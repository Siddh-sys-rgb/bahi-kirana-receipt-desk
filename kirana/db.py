"""SQLite persistence, review revisions and exactly-once ledger posting."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app, g


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA busy_timeout=10000')
    return connection


def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config['DATABASE'])
    return g.db


def init_database(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS receipts (
          id TEXT PRIMARY KEY, filename TEXT NOT NULL, image_name TEXT,
          content_hash TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
          raw_text TEXT NOT NULL, extraction TEXT NOT NULL, fields TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'review' CHECK(status IN ('review','approved','rejected')),
          revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          receipt_id TEXT NOT NULL UNIQUE REFERENCES receipts(id),
          merchant TEXT NOT NULL, purchase_date TEXT NOT NULL, category TEXT NOT NULL,
          amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
          reviewed_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          receipt_id TEXT NOT NULL REFERENCES receipts(id),
          action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL
        );
    ''')
    db.close()


def event(db, receipt_id, action, details):
    db.execute('INSERT INTO events(receipt_id,action,details,created_at) VALUES (?,?,?,?)',
               (receipt_id, action, json.dumps(details), now()))


def receipt(row):
    if not row:
        return None
    data = dict(row)
    data['fields'] = json.loads(data['fields'])
    data['extraction'] = json.loads(data['extraction'])
    return data


def create_receipt(db, receipt_id, filename, image_name, digest, source, text, extracted):
    timestamp = now()
    with db:
        db.execute('INSERT INTO receipts(id,filename,image_name,content_hash,source,raw_text,extraction,fields,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (receipt_id, filename, image_name, digest, source, text, json.dumps(extracted), json.dumps(extracted['fields']), timestamp, timestamp))
        event(db, receipt_id, 'extracted', {'source': source})


def update_review(db, receipt_id, revision, fields):
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM receipts WHERE id=?', (receipt_id,)).fetchone()
        if row is None:
            raise LookupError('Receipt not found.')
        if row['status'] != 'review' or row['revision'] != revision:
            raise Conflict('This bill changed or is already closed. Reload before saving.')
        old = json.loads(row['fields'])
        db.execute('UPDATE receipts SET fields=?,revision=revision+1,updated_at=? WHERE id=?',
                   (json.dumps(fields), now(), receipt_id))
        event(db, receipt_id, 'review_saved', {'before': old, 'after': fields, 'revision': revision+1})
        db.commit()
    except Exception:
        db.rollback()
        raise


def approve(db, receipt_id, revision, reviewed_by):
    from .parser import normalize_review, money, ValidationError
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM receipts WHERE id=?', (receipt_id,)).fetchone()
        if row is None:
            raise LookupError('Receipt not found.')
        if row['status'] == 'approved':
            result = db.execute('SELECT * FROM ledger WHERE receipt_id=?', (receipt_id,)).fetchone()
            db.commit()
            return dict(result), False
        if row['status'] != 'review' or row['revision'] != revision:
            raise Conflict('This bill changed or is already closed. Reload before approving.')
        fields, checks = normalize_review(json.loads(row['fields']))
        if not checks['balanced']:
            raise ValidationError('Item amounts + tax − discount must match the receipt total before approval.')
        timestamp = now()
        cursor = db.execute('INSERT INTO ledger(receipt_id,merchant,purchase_date,category,amount_paise,reviewed_by,created_at) VALUES (?,?,?,?,?,?,?)',
                           (receipt_id, fields['merchant'], fields['purchase_date'], fields['category'], money(fields['total']), reviewed_by, timestamp))
        db.execute("UPDATE receipts SET status='approved',revision=revision+1,updated_at=? WHERE id=?", (timestamp, receipt_id))
        event(db, receipt_id, 'approved', {'reviewed_by': reviewed_by, 'ledger_id': cursor.lastrowid})
        db.commit()
        return dict(db.execute('SELECT * FROM ledger WHERE id=?', (cursor.lastrowid,)).fetchone()), True
    except Exception:
        db.rollback()
        raise


def reject(db, receipt_id, revision):
    with db:
        cursor = db.execute("UPDATE receipts SET status='rejected',revision=revision+1,updated_at=? WHERE id=? AND status='review' AND revision=?", (now(), receipt_id, revision))
        if not cursor.rowcount:
            if not db.execute('SELECT 1 FROM receipts WHERE id=?', (receipt_id,)).fetchone():
                raise LookupError('Receipt not found.')
            raise Conflict('This bill changed or is already closed. Reload before rejecting.')
        event(db, receipt_id, 'rejected', {})

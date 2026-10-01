"""Explicit demo transcripts; do not mislabel seeded text as model inference."""
import hashlib
import json
from pathlib import Path
from .db import connect, create_receipt, approve
from .parser import parse_receipt

ROOT = Path(__file__).resolve().parents[1]

def seed(database):
    db = connect(database)
    try:
        # Seed once, including after users close or modify the sample records.
        if db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]:
            return
        for sample in json.loads((ROOT/'demo/receipts.json').read_text()):
            create_receipt(db, sample['id'], sample['image'], sample['image'],
                           hashlib.sha256(sample['text'].encode()).hexdigest(), 'demo-transcript',
                           sample['text'], parse_receipt(sample['text']))
            if sample['status'] == 'approved':
                approve(db, sample['id'], 1, 'Meera Patel (demo)')
    finally:
        db.close()

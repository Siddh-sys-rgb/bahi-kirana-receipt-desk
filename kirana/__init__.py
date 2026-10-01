"""Application factory for Bahi, a single-store local receipt review demo."""
import csv
import hashlib
import io
import json
import os
import secrets
import sqlite3
import uuid
from pathlib import Path
from flask import Flask, abort, jsonify, render_template, request, send_file, session
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
from . import db
from .ocr import ReceiptOCR, OCRUnavailable
from .parser import ValidationError, parse_receipt, normalize_review, rupees


ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(__name__, instance_path=str(ROOT/'instance'))
    app.config.update(DATABASE=str(ROOT/'instance'/'bahi.db'), UPLOAD_DIR=str(ROOT/'instance'/'uploads'),
                      MAX_CONTENT_LENGTH=6*1024*1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', SEED_DEMO=True, OCR_ENGINE=ReceiptOCR(),
                      TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'])
    if config:
        app.config.update(config)
    if not app.config.get('SECRET_KEY'):
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        secret_file = Path(app.instance_path)/'session.key'
        if not secret_file.exists():
            try:
                with secret_file.open('x') as stream:
                    os.chmod(secret_file, 0o600)
                    stream.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        app.config['SECRET_KEY'] = secret_file.read_text().strip()
    Path(app.config['UPLOAD_DIR']).mkdir(parents=True, exist_ok=True)
    db.init_database(app.config['DATABASE'])
    if app.config['SEED_DEMO']:
        from .demo import seed
        seed(app.config['DATABASE'])

    @app.teardown_appcontext
    def close_database(_):
        connection = __import__('flask').g.pop('db', None)
        if connection:
            connection.close()

    @app.before_request
    def csrf_check():
        if request.method in ('POST','PUT','PATCH','DELETE'):
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403, 'Cross-origin changes are blocked.')
            supplied = request.headers.get('X-CSRF-Token', '')
            if not supplied or not secrets.compare_digest(supplied, session.get('csrf', '')):
                abort(403, 'Refresh the page before making changes.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            code, message = exc.code, exc.description
        elif isinstance(exc, ValidationError):
            code, message = 422, str(exc)
        elif isinstance(exc, db.Conflict):
            code, message = 409, str(exc)
        elif isinstance(exc, LookupError):
            code, message = 404, str(exc)
        elif isinstance(exc, OCRUnavailable):
            code, message = 503, str(exc)
        else:
            app.logger.exception('Request failed')
            code, message = 500, 'The request could not be completed. Try again.'
        return jsonify(error=message), code

    def data():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValidationError('Send a JSON object.')
        return value

    def revision(value):
        result = value.get('revision')
        if type(result) is not int or result < 1:
            raise ValidationError('A positive integer review revision is required.')
        return result

    def load(receipt_id):
        value = db.receipt(db.get_db().execute('SELECT * FROM receipts WHERE id=?', (receipt_id,)).fetchone())
        if not value:
            raise LookupError('Receipt not found.')
        try:
            _, value['checks'] = normalize_review(value['fields'])
        except ValidationError as exc:
            value['checks'] = {'balanced': False, 'validation_error': str(exc)}
        value['image_url'] = '/api/receipts/'+receipt_id+'/image' if value['image_name'] else None
        return value

    @app.get('/')
    def home():
        return render_template('index.html')

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', app='Bahi', ocr='RapidOCR local model', ocr_installed=app.config['OCR_ENGINE'].available())

    @app.get('/api/bootstrap')
    def bootstrap():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(24)
        return jsonify(csrf_token=session['csrf'], store='Meera Kirana & General Store', owner='Meera Patel',
                       ocr_available=app.config['OCR_ENGINE'].available())

    @app.get('/api/receipts')
    def list_receipts():
        status = request.args.get('status', 'all')
        if status not in ('all','review','approved','rejected'):
            raise ValidationError('Unknown receipt status.')
        query = 'SELECT id FROM receipts' + (' WHERE status=?' if status != 'all' else '') + ' ORDER BY created_at DESC,id DESC'
        values = (status,) if status != 'all' else ()
        receipts = [load(row['id']) for row in db.get_db().execute(query, values).fetchall()]
        totals = db.get_db().execute('SELECT COUNT(*) count,COALESCE(SUM(amount_paise),0) total FROM ledger').fetchone()
        pending = db.get_db().execute("SELECT COUNT(*) FROM receipts WHERE status='review'").fetchone()[0]
        return jsonify(receipts=receipts, summary={'approved_count': totals['count'], 'approved_total': rupees(totals['total']), 'pending': pending})

    @app.get('/api/receipts/<receipt_id>')
    def detail(receipt_id):
        return jsonify(load(receipt_id))

    @app.get('/api/receipts/<receipt_id>/image')
    def image(receipt_id):
        value = load(receipt_id)
        if not value['image_name']:
            abort(404, 'No image attached to this receipt.')
        if value['source'] == 'demo-transcript':
            target = ROOT/'demo'/value['image_name']
        else:
            target = Path(app.config['UPLOAD_DIR'])/value['image_name']
        return send_file(target, mimetype='image/png', max_age=0)

    @app.post('/api/receipts')
    def upload():
        image_buffer = None
        if request.is_json:
            value = data()
            text = value.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 20000:
                raise ValidationError('Paste 1–20,000 characters of receipt text.')
            source, scores, filename = 'pasted-text', None, 'Pasted receipt'
            digest = hashlib.sha256(text.strip().encode()).hexdigest()
        else:
            file = request.files.get('receipt')
            if not file or not file.filename:
                raise ValidationError('Choose a PNG, JPG or WebP receipt image.')
            content = file.read(5*1024*1024+1)
            if len(content) > 5*1024*1024:
                abort(413, 'Receipt images must be smaller than 5 MB.')
            digest = hashlib.sha256(content).hexdigest()
            duplicate = db.get_db().execute('SELECT id FROM receipts WHERE content_hash=?', (digest,)).fetchone()
            if duplicate:
                return jsonify(error='This exact receipt is already in your inbox.', existing_id=duplicate['id']), 409
            try:
                with Image.open(io.BytesIO(content)) as original:
                    if original.format not in ('PNG','JPEG','WEBP') or original.width*original.height > 8_000_000:
                        raise ValidationError('Use a PNG, JPG or WebP image up to 8 megapixels.')
                    original.load()
                    clean = ImageOps.exif_transpose(original).convert('RGB')
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise ValidationError('That file is not a readable receipt image.') from exc
            text, scores = app.config['OCR_ENGINE'].extract(clean)
            source, filename = 'rapidocr', secure_filename(file.filename) or 'receipt.png'
            image_buffer = io.BytesIO()
            clean.save(image_buffer, format='PNG')
        extracted = parse_receipt(text, scores)
        receipt_id = uuid.uuid4().hex
        image_name = receipt_id+'.png' if image_buffer else None
        target = Path(app.config['UPLOAD_DIR'])/image_name if image_name else None
        try:
            if target:
                target.write_bytes(image_buffer.getvalue())
            db.create_receipt(db.get_db(), receipt_id, filename, image_name, digest, source, text, extracted)
        except sqlite3.IntegrityError:
            if target:
                target.unlink(missing_ok=True)
            duplicate = db.get_db().execute('SELECT id FROM receipts WHERE content_hash=?', (digest,)).fetchone()
            return jsonify(error='This exact receipt is already in your inbox.', existing_id=duplicate['id']), 409
        except Exception:
            if target:
                target.unlink(missing_ok=True)
            raise
        return jsonify(load(receipt_id)), 201

    @app.put('/api/receipts/<receipt_id>')
    def save_review(receipt_id):
        value = data()
        fields, _ = normalize_review(value.get('fields'))
        db.update_review(db.get_db(), receipt_id, revision(value), fields)
        return jsonify(load(receipt_id))

    @app.post('/api/receipts/<receipt_id>/approve')
    def approve(receipt_id):
        value = data()
        if value.get('verified') is not True:
            raise ValidationError('Confirm you checked the fields against the receipt.')
        result, created = db.approve(db.get_db(), receipt_id, revision(value), 'Meera Patel')
        return jsonify(ledger_entry=result, created=created, receipt=load(receipt_id)), 201 if created else 200

    @app.post('/api/receipts/<receipt_id>/reject')
    def reject(receipt_id):
        value = data()
        db.reject(db.get_db(), receipt_id, revision(value))
        return jsonify(load(receipt_id))

    @app.get('/api/receipts/<receipt_id>/events')
    def events(receipt_id):
        load(receipt_id)
        rows = db.get_db().execute('SELECT action,details,created_at FROM events WHERE receipt_id=? ORDER BY id', (receipt_id,)).fetchall()
        return jsonify(events=[{'action': r['action'], 'details': json.loads(r['details']), 'created_at': r['created_at']} for r in rows])

    @app.get('/api/ledger')
    def ledger():
        rows = db.get_db().execute('SELECT * FROM ledger ORDER BY purchase_date DESC,id DESC').fetchall()
        return jsonify(entries=[dict(r, amount=rupees(r['amount_paise'])) for r in rows])

    @app.get('/api/ledger.csv')
    def export():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date','Supplier','Category','Amount INR','Reviewed by','Receipt ID'])
        def safe(value):
            text = str(value)
            return "'"+text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text
        for row in db.get_db().execute('SELECT * FROM ledger ORDER BY purchase_date,id'):
            writer.writerow([row['purchase_date'],safe(row['merchant']),safe(row['category']),rupees(row['amount_paise']),safe(row['reviewed_by']),row['receipt_id']])
        return app.response_class(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition':'attachment; filename="bahi-approved-ledger.csv"'})

    return app

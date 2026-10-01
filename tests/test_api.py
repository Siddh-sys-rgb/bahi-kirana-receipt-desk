import csv
import io
from copy import deepcopy
from pathlib import Path

import pytest

from kirana import db
from kirana.ocr import OCRUnavailable
from kirana.parser import ValidationError
from kirana.parser import parse_receipt
from conftest import TEXT, image_bytes


def save(client, csrf, receipt, fields=None, revision=None):
    return client.put('/api/receipts/' + receipt['id'],
                      json={'fields': fields or receipt['fields'],
                            'revision': receipt['revision'] if revision is None else revision}, headers=csrf)


def approve(client, csrf, receipt, **extra):
    return client.post('/api/receipts/' + receipt['id'] + '/approve',
                       json={'revision': receipt['revision'], 'verified': True, **extra}, headers=csrf)


def test_home_health_and_headers(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Bahi' in response.data
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert response.headers['X-Frame-Options'] == 'DENY'
    health = client.get('/api/health')
    assert health.json['status'] == 'ok'
    assert health.headers['Cache-Control'] == 'no-store'
    bootstrap = client.get('/api/bootstrap')
    assert 'HttpOnly' in bootstrap.headers['Set-Cookie']
    assert 'SameSite=Strict' in bootstrap.headers['Set-Cookie']


def test_csrf_and_origin_are_required(client, csrf):
    assert client.post('/api/receipts', json={'text': TEXT}).status_code == 403
    assert client.post('/api/receipts', json={'text': TEXT}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    response = client.post('/api/receipts', json={'text': TEXT}, headers={**csrf, 'Origin': 'https://evil.example'})
    assert response.status_code == 403
    assert client.post('/api/receipts', json={'text': TEXT}, headers={**csrf, 'Origin': 'http://localhost'}).status_code == 201


def test_full_review_approve_and_idempotent_replay(client, csrf, receipt):
    fields = deepcopy(receipt['fields'])
    fields['merchant'] = 'Desai Dairy Suppliers'
    updated = save(client, csrf, receipt, fields)
    assert updated.status_code == 200
    assert updated.json['revision'] == 2
    assert save(client, csrf, receipt, fields).status_code == 409
    assert approve(client, csrf, receipt).status_code == 409
    posted = approve(client, csrf, updated.json)
    assert posted.status_code == 201
    assert posted.json['ledger_entry']['amount_paise'] == 69600
    assert posted.json['receipt']['status'] == 'approved'
    replay = approve(client, csrf, updated.json)
    assert replay.status_code == 200 and replay.json['created'] is False
    assert replay.json['ledger_entry']['id'] == posted.json['ledger_entry']['id']
    assert len(client.get('/api/ledger').json['entries']) == 1
    assert save(client, csrf, posted.json['receipt']).status_code == 409
    summary = client.get('/api/receipts').json['summary']
    assert summary == {'approved_count': 1, 'approved_total': '696.00', 'pending': 0}
    events = client.get(f"/api/receipts/{receipt['id']}/events").json['events']
    assert [event['action'] for event in events] == ['extracted', 'review_saved', 'approved']
    assert events[1]['details']['before']['merchant'] == receipt['fields']['merchant']
    assert events[1]['details']['after']['merchant'] == fields['merchant']


def test_approval_requires_confirmation_and_balance(client, csrf, receipt):
    assert approve(client, csrf, receipt, verified=False).status_code == 422
    assert approve(client, csrf, receipt, verified='true').status_code == 422
    fields = deepcopy(receipt['fields'])
    fields['total'] = '726.00'
    updated = save(client, csrf, receipt, fields).json
    response = approve(client, csrf, updated)
    assert response.status_code == 422
    assert client.get('/api/ledger').json['entries'] == []
    assert client.get('/api/receipts/' + receipt['id']).json['status'] == 'review'
    fields['tax'] = '30.00'
    updated = save(client, csrf, updated, fields).json
    assert approve(client, csrf, updated).status_code == 201


@pytest.mark.parametrize('value', [None, True, 0, -1, '1', 1.5])
def test_invalid_revisions_are_rejected(client, csrf, receipt, value):
    assert save(client, csrf, receipt, revision=value if value is not None else 'missing').status_code == 422
    assert approve(client, csrf, receipt, revision=value).status_code == 422


def test_rejected_receipts_are_closed_without_posting(client, csrf, receipt):
    path = f"/api/receipts/{receipt['id']}/reject"
    assert client.post(path, json={'revision': 99}, headers=csrf).status_code == 409
    response = client.post(path, json={'revision': 1}, headers=csrf)
    assert response.status_code == 200 and response.json['status'] == 'rejected'
    assert approve(client, csrf, response.json).status_code == 409
    assert save(client, csrf, response.json).status_code == 409
    assert client.post(path, json={'revision': 2}, headers=csrf).status_code == 409
    assert client.get('/api/ledger').json['entries'] == []
    assert len(client.get('/api/receipts?status=rejected').json['receipts']) == 1
    assert client.get('/api/receipts?status=review').json['receipts'] == []


def test_exact_duplicate_text_returns_original_id(client, csrf, receipt):
    duplicate = client.post('/api/receipts', json={'text': '  ' + TEXT + '  '}, headers=csrf)
    assert duplicate.status_code == 409 and duplicate.json['existing_id'] == receipt['id']
    assert len(client.get('/api/receipts').json['receipts']) == 1


@pytest.mark.parametrize('body', [{}, {'text': ''}, {'text': None}, {'text': 'a' * 20001}, []])
def test_invalid_text_body(client, csrf, body):
    assert client.post('/api/receipts', json=body, headers=csrf).status_code == 422


def test_invalid_json_and_content_type(client, csrf):
    assert client.post('/api/receipts', data='{oops', content_type='application/json', headers=csrf).status_code == 400
    assert client.put('/api/receipts/unknown', data='oops', headers=csrf).status_code == 415


def test_missing_resources_and_unknown_filters(client, csrf, receipt):
    for path in ['/missing', '/api/receipts/unknown', '/api/receipts/unknown/image', '/api/receipts/unknown/events']:
        assert client.get(path).status_code == 404
    assert client.get('/api/receipts?status=anything').status_code == 422
    assert save(client, csrf, {**receipt, 'id': 'unknown'}).status_code == 404
    assert approve(client, csrf, {**receipt, 'id': 'unknown'}).status_code == 404
    assert client.post('/api/receipts/unknown/reject', json={'revision': 1}, headers=csrf).status_code == 404
    assert client.get(f"/api/receipts/{receipt['id']}/image").status_code == 404


@pytest.mark.parametrize('format', ['PNG', 'JPEG', 'WEBP'])
def test_real_image_decoding_normalisation_and_duplicate_detection(app, client, csrf, format):
    content = image_bytes(format)
    def upload():
        return client.post('/api/receipts', data={'receipt': (io.BytesIO(content), '../../fake.svg')}, headers=csrf)
    response = upload()
    assert response.status_code == 201
    assert response.json['filename'] == 'fake.svg'
    assert response.json['source'] == 'rapidocr'
    image = client.get(response.json['image_url'])
    assert image.status_code == 200 and image.data.startswith(b'\x89PNG')
    assert image.headers['Content-Type'].startswith('image/png')
    duplicate = upload()
    assert duplicate.status_code == 409
    assert duplicate.json['existing_id'] == response.json['id']
    assert app.config['OCR_ENGINE'].calls == 1
    assert len(list(Path(app.config['UPLOAD_DIR']).iterdir())) == 1


@pytest.mark.parametrize('content,filename,expected', [(b'<svg><script>alert(1)</script></svg>', 'bill.png', 422),
                                                       (b'not an image', 'bill.jpg', 422),
                                                       (image_bytes('GIF'), 'bill.gif', 422),
                                                       (b'', 'empty.png', 422),
                                                       (b'x' * (5 * 1024 * 1024 + 1), 'big.png', 413)])
def test_upload_refuses_invalid_formats_and_sizes(app, client, csrf, content, filename, expected):
    response = client.post('/api/receipts', data={'receipt': (io.BytesIO(content), filename)}, headers=csrf)
    assert response.status_code == expected
    assert app.config['OCR_ENGINE'].calls == 0
    assert list(Path(app.config['UPLOAD_DIR']).iterdir()) == []


def test_large_pixels_and_request_limits(app, client, csrf):
    response = client.post('/api/receipts', data={'receipt': (io.BytesIO(image_bytes(size=(3000, 3000))), 'large.png')}, headers=csrf)
    assert response.status_code == 422
    response = client.post('/api/receipts', data=b'x' * (6 * 1024 * 1024 + 1), content_type='application/json', headers=csrf)
    assert response.status_code == 413
    assert app.config['OCR_ENGINE'].calls == 0


def test_empty_upload(app, client, csrf):
    assert client.post('/api/receipts', data={}, headers=csrf).status_code == 422


@pytest.mark.parametrize('exception,expected', [(OCRUnavailable('OCR busy'), 503), (ValidationError('No readable text'), 422)])
def test_ocr_failures_do_not_leave_files(app, client, csrf, exception, expected):
    def fail(_):
        raise exception
    app.config['OCR_ENGINE'].extract = fail
    response = client.post('/api/receipts', data={'receipt': (io.BytesIO(image_bytes()), 'bill.png')}, headers=csrf)
    assert response.status_code == expected
    assert list(Path(app.config['UPLOAD_DIR']).iterdir()) == []
    assert client.get('/api/receipts').json['receipts'] == []


def test_database_failure_cleans_staged_image(app, client, csrf, monkeypatch):
    def fail(*_):
        raise RuntimeError('private diagnostic')
    monkeypatch.setattr(db, 'create_receipt', fail)
    response = client.post('/api/receipts', data={'receipt': (io.BytesIO(image_bytes()), 'bill.png')}, headers=csrf)
    assert response.status_code == 500
    assert 'private diagnostic' not in response.json['error']
    assert list(Path(app.config['UPLOAD_DIR']).iterdir()) == []


def test_missing_fields_can_be_reviewed_manually(client, csrf):
    response = client.post('/api/receipts', json={'text': 'Receipt'}, headers=csrf)
    assert response.status_code == 201
    assert 'validation_error' in response.json['checks']
    assert approve(client, csrf, response.json).status_code == 422
    assert save(client, csrf, response.json, parse_receipt(TEXT)['fields']).status_code == 200


def test_csv_escapes_spreadsheet_formulas_and_quotes(client, csrf, receipt):
    fields = deepcopy(receipt['fields'])
    fields['merchant'] = '=HYPERLINK("https://example.invalid","Meera")'
    updated = save(client, csrf, receipt, fields).json
    assert approve(client, csrf, updated).status_code == 201
    response = client.get('/api/ledger.csv')
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[1][1] == "'" + fields['merchant']
    assert rows[1][3] == '696.00'
    assert 'attachment' in response.headers['Content-Disposition']


def test_arbitrary_host_is_not_trusted(client):
    assert client.get('/api/bootstrap', base_url='http://evil.example').status_code == 400

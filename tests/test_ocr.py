import io
import json

import pytest
from PIL import Image

from kirana.ocr import OCRUnavailable, ReceiptOCR
from kirana.parser import ValidationError, normalize_review, parse_receipt
from conftest import ROOT, SAMPLES


def test_busy_model_returns_retryable_error():
    model = ReceiptOCR()
    model._lock.acquire()
    try:
        with pytest.raises(OCRUnavailable, match='Another receipt'):
            model.extract(Image.new('RGB', (10, 10)))
    finally:
        model._lock.release()


def test_blank_detection_is_a_reviewable_error_and_releases_lock():
    model = ReceiptOCR()
    model._engine = lambda image: (None, None)
    with pytest.raises(ValidationError, match='No readable text'):
        model.extract(Image.new('RGB', (10, 10)))
    assert not model._lock.locked()


@pytest.mark.ocr
@pytest.mark.parametrize('sample', SAMPLES, ids=[sample['id'] for sample in SAMPLES])
def test_actual_local_model_extracts_authored_receipt_fields(sample):
    model = ReceiptOCR()
    with Image.open(ROOT / 'demo' / sample['image']) as image:
        text, scores = model.extract(image)
    actual = parse_receipt(text, scores)
    labels = json.loads((ROOT / 'demo' / 'labels.json').read_text())
    assert actual['fields'] == labels[sample['id']]
    assert actual['ocr_score'] is not None
    assert normalize_review(actual['fields'])[1]['balanced'] == (sample['id'] != 'demo-staples')


@pytest.mark.ocr
def test_actual_model_through_upload_api(app, client, csrf):
    app.config['OCR_ENGINE'] = ReceiptOCR()
    content = (ROOT / 'demo' / SAMPLES[1]['image']).read_bytes()
    response = client.post('/api/receipts', data={'receipt': (io.BytesIO(content), 'desai.png')}, headers=csrf)
    assert response.status_code == 201
    assert response.json['source'] == 'rapidocr'
    assert response.json['fields']['total'] == '696.00'
    assert response.json['checks']['balanced']

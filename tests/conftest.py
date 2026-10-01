import io
import json
from pathlib import Path

import pytest
from PIL import Image

from kirana import create_app


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = json.loads((ROOT / 'demo' / 'receipts.json').read_text())
TEXT = SAMPLES[1]['text']


class StubOCR:
    calls = 0

    def available(self):
        return True

    def extract(self, image):
        self.calls += 1
        return TEXT, [0.98]


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'SECRET_KEY': 'test-only-secret',
                       'DATABASE': str(tmp_path / 'test.db'),
                       'UPLOAD_DIR': str(tmp_path / 'uploads'),
                       'SEED_DEMO': False, 'OCR_ENGINE': StubOCR()})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf(client):
    return {'X-CSRF-Token': client.get('/api/bootstrap').json['csrf_token']}


@pytest.fixture
def receipt(client, csrf):
    response = client.post('/api/receipts', json={'text': TEXT}, headers=csrf)
    assert response.status_code == 201
    return response.json


def image_bytes(format='PNG', size=(100, 100)):
    output = io.BytesIO()
    Image.new('RGB', size, 'white').save(output, format=format)
    return output.getvalue()

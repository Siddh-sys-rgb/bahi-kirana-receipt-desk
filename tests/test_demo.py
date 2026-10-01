from kirana import create_app
from kirana.demo import seed


def test_demo_seeds_once_with_honest_source_labels(tmp_path):
    database = str(tmp_path / 'demo.db')
    app = create_app({'SECRET_KEY': 'test-only', 'DATABASE': database,
                      'UPLOAD_DIR': str(tmp_path / 'uploads'), 'SEED_DEMO': True})
    seed(database)
    client = app.test_client()
    response = client.get('/api/receipts').json
    assert len(response['receipts']) == 3
    assert response['summary'] == {'approved_count': 1, 'approved_total': '2100.00', 'pending': 2}
    assert all(receipt['source'] == 'demo-transcript' for receipt in response['receipts'])
    assert all(receipt['extraction']['ocr_score'] is None for receipt in response['receipts'])
    assert client.get('/api/receipts/demo-staples').json['checks']['difference'] == '30.00'
    assert client.get('/api/receipts/demo-shah/image').data.startswith(b'\x89PNG')

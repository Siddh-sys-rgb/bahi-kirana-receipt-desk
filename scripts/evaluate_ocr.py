"""Offline OCR acceptance check against independently authored field labels.

Run from the repository root: python scripts/evaluate_ocr.py
These three clean synthetic receipts are not a real-world accuracy benchmark.
"""
import json
import sys
from pathlib import Path
from time import perf_counter

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kirana.ocr import ReceiptOCR
from kirana.parser import parse_receipt, normalize_review


def main():
    samples = json.loads((ROOT / 'demo' / 'receipts.json').read_text())
    labels = json.loads((ROOT / 'demo' / 'labels.json').read_text())
    model, rows = ReceiptOCR(), []
    for sample in samples:
        started = perf_counter()
        with Image.open(ROOT / 'demo' / sample['image']) as image:
            text, scores = model.extract(image)
        extracted = parse_receipt(text, scores)
        fields = extracted['fields']
        expected = labels[sample['id']]
        mismatches = [key for key, value in expected.items() if fields.get(key) != value]
        rows.append({'receipt': sample['id'], 'exact_fields_match': not mismatches,
                     'mismatched_fields': mismatches, 'mean_text_score': extracted['ocr_score'],
                     'seconds': round(perf_counter() - started, 3),
                     'balanced': normalize_review(fields)[1]['balanced']})
    report = {'dataset': 'Three original, fictional English printed INR receipts',
              'limitation': 'Synthetic acceptance check; not a real-world accuracy estimate.',
              'model': 'rapidocr-onnxruntime 1.4.4, bundled ONNX models, CPU',
              'matched': sum(row['exact_fields_match'] for row in rows), 'total': len(rows), 'results': rows}
    output = ROOT / 'instance' / 'ocr-evaluation.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['matched'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

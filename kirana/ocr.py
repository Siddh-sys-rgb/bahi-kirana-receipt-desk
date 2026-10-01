"""Local learned OCR; models ship in the pinned RapidOCR wheel."""
import importlib.util
import threading
from PIL import Image, ImageOps
from .parser import ValidationError


class OCRUnavailable(RuntimeError):
    pass


class ReceiptOCR:
    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def available(self):
        return importlib.util.find_spec('rapidocr_onnxruntime') is not None

    def extract(self, image):
        if not self._lock.acquire(blocking=False):
            raise OCRUnavailable('Another receipt is being read. Try again in a moment.')
        try:
            if self._engine is None:
                from rapidocr_onnxruntime import RapidOCR
                self._engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
            import numpy as np
            array = np.array(ImageOps.exif_transpose(image).convert('RGB'))
            result, _ = self._engine(array)
            if not result:
                raise ValidationError('No readable text was found. Try a sharper English receipt or paste its text.')
            fragments = []
            for box, text, score in result:
                fragments.append({'y': sum(p[1] for p in box)/4, 'x': min(p[0] for p in box),
                                  'height': max(p[1] for p in box)-min(p[1] for p in box), 'text': text, 'score': float(score)})
            fragments.sort(key=lambda item: item['y'])
            rows = []
            for fragment in fragments:
                if rows and abs(fragment['y'] - rows[-1][0]['y']) < max(10, fragment['height']*.55):
                    rows[-1].append(fragment)
                else:
                    rows.append([fragment])
            text = '\n'.join(' '.join(f['text'] for f in sorted(row, key=lambda f:f['x'])) for row in rows)
            return text, [f['score'] for f in fragments]
        except ImportError as exc:
            raise OCRUnavailable('Local OCR is not installed. Install requirements.txt or paste receipt text.') from exc
        finally:
            self._lock.release()

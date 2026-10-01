"""Draw original fictional receipts for demonstrations and reproducible OCR checks."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]

def font(size):
    for path in ['/System/Library/Fonts/Supplemental/Courier New.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)

def main():
    samples = json.loads((ROOT/'demo/receipts.json').read_text())
    for sample in samples:
        lines = sample['text'].splitlines()
        image = Image.new('RGB', (1000, 230+len(lines)*62), '#fffdf7')
        draw = ImageDraw.Draw(image)
        draw.rectangle((22,22,image.width-22,image.height-22), outline='#d7d2c6', width=2)
        y = 65
        for i, line in enumerate(lines):
            size = 42 if i == 0 else 31
            draw.text((65,y),line,font=font(size),fill='#141a16')
            y += 62
            if i in (3,4) or line.startswith('Subtotal'):
                draw.line((65,y-13,935,y-13),fill='#cbc8bb',width=2)
        draw.text((65,image.height-75),'FICTIONAL DEMO / INR',font=font(22),fill='#6d726e')
        image.save(ROOT/'demo'/sample['image'])
        print(sample['image'])

if __name__ == '__main__':
    main()

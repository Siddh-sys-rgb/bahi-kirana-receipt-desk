# Bahi validation record

The implementation was checked locally using macOS, Python 3.12.14, Flask 3.1.3, RapidOCR 1.4.4 and ONNX Runtime 1.19.2. The dependency versions are recorded in `constraints-tested.txt`. No remote CI run or GitHub upload was performed.

## Automated results

`python -m pytest --cov=kirana --cov-report=term-missing` passed **98 tests**, including four tests marked `ocr` that use the actual bundled models. The suite reported **97% Python statement coverage**. Coverage is not evidence that every UI behaviour or real receipt layout is supported.

| Area | Behaviour verified |
| --- | --- |
| INR parsing | Exact decimal/paise conversion, fractional quantities, one-paise tolerance, invalid values and bounded numeric input |
| Receipt parsing | Date formats, CGST/SGST, discounts, missing-field warnings, foreign currencies, long phone/invoice numbers and negative total refusal |
| Reviews | Save/reload, stale revision conflicts, required verification, mismatched total blocking, corrected tax approval and closed records |
| Transactions | Two simultaneous approvals yield one entry; two simultaneous saves yield one success and one conflict |
| Uploads | Decode PNG/JPEG/WebP, re-encode to PNG, reject spoofed images/GIF/oversized requests/pixel dimensions, skip duplicate OCR, clean staged images on failures |
| API protection | CSRF, mutation origin checks, untrusted hosts, security headers, generic internal errors and CSV formula escaping |
| Demo data | Seed once, label transcript fixtures honestly, preserve expected totals and mismatch |
| OCR | Actual model against three independent fixture labels and a complete image upload through Flask |

The OCR adapter's busy and blank-result paths are tested without model inference. Most API tests use a stub to isolate HTTP and database behaviour; the marked tests explicitly replace it with the real OCR adapter.

## OCR acceptance results

The original images are clean, synthetic English receipts. Ground truth is hand-authored in `demo/labels.json`, independently of the parser. The acceptance script compared the full supplier/date/items/tax/discount/total field objects.

| Image | Exact field object match | Mean OCR text score | Total check |
| --- | --- | --- | --- |
| Shah Wholesale | Yes | 0.984 | ₹2,140 − ₹40 = ₹2,100 |
| Desai Dairy | Yes | 0.987 | ₹696 = ₹696 |
| Patel Staples | Yes | 0.976 | ₹1,220 differs from ₹1,250; approval blocked |

These results establish a repeatable acceptance check on these three images. They are not a held-out customer benchmark or a claim of 100% real-world receipt accuracy. Text scores come from the recogniser and are not calibrated field correctness probabilities. No external receipt corpus was downloaded or used for training.

## Browser checks

The local interface was exercised in the in-app browser at its default desktop viewport (1280 × 720) and at a temporary mobile viewport (390 × 844).

- Overview loaded the seeded supplier bills and expected metrics.
- Approval without confirmation displayed an explanation.
- The Patel sample's ₹30 mismatch was blocked by the backend after confirmation.
- Uploading `desai-dairy.png` ran the actual OCR model and showed the image, text score and suggested fields.
- Supplier capitalisation was changed, saved, and retained on reload.
- The uploaded Desai bill was approved, became read-only and appeared in the purchase khata.
- Re-uploading the exact image displayed a link to its existing receipt.
- Pasted text produced an editable receipt, its Read text tab showed the source, and rejection closed it without posting to the ledger.
- Export CSV downloaded a file from the ledger screen.
- Mobile overview and receipt review had document width equal to the 390-pixel viewport. Adding and removing an item worked at that size.
- Direct review reload retained the pending inbox count after its API responses arrived.
- Browser console inspection after the OCR upload reported no warning/error entries.

The screenshots in `docs/screenshots/` are actual captures from these checks. The overview and khata show the demo after approval of the uploaded ₹696 bill: two ledger entries totalling ₹2,796. A clean database starts with only the seeded ₹2,100 entry.

## Checks to repeat when extending the app

Add your own consented, redacted receipt images and independent field labels before claiming broader extraction accuracy. A varied evaluation set should include different store layouts, skew, blur, tax formats, low contrast and unsupported scripts. Treat arithmetic consistency as a review aid: it cannot establish that a model read the right figures.

The local concurrency tests verify ledger correctness for the tested two-worker cases; they are not a load test. Linux/Windows installations and the prepared CI matrix have not been executed in this delivery. There is no production authentication, external audit store or background job system.

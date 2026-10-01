"""Transparent receipt parsing and exact INR arithmetic after OCR."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class ValidationError(ValueError):
    pass


def money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValidationError('Enter a valid amount with at most two decimal places.')
    if len(str(value)) > 30:
        raise ValidationError('Amount is too long.')
    try:
        number = Decimal(str(value).replace(',', '').strip())
    except InvalidOperation as exc:
        raise ValidationError('Enter a valid amount.') from exc
    if not number.is_finite() or number < 0 or number > Decimal('10000000'):
        raise ValidationError('Amount must be between 0 and 1 crore rupees.')
    if number != number.quantize(Decimal('0.01')):
        raise ValidationError('Amounts may have at most two decimal places.')
    return int(number * 100)


def rupees(paise):
    return f'{Decimal(paise) / 100:.2f}'


def clean_text(value, name, maximum=150):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValidationError(f'{name} must be 1–{maximum} characters.')
    value = value.strip()
    if any(ord(c) < 32 for c in value):
        raise ValidationError(f'{name} contains control characters.')
    return value


def normalize_review(data):
    if not isinstance(data, dict):
        raise ValidationError('Review must be a JSON object.')
    merchant = clean_text(data.get('merchant'), 'Supplier')
    try:
        if not isinstance(data.get('purchase_date'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data['purchase_date']):
            raise ValueError
        purchase_date = date.fromisoformat(data.get('purchase_date', ''))
    except (ValueError, TypeError) as exc:
        raise ValidationError('Choose a valid purchase date.') from exc
    if not 1900 <= purchase_date.year <= 2100:
        raise ValidationError('Purchase date must be between 1900 and 2100.')
    if data.get('currency', 'INR') != 'INR':
        raise ValidationError('This ledger supports INR receipts only.')
    category = data.get('category', 'Stock purchase')
    if category not in ('Stock purchase', 'Store supplies', 'Transport', 'Other'):
        raise ValidationError('Choose a supported category.')
    supplied = data.get('items')
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= 50:
        raise ValidationError('Add between 1 and 50 line items.')
    items = []
    for item in supplied:
        if not isinstance(item, dict):
            raise ValidationError('Invalid line item.')
        name = clean_text(item.get('name'), 'Item', 100)
        try:
            if isinstance(item.get('quantity'), bool):
                raise InvalidOperation
            if len(str(item.get('quantity', ''))) > 30:
                raise InvalidOperation
            quantity = Decimal(str(item.get('quantity', '')))
        except InvalidOperation as exc:
            raise ValidationError('Quantity must be a positive number.') from exc
        if not quantity.is_finite() or not 0 < quantity <= 100000 or quantity != quantity.quantize(Decimal('.001')):
            raise ValidationError('Quantity must be positive with at most three decimal places.')
        unit = money(item.get('unit_price', ''))
        amount = money(item.get('amount', ''))
        calculated = int((quantity * unit).quantize(Decimal('1')))
        if abs(calculated - amount) > 1:
            raise ValidationError(f'{name}: quantity × rate does not match its amount.')
        items.append({'name': name, 'quantity': str(quantity), 'unit_price': rupees(unit), 'amount': rupees(amount)})
    tax = money(data.get('tax', '0'))
    discount = money(data.get('discount', '0'))
    total = money(data.get('total', ''))
    subtotal = sum(money(item['amount']) for item in items)
    calculated = subtotal + tax - discount
    result = {'merchant': merchant, 'purchase_date': purchase_date.isoformat(), 'currency': 'INR',
              'category': category, 'items': items, 'tax': rupees(tax), 'discount': rupees(discount), 'total': rupees(total)}
    checks = {'subtotal': rupees(subtotal), 'calculated_total': rupees(calculated),
              'difference': rupees(total-calculated), 'balanced': calculated >= 0 and abs(total-calculated) <= 1}
    return result, checks


NUMBER = r'\d[\d,]*(?:\.\d{1,2})?'


def parse_receipt(text, scores=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise ValidationError('Receipt text must contain 1–20,000 characters.')
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    result = {'merchant': '', 'purchase_date': '', 'currency': 'INR', 'category': 'Stock purchase',
              'items': [], 'tax': '0.00', 'discount': '0.00', 'total': ''}
    evidence, warnings = {}, []
    date_match = re.search(r'\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b', text)
    if date_match:
        for pattern in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                result['purchase_date'] = datetime.strptime(date_match[1], pattern).date().isoformat()
                evidence['purchase_date'] = date_match[1]
                break
            except ValueError:
                pass
    for line in lines[:5]:
        if re.search(r'[A-Za-z]{3}', line) and not re.search(r'^(tax invoice|receipt|bill|cash memo|date|gstin)', line, re.I):
            result['merchant'] = line
            evidence['merchant'] = line
            break
    taxes = []
    for line in lines:
        if re.match(r'^(grand\s*total|net\s*total|total|amount\s*due|tax|[cs]gst|igst|gst|discount)\b', line, re.I) and re.search(r'-\s*\d[\d,]*(?:\.\d{1,2})?\s*$', line):
            raise ValidationError('Negative receipt amounts are not supported. Check the original bill.')
        amount_match = re.search(rf'({NUMBER})\s*$', line)
        if not amount_match:
            continue
        if re.fullmatch(rf'(grand\s*total|net\s*total|total\s*payable|total\s*amount|total|amount\s*due)\s*[:=]?\s*(?:₹|Rs\.?|INR)?\s*{NUMBER}', line, re.I):
            value = rupees(money(amount_match[1]))
            result['total'] = value
            evidence['total'] = line
        elif re.match(r'^(cgst|sgst|igst|gst|tax)\b', line, re.I):
            value = rupees(money(amount_match[1]))
            taxes.append(money(value))
            evidence.setdefault('tax', []).append(line)
        elif re.match(r'^discount\b', line, re.I):
            value = rupees(money(amount_match[1]))
            result['discount'] = value
        else:
            match = re.match(rf'^(.+?)\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*$', line)
            if match and not re.search(r'^(date|bill|invoice|phone|tel|gstin|sub\s*total|subtotal|round)', line, re.I):
                name, quantity, rate, amount = match.groups()
                try:
                    money(rate); money(amount)
                    if Decimal(quantity.replace(',', '')) <= 0:
                        continue
                except (ValidationError, InvalidOperation):
                    continue
                result['items'].append({'name': name, 'quantity': quantity.replace(',', ''), 'unit_price': rupees(money(rate)), 'amount': rupees(money(amount))})
    result['tax'] = rupees(sum(taxes))
    if re.search(r'\b(USD|EUR|IDR)\b|\$', text, re.I):
        result['currency'] = 'OTHER'
        warnings.append('Foreign currency detected. This ledger accepts INR only.')
    for key in ('merchant', 'purchase_date', 'total'):
        if not result[key]:
            warnings.append(f'{key.replace("_", " ").capitalize()} was not recognised; fill it from the receipt.')
    if not result['items']:
        warnings.append('No item rows were recognised. Add the quantities, rates and amounts manually.')
    if scores and any(s < .88 for s in scores):
        warnings.append('Some OCR text has a low recognition score. Check it carefully.')
    return {'fields': result, 'evidence': evidence, 'warnings': warnings,
            'ocr_score': round(sum(scores)/len(scores), 3) if scores else None}

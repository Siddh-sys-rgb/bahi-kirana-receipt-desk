from copy import deepcopy
from decimal import Decimal

import pytest

from kirana.parser import ValidationError, money, normalize_review, parse_receipt, rupees
from conftest import TEXT


@pytest.mark.parametrize('value,expected', [('0', 0), ('0.29', 29), ('1,23,456.78', 12345678),
                                           (Decimal('2.10'), 210), ('10000000', 1000000000)])
def test_money_is_exact(value, expected):
    assert money(value) == expected
    assert money(rupees(expected)) == expected


@pytest.mark.parametrize('value', [True, None, {}, [], 'NaN', 'Infinity', '-1', '1.005',
                                  '10000000.01', 'x', '9' * 10000])
def test_money_rejects_invalid_or_excessive_values(value):
    with pytest.raises(ValidationError):
        money(value)


def test_parse_transcript_and_reconcile():
    result = parse_receipt(TEXT, [.99, .98])
    fields, checks = normalize_review(result['fields'])
    assert fields['merchant'] == 'DESAI DAIRY SUPPLIERS'
    assert fields['purchase_date'] == '2026-09-29'
    assert fields['total'] == '696.00'
    assert len(fields['items']) == 2
    assert checks['balanced'] is True
    assert result['evidence']['total'] == 'Grand Total 696.00'
    assert result['warnings'] == []
    assert result['ocr_score'] == .985


@pytest.mark.parametrize('printed', ['2026-09-30', '30/09/2026', '30-09-2026'])
def test_recognises_date_formats(printed):
    assert parse_receipt('MEERA SUPPLIER\nDate ' + printed)['fields']['purchase_date'] == '2026-09-30'


def test_taxes_discount_and_fractional_quantity():
    text = 'MEERA SUPPLIER\nDate 30/09/2026\nRice 1.5 20.00 30.00\nCGST 0.75\nSGST 0.75\nDiscount 1.00\nGrand Total 30.50'
    fields, checks = normalize_review(parse_receipt(text)['fields'])
    assert fields['tax'] == '1.50'
    assert fields['items'][0]['quantity'] == '1.5'
    assert checks['balanced']


def test_missing_fields_and_low_scores_are_visible():
    result = parse_receipt('Receipt\nDate 31/02/2026', [.5])
    assert result['fields']['total'] == ''
    assert len(result['warnings']) == 5


def test_foreign_currency_cannot_be_approved_as_inr():
    fields = parse_receipt(TEXT + '\nUSD')['fields']
    assert fields['currency'] == 'OTHER'
    with pytest.raises(ValidationError, match='INR'):
        normalize_review(fields)


@pytest.mark.parametrize('text', ['', ' ' * 5, None, 'a' * 20001, 'SHOP\nGrand Total -50.00'])
def test_invalid_transcripts_do_not_create_positive_amounts(text):
    with pytest.raises(ValidationError):
        parse_receipt(text)


@pytest.mark.parametrize('key,value', [('merchant', ''), ('merchant', 'A\nB'), ('merchant', 'a' * 151),
                                     ('purchase_date', '2026-02-30'), ('purchase_date', '20260929'),
                                     ('purchase_date', '1800-09-29'), ('purchase_date', None),
                                     ('currency', 'USD'), ('category', 'Unknown'), ('items', []),
                                     ('items', [None]), ('items', [{}] * 51), ('tax', True)])
def test_review_field_validation(key, value):
    fields = parse_receipt(TEXT)['fields']
    fields[key] = value
    with pytest.raises(ValidationError):
        normalize_review(fields)


@pytest.mark.parametrize('key,value', [('quantity', '0'), ('quantity', '-2'), ('quantity', '0.0001'),
                                     ('quantity', 'NaN'), ('quantity', True), ('quantity', '1' * 100),
                                     ('name', ''), ('amount', '335.00'), ('unit_price', '-2')])
def test_item_validation(key, value):
    fields = parse_receipt(TEXT)['fields']
    fields['items'][0][key] = value
    with pytest.raises(ValidationError):
        normalize_review(fields)


def test_saved_unbalanced_review_remains_blocked():
    fields = parse_receipt(TEXT)['fields']
    fields['total'] = '726.00'
    _, checks = normalize_review(fields)
    assert checks['difference'] == '30.00'
    assert checks['calculated_total'] == '696.00'
    assert not checks['balanced']
    fields['discount'] = '1000.00'
    assert not normalize_review(fields)[1]['balanced']


def test_one_paise_tolerance_is_explicit():
    fields = parse_receipt(TEXT)['fields']
    fields['total'] = '696.01'
    assert normalize_review(fields)[1]['balanced']
    fields['total'] = '696.02'
    assert not normalize_review(fields)[1]['balanced']


def test_review_requires_an_object():
    with pytest.raises(ValidationError):
        normalize_review(None)


def test_phone_invoice_numbers_and_payment_labels_do_not_become_amounts():
    result = parse_receipt(TEXT + '\nPhone 9876543210\nInvoice 2026093012345\nTotal paid 0.00')
    assert result['fields']['total'] == '696.00'
    assert len(result['fields']['items']) == 2

from app.services.transaction_normalization.base import STATUS_NEEDS_REVIEW, STATUS_NORMALIZED
from app.services.transaction_normalization.engine import normalize_transaction_detail
from app.services.transaction_normalization.text import clean_description


def test_basic_cleaning_keeps_raw_value_separate() -> None:
    raw = "  CHEVRON   0094821   FREMONT   CA  "

    cleaned = clean_description(raw)
    result = normalize_transaction_detail(raw)

    assert raw == "  CHEVRON   0094821   FREMONT   CA  "
    assert cleaned == "CHEVRON 0094821 FREMONT CA"
    assert result.normalized_name == "Chevron"
    assert result.confidence > 0.95


def test_known_merchant_rules() -> None:
    examples = {
        "CHEVRON 0094821 FREMONT CA": "Chevron",
        "SHELL OIL 12345": "Shell",
        "AMZN MKTPL*123": "Amazon",
        "AMAZON.COM*ABCD1234": "Amazon",
        "AMAZON MKTPLACE PMTS": "Amazon",
        "COSTCO GAS #1234": "Costco Gas",
        "COSTCO WHSE #1234": "Costco",
        "STARBUCKS STORE 12345 FREMONT CA": "Starbucks",
        "TJX Rew Mstrcrd Syf Paymnt 524366304326066": "TJX Rewards Mastercard",
        "CAPITAL ONE MOBILE PMT": "Capital One",
        "AMERICAN EXPRESS ACH PMT": "American Express",
    }

    for raw_detail, expected_name in examples.items():
        result = normalize_transaction_detail(raw_detail)
        assert result.normalized_name == expected_name
        assert result.status == STATUS_NORMALIZED


def test_payment_processors_extract_actual_merchant_when_clear() -> None:
    examples = {
        "PAYPAL *ADOBE": "Adobe",
        "PAYPAL *OFFICEDEPOT": "Office Depot",
        "SQ *JOES COFFEE": "Joe's Coffee",
    }

    for raw_detail, expected_name in examples.items():
        result = normalize_transaction_detail(raw_detail)
        assert result.normalized_name == expected_name
        assert result.status == STATUS_NORMALIZED


def test_ambiguous_processor_and_generic_payments_need_review() -> None:
    for raw_detail in ["PAYPAL PAYMENT", "PAYPAL TRANSFER", "DBT CRD 481920", "PAYMENT 112233", "ACH 99883"]:
        result = normalize_transaction_detail(raw_detail)
        assert result.normalized_name is None
        assert result.status == STATUS_NEEDS_REVIEW
        assert result.confidence <= 0.25


def test_person_payments_checks_fees_and_atm_are_conservative_names() -> None:
    examples = {
        "ZELLE PAYMENT TO LAWRENCE VIZCONDE": "Lawrence Vizconde",
        "ZELLE PAYMENT FROM JANE DOE AB12CD34": "Jane Doe",
        "CHECK #1024": "Check #1024",
        "ATM WITHDRAWAL 123 MAIN ST OAKLAND CA": "ATM Withdrawal",
        "MONTHLY SERVICE FEE": "Monthly Service Fee",
    }

    for raw_detail, expected_name in examples.items():
        result = normalize_transaction_detail(raw_detail)
        assert result.normalized_name == expected_name
        assert result.status == STATUS_NORMALIZED

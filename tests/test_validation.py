import pytest

from src.ingest.models import SupplierRecord
from src.ingest.validation import (
    rejects_to_csv,
    validate_file,
    validate_record,
)

HEADER = (
    "supplier_number,supplier_name,source_system,country_code,"
    "currency_code,payment_terms_days,lead_time_days,status"
)


def make_record(**overrides) -> SupplierRecord:
    base = {
        "supplier_number": "SUP1001",
        "supplier_name": "Acme Components",
        "source_system": "SAP",
        "country_code": "US",
        "currency_code": "USD",
        "payment_terms_days": "30",
        "lead_time_days": "14",
        "status": "ACTIVE",
        "row_number": 2,
    }
    base.update(overrides)
    return SupplierRecord(**base)


class TestValidateRecord:
    def test_a_clean_record_passes(self):
        result = validate_record(make_record())
        assert result.is_valid
        assert result.errors == []

    @pytest.mark.parametrize(
        "field_name",
        ["supplier_number", "supplier_name", "payment_terms_days", "lead_time_days"],
    )
    def test_missing_required_fields_are_rejected(self, field_name):
        result = validate_record(make_record(**{field_name: ""}))
        assert not result.is_valid
        assert any(error.startswith("REQUIRED_FIELD") for error in result.errors)
        assert any(field_name in error for error in result.errors)

    def test_unknown_source_system_is_rejected(self):
        result = validate_record(make_record(source_system="TOTALLY_NEW"))
        assert any(error.startswith("REFERENCE_DATA") for error in result.errors)

    def test_unknown_status_is_rejected(self):
        result = validate_record(make_record(status="PENDING"))
        assert any("status" in error for error in result.errors)

    @pytest.mark.parametrize("country_code", ["USA", "U", "1S", ""])
    def test_country_code_must_be_two_letters(self, country_code):
        result = validate_record(make_record(country_code=country_code))
        assert any("country_code" in error for error in result.errors)

    @pytest.mark.parametrize("currency_code", ["US", "USDD", "12A", ""])
    def test_currency_code_must_be_three_letters(self, currency_code):
        result = validate_record(make_record(currency_code=currency_code))
        assert any("currency_code" in error for error in result.errors)

    def test_non_numeric_payment_terms_are_rejected(self):
        result = validate_record(make_record(payment_terms_days="net30"))
        assert any(error.startswith("FORMAT") for error in result.errors)

    def test_negative_lead_time_is_rejected(self):
        result = validate_record(make_record(lead_time_days="-5"))
        assert any(error.startswith("RANGE") for error in result.errors)

    def test_payment_terms_above_the_maximum_are_rejected(self):
        # A date accidentally loaded into a days field looks like this.
        result = validate_record(make_record(payment_terms_days="20260131"))
        assert any(error.startswith("RANGE") for error in result.errors)

    def test_supplier_number_with_punctuation_is_rejected(self):
        result = validate_record(make_record(supplier_number="SUP-1001"))
        assert any(error.startswith("FORMAT") for error in result.errors)

    def test_a_record_can_fail_several_rules_at_once(self):
        result = validate_record(
            make_record(supplier_name="", country_code="USA", status="PENDING")
        )
        assert len(result.errors) >= 3


class TestValidateFile:
    def test_all_valid_rows_are_accepted(self):
        content = "\n".join(
            [
                HEADER,
                "SUP1001,Acme Components,SAP,US,USD,30,14,ACTIVE",
                "SUP1002,Brightline Metals,EBS_R12,DE,EUR,45,21,ACTIVE",
            ]
        )
        accepted, rejected, summary = validate_file(content, "inbound/suppliers.csv")
        assert len(accepted) == 2
        assert rejected == []
        assert summary.total_rows == 2
        assert summary.reject_rate == 0.0

    def test_bad_rows_are_separated_from_good_ones(self):
        content = "\n".join(
            [
                HEADER,
                "SUP1001,Acme Components,SAP,US,USD,30,14,ACTIVE",
                ",Missing Number,SAP,US,USD,30,14,ACTIVE",
                "SUP1003,Ghost Supplier,UNKNOWN_SYS,US,USD,30,14,ACTIVE",
            ]
        )
        accepted, rejected, summary = validate_file(content, "inbound/suppliers.csv")
        assert len(accepted) == 1
        assert len(rejected) == 2
        assert summary.total_rows == 3
        assert summary.rejected_rows == 2
        assert summary.reject_rate == pytest.approx(2 / 3)

    def test_reject_rows_carry_their_row_number_and_reasons(self):
        content = "\n".join(
            [
                HEADER,
                "SUP1001,Acme Components,SAP,US,USD,30,14,ACTIVE",
                ",Missing Number,SAP,US,USD,30,14,ACTIVE",
            ]
        )
        _, rejected, _ = validate_file(content, "inbound/suppliers.csv")
        # Row 3 of the file, because row 1 is the header.
        assert rejected[0]["row_number"] == 3
        assert "supplier_number" in rejected[0]["reasons"]

    def test_errors_are_counted_by_rule(self):
        content = "\n".join(
            [
                HEADER,
                ",A,SAP,US,USD,30,14,ACTIVE",
                ",B,SAP,US,USD,30,14,ACTIVE",
                "SUP1003,C,NOPE,US,USD,30,14,ACTIVE",
            ]
        )
        _, _, summary = validate_file(content, "inbound/suppliers.csv")
        assert summary.errors_by_rule["REQUIRED_FIELD"] == 2
        assert summary.errors_by_rule["REFERENCE_DATA"] == 1

    def test_a_file_missing_columns_is_refused_outright(self):
        content = "supplier_number,supplier_name\nSUP1001,Acme"
        with pytest.raises(ValueError) as excinfo:
            validate_file(content, "inbound/suppliers.csv")
        assert "missing required columns" in str(excinfo.value)

    def test_an_empty_file_produces_an_empty_summary(self):
        accepted, rejected, summary = validate_file(HEADER, "inbound/suppliers.csv")
        assert accepted == []
        assert rejected == []
        assert summary.total_rows == 0
        assert summary.reject_rate == 0.0

    def test_surrounding_whitespace_is_trimmed(self):
        content = "\n".join(
            [HEADER, "  SUP1001 ,  Acme Components  , SAP , US , USD , 30 , 14 , ACTIVE "]
        )
        accepted, _, summary = validate_file(content, "inbound/suppliers.csv")
        assert summary.accepted_rows == 1
        assert accepted[0].supplier_number == "SUP1001"


class TestRejectsToCsv:
    def test_reject_report_has_a_header_and_one_row_each(self):
        rows = [
            {
                "row_number": 3,
                "supplier_number": "",
                "source_system": "SAP",
                "reasons": "REQUIRED_FIELD: supplier_number is missing",
            }
        ]
        output = rejects_to_csv(rows).splitlines()
        assert output[0] == "row_number,supplier_number,source_system,reasons"
        assert len(output) == 2


class TestToItem:
    def test_numbers_are_coerced_and_a_key_is_built(self):
        item = make_record().to_item()
        assert item["payment_terms_days"] == 30
        assert item["lead_time_days"] == 14
        assert item["supplier_key"] == "SAP#SUP1001"
        assert "row_number" not in item

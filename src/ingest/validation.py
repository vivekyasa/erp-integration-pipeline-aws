"""Validation rules applied to every inbound supplier record.

Each rule returns an error string prefixed with a stable rule code so that
rejects can be counted by rule and reported back to the source system owners.
"""

from __future__ import annotations

import csv
import io

from .models import (
    REQUIRED_COLUMNS,
    VALID_SOURCE_SYSTEMS,
    VALID_STATUSES,
    LoadSummary,
    SupplierRecord,
    ValidationResult,
)

# Payment terms longer than this are almost always a unit error in the
# source extract, for example a date loaded into a days field.
MAX_PAYMENT_TERMS_DAYS = 365
MAX_LEAD_TIME_DAYS = 365


def _is_blank(value: str) -> bool:
    return value is None or value.strip() == ""


def validate_record(record: SupplierRecord) -> ValidationResult:
    """Apply every rule to one record and collect the failures."""
    errors: list[str] = []

    if _is_blank(record.supplier_number):
        errors.append("REQUIRED_FIELD: supplier_number is missing")
    elif not record.supplier_number.isalnum():
        errors.append("FORMAT: supplier_number must contain only letters and numbers")

    if _is_blank(record.supplier_name):
        errors.append("REQUIRED_FIELD: supplier_name is missing")

    if record.source_system not in VALID_SOURCE_SYSTEMS:
        errors.append(
            f"REFERENCE_DATA: source_system '{record.source_system}' is not a known source system"
        )

    if len(record.country_code) != 2 or not record.country_code.isalpha():
        errors.append("FORMAT: country_code must be a two letter code")

    if len(record.currency_code) != 3 or not record.currency_code.isalpha():
        errors.append("FORMAT: currency_code must be a three letter code")

    if record.status not in VALID_STATUSES:
        errors.append(f"REFERENCE_DATA: status '{record.status}' is not a valid supplier status")

    errors.extend(
        _validate_whole_number(
            record.payment_terms_days, "payment_terms_days", MAX_PAYMENT_TERMS_DAYS
        )
    )
    errors.extend(
        _validate_whole_number(record.lead_time_days, "lead_time_days", MAX_LEAD_TIME_DAYS)
    )

    return ValidationResult(record=record, errors=errors)


def _validate_whole_number(raw: str, field_name: str, maximum: int) -> list[str]:
    if _is_blank(raw):
        return [f"REQUIRED_FIELD: {field_name} is missing"]
    try:
        value = int(raw)
    except ValueError:
        return [f"FORMAT: {field_name} must be a whole number"]
    if value < 0:
        return [f"RANGE: {field_name} cannot be negative"]
    if value > maximum:
        return [f"RANGE: {field_name} of {value} is above the allowed maximum of {maximum}"]
    return []


def validate_file(
    content: str, source_key: str
) -> tuple[list[SupplierRecord], list[dict], LoadSummary]:
    """Validate a whole CSV payload.

    Returns the accepted records, one reject row per failed record carrying its
    reasons, and a summary of the load.
    """
    summary = LoadSummary(source_key=source_key)
    accepted: list[SupplierRecord] = []
    rejected: list[dict] = []

    reader = csv.DictReader(io.StringIO(content))
    header = reader.fieldnames or []
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing_columns:
        raise ValueError("The file is missing required columns: " + ", ".join(missing_columns))

    # Rows are numbered from 2 so the number matches the line in the file,
    # with line 1 being the header. This is what the source system owner sees.
    for row_number, row in enumerate(reader, start=2):
        summary.total_rows += 1
        record = SupplierRecord.from_row(row, row_number)
        result = validate_record(record)
        if result.is_valid:
            accepted.append(record)
            summary.accepted_rows += 1
        else:
            summary.rejected_rows += 1
            summary.record_errors(result.errors)
            rejected.append(
                {
                    "row_number": row_number,
                    "supplier_number": record.supplier_number,
                    "source_system": record.source_system,
                    "reasons": "; ".join(result.errors),
                }
            )

    return accepted, rejected, summary


def rejects_to_csv(rejected: list[dict]) -> str:
    """Render reject rows as CSV for the rejects prefix in the bucket."""
    buffer = io.StringIO()
    columns = ["row_number", "supplier_number", "source_system", "reasons"]
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rejected:
        writer.writerow(row)
    return buffer.getvalue()

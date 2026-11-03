"""Record definitions for inbound supplier master data files.

The field set mirrors the supplier master attributes an ERP cloud migration
typically loads, so the validation rules below map to real business checks
rather than invented ones.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Columns every inbound supplier file must provide, in the order the
# source systems export them.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "supplier_number",
    "supplier_name",
    "source_system",
    "country_code",
    "currency_code",
    "payment_terms_days",
    "lead_time_days",
    "status",
)

# Source systems feeding the target cloud instance during migration.
VALID_SOURCE_SYSTEMS: frozenset[str] = frozenset({"SAP", "EBS_R12", "LEGACY_A", "LEGACY_B"})

VALID_STATUSES: frozenset[str] = frozenset({"ACTIVE", "INACTIVE", "ON_HOLD"})


@dataclass(frozen=True)
class SupplierRecord:
    """One inbound supplier row, already parsed but not yet validated."""

    supplier_number: str
    supplier_name: str
    source_system: str
    country_code: str
    currency_code: str
    payment_terms_days: str
    lead_time_days: str
    status: str
    row_number: int = 0

    @classmethod
    def from_row(cls, row: dict[str, Any], row_number: int) -> SupplierRecord:
        """Build a record from a CSV row, treating missing columns as empty."""
        values = {column: str(row.get(column, "") or "").strip() for column in REQUIRED_COLUMNS}
        return cls(row_number=row_number, **values)

    def to_item(self) -> dict[str, Any]:
        """Return the record shaped for persistence, with numbers coerced."""
        item = asdict(self)
        item.pop("row_number", None)
        item["payment_terms_days"] = int(self.payment_terms_days)
        item["lead_time_days"] = int(self.lead_time_days)
        item["supplier_key"] = f"{self.source_system}#{self.supplier_number}"
        return item


@dataclass
class ValidationResult:
    """Outcome of validating a single record."""

    record: SupplierRecord
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass
class LoadSummary:
    """Totals for one processed file, used for reporting and alerting."""

    source_key: str
    total_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    errors_by_rule: dict[str, int] = field(default_factory=dict)

    @property
    def reject_rate(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return self.rejected_rows / self.total_rows

    def record_errors(self, errors: list[str]) -> None:
        for error in errors:
            rule = error.split(":", 1)[0]
            self.errors_by_rule[rule] = self.errors_by_rule.get(rule, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "total_rows": self.total_rows,
            "accepted_rows": self.accepted_rows,
            "rejected_rows": self.rejected_rows,
            "reject_rate": round(self.reject_rate, 4),
            "errors_by_rule": dict(sorted(self.errors_by_rule.items())),
        }

import pytest

from src.ingest.notifications import (
    DEFAULT_REJECT_RATE_THRESHOLD,
    build_message,
    reject_rate_threshold,
    should_alert,
)


def summary(total=100, accepted=95, rejected=5, errors=None):
    rate = 0.0 if total == 0 else rejected / total
    return {
        "source_key": "inbound/suppliers.csv",
        "total_rows": total,
        "accepted_rows": accepted,
        "rejected_rows": rejected,
        "reject_rate": rate,
        "errors_by_rule": errors or {},
    }


class TestShouldAlert:
    def test_a_normal_load_does_not_alert(self):
        assert should_alert(summary(100, 95, 5), threshold=0.10) is False

    def test_crossing_the_threshold_alerts(self):
        assert should_alert(summary(100, 80, 20), threshold=0.10) is True

    def test_sitting_exactly_on_the_threshold_does_not_alert(self):
        assert should_alert(summary(100, 90, 10), threshold=0.10) is False

    def test_an_empty_file_always_alerts(self):
        # An empty file usually means the extract itself failed upstream.
        assert should_alert(summary(0, 0, 0), threshold=0.99) is True

    def test_a_fully_rejected_load_alerts(self):
        assert should_alert(summary(50, 0, 50), threshold=0.10) is True


class TestThresholdConfiguration:
    def test_the_default_is_used_when_unset(self, monkeypatch):
        monkeypatch.delenv("REJECT_RATE_THRESHOLD", raising=False)
        assert reject_rate_threshold() == DEFAULT_REJECT_RATE_THRESHOLD

    def test_the_environment_value_is_used_when_set(self, monkeypatch):
        monkeypatch.setenv("REJECT_RATE_THRESHOLD", "0.25")
        assert reject_rate_threshold() == pytest.approx(0.25)

    def test_a_nonsense_value_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("REJECT_RATE_THRESHOLD", "ten percent")
        assert reject_rate_threshold() == DEFAULT_REJECT_RATE_THRESHOLD


class TestMessage:
    def test_the_message_names_the_file_and_the_totals(self):
        text = build_message(summary(100, 80, 20, {"REQUIRED_FIELD": 20}))
        assert "inbound/suppliers.csv" in text
        assert "20" in text
        assert "REQUIRED_FIELD" in text

    def test_a_summary_without_errors_still_renders(self):
        text = build_message(summary(0, 0, 0))
        assert "Total rows:    0" in text

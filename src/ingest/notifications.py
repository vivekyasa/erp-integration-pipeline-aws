"""Raises an alert when a load fails badly enough to need a human."""

from __future__ import annotations

import logging
import os

import boto3

logger = logging.getLogger(__name__)

# A load is escalated when more than this share of rows is rejected. A small
# number of rejects is normal during a migration, a large share usually means
# the source extract itself is wrong.
DEFAULT_REJECT_RATE_THRESHOLD = 0.10


def reject_rate_threshold() -> float:
    raw = os.environ.get("REJECT_RATE_THRESHOLD")
    if not raw:
        return DEFAULT_REJECT_RATE_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        logger.warning("REJECT_RATE_THRESHOLD %r is not a number, using default", raw)
        return DEFAULT_REJECT_RATE_THRESHOLD


def should_alert(summary: dict, threshold: float | None = None) -> bool:
    """Alert when the file was empty or the reject rate crossed the threshold."""
    limit = reject_rate_threshold() if threshold is None else threshold
    if summary["total_rows"] == 0:
        return True
    return summary["reject_rate"] > limit


def build_message(summary: dict) -> str:
    lines = [
        f"Supplier load needs review: {summary['source_key']}",
        "",
        f"Total rows:    {summary['total_rows']}",
        f"Accepted rows: {summary['accepted_rows']}",
        f"Rejected rows: {summary['rejected_rows']}",
        f"Reject rate:   {summary['reject_rate'] * 100:.1f} percent",
    ]
    if summary["errors_by_rule"]:
        lines.extend(["", "Rejects by rule:"])
        for rule, count in summary["errors_by_rule"].items():
            lines.append(f"  {rule}: {count}")
    return "\n".join(lines)


def publish_alert(summary: dict) -> None:
    topic_arn = os.environ.get("ALERT_TOPIC_ARN")
    if not topic_arn:
        logger.warning("ALERT_TOPIC_ARN is not set, skipping the alert")
        return
    boto3.client("sns").publish(
        TopicArn=topic_arn,
        Subject=f"Supplier load review needed: {summary['rejected_rows']} rejects",
        Message=build_message(summary),
    )
    logger.info("Published alert for %s", summary["source_key"])

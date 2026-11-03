"""Lambda entry point.

Triggered when a supplier file lands under inbound/ in the landing bucket.
The function validates every row, writes the accepted records to DynamoDB,
writes a reject report and a load summary back to the bucket, and raises an
alert when the load needs a human to look at it.
"""

from __future__ import annotations

import json
import logging
import urllib.parse

from . import notifications, persistence
from .validation import rejects_to_csv, validate_file

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    """Process every S3 record in the triggering event."""
    results = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        try:
            results.append(process_object(bucket, key))
        except Exception:
            # Logged with the key so a failed file can be found and replayed.
            logger.exception("Failed to process s3://%s/%s", bucket, key)
            raise

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": results}),
    }


def process_object(bucket: str, key: str) -> dict:
    """Validate and load a single inbound file."""
    logger.info("Processing s3://%s/%s", bucket, key)
    content = persistence.read_object(bucket, key)

    accepted, rejected, summary = validate_file(content, source_key=key)
    summary_dict = summary.as_dict()

    if accepted:
        persistence.write_records(accepted)

    if rejected:
        persistence.write_rejects(bucket, key, rejects_to_csv(rejected))

    persistence.write_summary(bucket, key, summary_dict)

    if notifications.should_alert(summary_dict):
        notifications.publish_alert(summary_dict)

    logger.info("Load summary: %s", json.dumps(summary_dict))
    return summary_dict

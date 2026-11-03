"""Writes accepted records to DynamoDB and reject files back to S3."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from typing import Any

import boto3

logger = logging.getLogger(__name__)

# Batch size fixed by the DynamoDB BatchWriteItem API.
DYNAMO_BATCH_SIZE = 25


def _table():
    table_name = os.environ["SUPPLIER_TABLE_NAME"]
    return boto3.resource("dynamodb").Table(table_name)


def _s3():
    return boto3.client("s3")


def write_records(records: Iterable[Any]) -> int:
    """Write accepted records to DynamoDB, returning how many were written.

    The supplier key is the partition key, so re-processing the same file
    overwrites rather than duplicates. That makes a replay safe to run.
    """
    table = _table()
    written = 0
    with table.batch_writer(overwrite_by_pkeys=["supplier_key"]) as batch:
        for record in records:
            batch.put_item(Item=record.to_item())
            written += 1
    logger.info("Wrote %s supplier records to DynamoDB", written)
    return written


def write_rejects(bucket: str, source_key: str, body: str) -> str:
    """Store the reject report next to the inbound file, under rejects/."""
    reject_key = _reject_key(source_key)
    _s3().put_object(
        Bucket=bucket,
        Key=reject_key,
        Body=body.encode("utf-8"),
        ContentType="text/csv",
    )
    logger.info("Wrote reject report to s3://%s/%s", bucket, reject_key)
    return reject_key


def write_summary(bucket: str, source_key: str, summary: dict) -> str:
    """Store the load summary so each run leaves an auditable record."""
    summary_key = _summary_key(source_key)
    _s3().put_object(
        Bucket=bucket,
        Key=summary_key,
        Body=json.dumps(summary, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return summary_key


def read_object(bucket: str, key: str) -> str:
    response = _s3().get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def _strip_inbound_prefix(source_key: str) -> str:
    return source_key.split("/", 1)[1] if "/" in source_key else source_key


def _reject_key(source_key: str) -> str:
    return f"rejects/{_strip_inbound_prefix(source_key)}".replace(".csv", "_rejects.csv")


def _summary_key(source_key: str) -> str:
    return f"summaries/{_strip_inbound_prefix(source_key)}".replace(".csv", "_summary.json")

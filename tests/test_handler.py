"""End to end tests for the Lambda, running against mocked AWS services.

moto stands in for S3, DynamoDB and SNS, so these tests exercise the real
boto3 calls without an AWS account and without any cost.
"""

import json

import boto3
import pytest
from moto import mock_aws

BUCKET = "erp-landing-test"
TABLE = "suppliers-test"
HEADER = (
    "supplier_number,supplier_name,source_system,country_code,"
    "currency_code,payment_terms_days,lead_time_days,status"
)

GOOD_ROWS = [
    "SUP1001,Acme Components,SAP,US,USD,30,14,ACTIVE",
    "SUP1002,Brightline Metals,EBS_R12,DE,EUR,45,21,ACTIVE",
]
BAD_ROW = ",Missing Number,SAP,US,USD,30,14,ACTIVE"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("SUPPLIER_TABLE_NAME", TABLE)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        boto3.client("dynamodb").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "supplier_key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "supplier_key", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        topic = boto3.client("sns").create_topic(Name="erp-alerts-test")
        monkeypatch.setenv("ALERT_TOPIC_ARN", topic["TopicArn"])
        yield


def put_file(key: str, rows: list[str]) -> None:
    body = "\n".join([HEADER, *rows])
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=body.encode())


def s3_event(key: str) -> dict:
    return {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": key}}}]}


def read_key(key: str) -> str:
    return boto3.client("s3").get_object(Bucket=BUCKET, Key=key)["Body"].read().decode()


def list_keys(prefix: str) -> list[str]:
    response = boto3.client("s3").list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [item["Key"] for item in response.get("Contents", [])]


class TestCleanLoad:
    def test_accepted_records_land_in_dynamodb(self, aws_env):
        from src.ingest.handler import lambda_handler

        put_file("inbound/suppliers.csv", GOOD_ROWS)
        response = lambda_handler(s3_event("inbound/suppliers.csv"), None)

        assert response["statusCode"] == 200
        table = boto3.resource("dynamodb").Table(TABLE)
        assert table.scan()["Count"] == 2

    def test_no_reject_report_is_written_for_a_clean_file(self, aws_env):
        from src.ingest.handler import lambda_handler

        put_file("inbound/suppliers.csv", GOOD_ROWS)
        lambda_handler(s3_event("inbound/suppliers.csv"), None)

        assert list_keys("rejects/") == []

    def test_a_summary_is_always_written(self, aws_env):
        from src.ingest.handler import lambda_handler

        put_file("inbound/suppliers.csv", GOOD_ROWS)
        lambda_handler(s3_event("inbound/suppliers.csv"), None)

        summary = json.loads(read_key("summaries/suppliers_summary.json"))
        assert summary["total_rows"] == 2
        assert summary["accepted_rows"] == 2
        assert summary["rejected_rows"] == 0


class TestMixedLoad:
    def test_good_rows_load_even_when_others_fail(self, aws_env):
        from src.ingest.handler import lambda_handler

        put_file("inbound/suppliers.csv", [*GOOD_ROWS, BAD_ROW])
        lambda_handler(s3_event("inbound/suppliers.csv"), None)

        table = boto3.resource("dynamodb").Table(TABLE)
        assert table.scan()["Count"] == 2

    def test_a_reject_report_is_written_with_the_failed_row(self, aws_env):
        from src.ingest.handler import lambda_handler

        put_file("inbound/suppliers.csv", [*GOOD_ROWS, BAD_ROW])
        lambda_handler(s3_event("inbound/suppliers.csv"), None)

        report = read_key("rejects/suppliers_rejects.csv")
        assert "supplier_number is missing" in report
        assert len(report.strip().splitlines()) == 2


class TestReplaySafety:
    def test_reprocessing_the_same_file_does_not_duplicate_records(self, aws_env):
        from src.ingest.handler import lambda_handler

        put_file("inbound/suppliers.csv", GOOD_ROWS)
        lambda_handler(s3_event("inbound/suppliers.csv"), None)
        lambda_handler(s3_event("inbound/suppliers.csv"), None)

        table = boto3.resource("dynamodb").Table(TABLE)
        assert table.scan()["Count"] == 2


class TestFailureHandling:
    def test_a_file_missing_columns_raises_so_the_run_is_visible(self, aws_env):
        from src.ingest.handler import lambda_handler

        boto3.client("s3").put_object(
            Bucket=BUCKET,
            Key="inbound/broken.csv",
            Body=b"supplier_number,supplier_name\nSUP1001,Acme",
        )
        with pytest.raises(ValueError):
            lambda_handler(s3_event("inbound/broken.csv"), None)

    def test_a_key_with_spaces_is_decoded(self, aws_env):
        from src.ingest.handler import lambda_handler

        put_file("inbound/supplier master.csv", GOOD_ROWS)
        # S3 notifications encode spaces as plus signs.
        event = s3_event("inbound/supplier+master.csv")
        response = lambda_handler(event, None)
        assert response["statusCode"] == 200

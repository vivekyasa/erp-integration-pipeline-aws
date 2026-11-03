# ERP Integration Pipeline on AWS

A serverless inbound data pipeline for an ERP cloud migration, defined entirely
in Terraform. Supplier master files from four source systems land in S3, get
validated row by row, and load into DynamoDB. Rows that fail come back as a
reject report naming the row number and the reason, and a load that goes badly
wrong raises an alert instead of failing silently.

I built this because I spent a year and a half on the functional side of exactly
this problem, writing the data mappings, validation criteria and test scenarios
for integrations between four source systems and Oracle Fusion Cloud, and
tracing recurring File-Based Data Import failures back to duplicate source files
and missing master data. This is that same problem solved as cloud
infrastructure I own end to end.

## How it works

```
  Source extracts (SAP, EBS R12, two legacy systems)
                      |
                      v
          s3://<bucket>/inbound/*.csv
                      |
                      |  ObjectCreated, prefix inbound/, suffix .csv
                      v
             Lambda: validate and load
              |         |          |
              |         |          +--> SNS topic -> email alert
              |         |                (reject rate above threshold,
              |         |                 or an empty file)
              |         |
              |         +--> s3://<bucket>/rejects/*_rejects.csv
              |         +--> s3://<bucket>/summaries/*_summary.json
              v
      DynamoDB: supplier records
      partition key SAP#SUP1001
```

Everything in that diagram is created by `terraform apply`. Nothing is clicked
together in the console.

## The validation rules

Every row is checked against the rules in `src/ingest/validation.py`. Each
failure carries a stable rule code so rejects can be counted by cause and sent
back to whoever owns the source extract.

| Rule code | What it catches |
|---|---|
| `REQUIRED_FIELD` | A mandatory field arrived empty |
| `FORMAT` | Country or currency code the wrong length, a non numeric days field, punctuation in a supplier number |
| `REFERENCE_DATA` | A source system or status that is not on the known list |
| `RANGE` | A negative value, or a days field above 365 |

That last rule is the one that comes from experience rather than a
specification. A payment terms field holding `20260131` is a date that was
loaded into a days column upstream, and it will pass any check that only asks
whether the value is a number.

## Design decisions worth explaining

**The reject report is the product, not the error log.** A migration load is
never all or nothing. Good rows load, bad rows come back to the source system
owner with the row number and the reason, and they fix the extract. A pipeline
that rejects the whole file on the first bad row creates a week of back and
forth.

**Re-running a file is safe.** The supplier key is the DynamoDB partition key
and writes are upserts, so replaying the same file overwrites rather than
duplicates. During a migration you re-run files constantly.

**Only `inbound/` triggers the function.** The function writes its reports into
the same bucket. Without the prefix filter those writes would trigger it again,
which is an infinite loop that bills by the invocation.

**The function cannot delete anything.** Its IAM policy grants `GetObject` on
`inbound/` only, `PutObject` on the two report prefixes only, and write actions
on one table. There is no delete permission anywhere, and no bucket wide read.
A separate reader role can read everything and change nothing, mirroring the
owner and reader split used on the database side.

**Alerts fire on an empty file too.** Zero rows usually means the extract failed
upstream, and a pipeline that reports "0 rejects" on an empty file is reporting
success for a load that did not happen.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

47 tests, no AWS account needed. The handler tests run against mocked S3,
DynamoDB and SNS through `moto`, so they exercise the real boto3 calls and the
real control flow, including the replay case and the alert threshold.

## Deploying

Terraform needs AWS credentials with permission to create the resources above.

```bash
cd infra
cp example.tfvars terraform.tfvars   # then edit it
terraform init
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

Then trigger a load:

```bash
aws s3 cp ../sample_data/suppliers_with_errors.csv \
  "s3://$(terraform output -raw landing_bucket)/inbound/"

# the reject report appears within a few seconds
aws s3 ls "s3://$(terraform output -raw landing_bucket)/rejects/"
```

Tear it down with `terraform destroy -var-file=terraform.tfvars`.

### Cost

This is built to sit inside the AWS always free allowances rather than the
twelve month trial. DynamoDB runs on demand, Lambda and SNS usage at this volume
is negligible, and S3 lifecycle rules expire old versions and summaries after 30
days. Point in time recovery on the table does cost money and is off by default.

The usual way a project like this starts costing money is a NAT Gateway, at
roughly 32 dollars a month. The function here needs no VPC, so there is none.

## Layout

```
infra/           Terraform: S3, DynamoDB, Lambda, SNS, IAM, CloudWatch
src/ingest/      Lambda source
  models.py        Record shape and load summary
  validation.py    The rules, and whole file validation
  persistence.py   DynamoDB and S3 writes
  notifications.py Alert threshold and message
  handler.py       Lambda entry point
tests/           47 tests, AWS mocked with moto
sample_data/     One clean file, one with every error type in it
docs/            Architecture notes
```

## What I would add next

- A dead letter queue on the function, so a file that fails repeatedly lands
  somewhere visible instead of only in the logs.
- Cross field validation, for example checking lead time against the payment
  terms for the same supplier.
- A second record type (items) to prove the validation framework generalises
  beyond suppliers.

## License

MIT

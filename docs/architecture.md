# Architecture notes

Notes on why the pipeline is shaped the way it is. The README covers what it
does; this covers the alternatives that were considered and set aside.

## Why DynamoDB rather than RDS

The supplier record is a single flat item retrieved by one key, so there is no
join to justify a relational engine. The deciding factor was cost: DynamoDB on
demand sits in the AWS always free allowance indefinitely, while the RDS free
tier expires after twelve months and then bills whether or not the instance is
used. For a project that is meant to stay running and be shown to people, an
allowance that does not expire matters more than query flexibility it does not
need.

If item master or supplier site data were added, with a genuine parent and child
relationship, that balance would change.

## Why one bucket with prefixes rather than three buckets

Inbound files, reject reports and summaries are the same data at different
stages of one process, and lifecycle rules can already be scoped per prefix.
Three buckets would mean three sets of public access blocks, encryption settings
and policies to keep aligned, for no isolation benefit, since the same function
writes two of them.

The cost of this choice is the trigger loop risk: the function writes into the
bucket that triggers it. That is handled by filtering the notification to the
`inbound/` prefix and `.csv` suffix. It is the single most important line in the
Terraform, because without it every load triggers two more invocations.

## Why the function has no VPC

The function talks to S3, DynamoDB and SNS, all of which are reachable over the
AWS network without a VPC. Putting a Lambda in a private subnet and giving it
internet access requires a NAT Gateway at roughly 32 dollars a month, which is
the most common way a learning project starts generating a bill.

If this later needed to reach a database inside a VPC, the answer would be VPC
endpoints for the AWS services rather than a NAT Gateway.

## Why validation happens in code rather than in the database

Constraints in the data store can only reject a row, and the error they return
is written for a developer. The requirement here is a report that goes back to
the person who owns the source extract, naming the row number in their file and
the reason in language they recognise. That needs the rules to run before the
write, with the original row still in hand.

It also means the rules can be tested directly, without standing anything up.

## Why rejects are a file rather than a queue

The consumer is a person reviewing a load, not a system. They want one report
per file that they can open in Excel, matching the file they sent. A queue would
be the right answer if another service were consuming the rejects
programmatically.

## On the alert threshold

The threshold is a share of rows rather than a count, because the same number of
rejects means something different in a file of 50 rows and a file of 50,000. It
is configurable because the tolerable rate changes through a migration: high
early while the mappings are still being corrected, close to zero by cutover.

The empty file case is handled separately and always alerts, because a reject
rate of zero on zero rows is indistinguishable from a clean load if you only
look at the rate.

## Known gaps

- No dead letter queue. A file that fails repeatedly is visible in the logs and
  through the error alarm, but is not captured anywhere for replay.
- No schema versioning. A source system adding a column would pass, but a source
  system renaming one fails the whole file at the header check, which is loud
  but not graceful.
- Validation is per row. Rules that need to compare rows to each other, such as
  detecting a duplicate supplier number within one file, are not implemented.

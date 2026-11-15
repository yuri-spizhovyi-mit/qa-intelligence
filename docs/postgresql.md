# PostgreSQL storage increment

Status: the optional adapter passed the twelve reviewed integration checks against a disposable PostgreSQL fixture;32 existing SQLite/API scenarios also passed separately. SQLite remains the default backend. No existing records have been imported or switched to PostgreSQL.

The optional `PostgresAnalysisStore` implements the existing save/get/review contract. The API selects it only with `QA_STORAGE_BACKEND=postgres` and a nonempty `QA_DATABASE_URL`. An unsupported backend, missing driver/configuration or unavailable database fails closed with a storage error; `/health` remains process liveness only. Connection diagnostics are not returned to the client.

## Schema and transaction boundaries

The version1 SQL migration creates UUID analysis and review identifiers, JSONB snapshots, a unique review ID, a foreign key to the analysis, and an index for ordered history. The adapter exposes no update/delete operation for saved drafts or reviews. This is an application boundary, not a database role/trigger guarantee against privileged SQL changes.

Review writes lock their analysis row for the transaction, validate the draft digest and resolve global review-ID conflicts using a unique constraint and `INSERT ... ON CONFLICT DO NOTHING`. Identical retries return the original record without appending; conflicting content returns the existing409 contract. A later read after a concurrent insert resolves an ID owned by another analysis. Snapshot reads use repeatable-read transactions so the draft and history are read consistently. Connections, statements and lock waits have finite timeouts.

The digest uses the same canonical content as SQLite, independent of JSONB formatting. UUIDs, timestamps, digests and histories must remain unchanged during the later import increment. Import is not implemented here.

Relevant primary documentation: [PostgreSQL transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html), [row locks](https://www.postgresql.org/docs/16/explicit-locking.html), and [Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html).

## Explicit schema installation

Install the optional driver with `pip install '.[postgres]'`, or build the optional image using `docker build --target postgres -t qi-postgres-api .`. Normal Docker builds still end at the SQLite-only runtime target. The PostgreSQL image installs the binary driver from `requirements-postgres.txt` with hash verification; regenerate it with `infra/postgres/Dockerfile.lock`.

Provide the connection string privately as `QA_DATABASE_URL`. Do not put real credentials in source, command history, public issues or logs. Run `python -m qa_intelligence.migrate` inside the configured application container before starting the PostgreSQL-backed API. Migration is an explicit operator step, not DDL on each API request. It does not import SQLite or call a model.

The migration command serializes installation with a transaction-scoped advisory lock, stores version/checksum metadata, returns unchanged on a matching installed migration, and rejects a changed installed checksum. DDL and metadata commit together. An empty application database is required for the initial migration; existing unrelated tables are not overwritten. Separate operator and application database roles are an operations follow-up.

## Integration checks

`tests/test_postgres_storage.py` targets only a disposable database named `qi_test` at host alias `postgres`, configured through `QA_TEST_DATABASE_URL`. It truncates its own fixture tables between examples. Never aim it at a persistent application database. With no configured fixture it skips; a skip does not count as PostgreSQL verification.

The twelve reviewed tests cover migration repeatability/checksum rejection, snapshot/digest round-trip, ordered history/idempotent retry/conflict, concurrent identical and cross-analysis review IDs, unknown IDs, direct database uniqueness/foreign-key constraints, API status compatibility, sanitized outage handling and explicit backend selection. The provider is fake; no model request is needed.

Build the test image with `docker build --target postgres-tests -t qi-postgres-tests .`; building does not execute or collect tests. Execution requires exact-file human review and verified isolated non-root containers. Restrict the test container to a fresh PostgreSQL fixture on an internal network with an isolated gateway, no host ports/mounts/socket or external credentials, dropped capabilities, read-only roots with bounded temporary storage, resource limits and an outer deadline. A passwordless trust fixture is permitted only on that private disposable network; it is not the deployment configuration.

Remaining M4 work: verify this adapter, demonstrate durable PostgreSQL operation and controlled SQLite import, then add source-versioned document ingestion, embeddings and retrieval-grounded analysis. This increment makes no RAG or migration-completion claim.

## Recorded verification

The unchanged human-reviewed test file passed12/12 in7.31s against PostgreSQL16.10, using the local official-image digest `postgres@sha256:b477759d38be47671d54a054d832791f8ddb9f0eaf6faf51ed17516087793a66`. This is the tested fixture version, not a deployment-version recommendation.

Both fixture containers were inspected before test execution: non-root UIDs999/10001, read-only roots, only bounded temporary storage, no host bind mounts/volumes/ports/socket, no external credentials, dropped capabilities, no-new-privileges, seccomp filtering, bounded memory/CPU/PIDs, disabled IPv6 and a dedicated internal network with isolated gateway mode. Only those two containers shared the network; the test alias resolved statically to the fixture. Installed application/migration and exact reviewed test hashes matched the source. The test container had a60-second outer deadline. The fixture and network were removed afterward.

A separate verified network-disabled container ran the unchanged previously reviewed32 platform scenarios:32passed in3.54s. It exercised the default SQLite path with ephemeral storage. No model calls, existing SQLite volume access or record import occurred. These separate runs establish adapter/contract behavior, not PostgreSQL data survival across container replacement or completion of M4 retrieval work.

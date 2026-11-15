# Controlled SQLite import

Status: ten core import checks and both separately selected container-replacement phases passed against disposable synthetic fixtures. Existing application data and the default SQLite API backend remain unchanged.

This is an offline maintenance operation for a small platform database, not an online synchronization service. It reads a quiescent SQLite snapshot using a read-only URI and query-only transaction. It validates IDs, saved draft digests, review digests/references and supported payload fields before opening a PostgreSQL write transaction. It never updates the SQLite source.

The initial scope is bounded to a64MiB SQLite file,10,000 analyses and50,000 reviews. Freeze writes and use a consistent backup of the source, including proper SQLite backup handling if WAL is in use. A live file copied without its WAL is not a valid migration strategy. The API must remain stopped for the eventual maintenance cutover.

## Apply policy

Run the explicit PostgreSQL schema migration first. Import requires either an empty target or a complete exact match for an idempotent retry. A target with any differing record, missing/extra review or later review is rejected; it is never merged or overwritten.

The importer locks both target tables against writes, inserts saved IDs/content/timestamps/digests and ordered review history, verifies the target representation, and commits the transfer atomically. An insert or verification error rolls back inserted records. Database identity sequence gaps can remain after rollback; sequence numbers are internal and are not part of exported records or their digests. Imported reviews receive new internal sequence numbers in original order, so later appends remain ordered.

A content fingerprint covers canonical records and global review order. It excludes SQLite physical bytes and internal sequence numbers. It proves content equality for this representation, not independent authenticity or a digital signature. The tool does not grant new approval and does not recompute replacement draft digests.

Primary references: [Python SQLite read-only URI support](https://docs.python.org/3.12/library/sqlite3.html) and [PostgreSQL table locks](https://www.postgresql.org/docs/16/explicit-locking.html).

## Operator commands

Run within the configured PostgreSQL application container, using a controlled staged source copy. Do not mount host directories into test execution containers or publish source files/connection strings. The database URL belongs in private environment configuration.

```text
python -m qa_intelligence.import_sqlite --sqlite /staged/analyses.sqlite3
python -m qa_intelligence.import_sqlite --sqlite /staged/analyses.sqlite3 --apply
```

Without `--apply`, the tool only validates SQLite and prints counts/fingerprint; it does not connect to PostgreSQL. Apply requires `QA_DATABASE_URL`. Output contains summary metadata only. A rejected import exits nonzero with a sanitized message. Neither command switches the API backend, removes the source, or changes the schema.

## Verification

The exact-file review policy applies to `tests/test_sqlite_import.py`. Ten core tests cover complete record preservation and unchanged source bytes, identical import/review retries, differing target rejection, corrupt analysis/review digests, rollback after a failed review insert, concurrent identical imports, missing source, validation-only CLI behavior and target outage.

Two additional functions are selected separately for persistence proof. The prepare phase imports two synthetic analyses and three reviews and prints a content fingerprint. Trusted host orchestration then replaces the PostgreSQL container while retaining only a dedicated disposable Docker-managed database volume. The verify phase compares the full fingerprint and counts and verifies a new review appends after preserved history. The generated test container receives no volume, host directories, Docker socket or external credentials.

Both phases require an isolated internal network restricted to the disposable `postgres/qi_test` fixture, non-root read-only containers with bounded resources, and exact image/source checks before execution. An unselected/skipped phase is not persistence evidence. The dedicated fixture volume must be removed after verification, without touching any existing application volume.

## Recorded synthetic result

The unchanged human-reviewed file passed10 core checks in9.20s. Both durability functions were then explicitly selected: prepare passed in5.93s and verify passed in4.75s. These were three separate invocations, not one combined run, and no skipped/deselected phase is counted as a pass.

The prepare phase imported two analyses and three reviews and verified complete record equality and ordered history. A trusted host process stopped and removed the original PostgreSQL container, created a different container from the same pinned image against only the dedicated fixture volume, and reverified its isolation. The verify phase matched the complete pre-replacement content fingerprint/counts, then appended a fourth review after the preserved history.

Before every generated test phase, actual container/network settings and copied test/installed-source hashes were verified. Test containers were non-root, read-only, resource-limited and mount-free; they could reach only the disposable PostgreSQL fixture. PostgreSQL used a separate task-owned Docker volume rather than a host bind mount. Neither fixture had host ports, external credentials or a Docker socket. IPv6 was disabled and the network used internal isolated-gateway mode. The volume was retained solely for replacement verification, then removed with the fixture containers/network.

This establishes the synthetic import and container-replacement path. It does not claim an actual application-data cutover, independent authentication of approval records, or completion of M4 embeddings/retrieval. Keep the real SQLite database unchanged until a verified backup and explicit maintenance cutover are performed.

# Demo Energy Hub — synthetic system under test

Status: proposal. Nothing described here is implemented.

**Provenance:** general public engineering knowledge only. Every name, ID, number, rule, and data value is invented and does not describe any real product, company, or system.

**Role in QA Intelligence (suggested):** the "owned local demo application" for [M3](milestones.md), and a source of synthetic requirements for `evals/`. Keep it separate from the platform: the [architecture](architecture.md) excludes queues from QA Intelligence itself, so the worker below belongs only to the demo system.

## Part A — Generic concepts (industry-general)

| Area | Concepts worth practising |
|---|---|
| Device management | Registration, account ownership (tenancy), unique hardware serials, device-scoped credentials |
| Meter readings | Interval vs cumulative-register readings; energy (Wh) vs power (W); integer units; measured vs estimated quality; register resets |
| Energy usage | Hourly/daily aggregation; completeness; **"no data" ≠ "zero usage"**; half-open ranges `[start, end)` |
| Time | UTC storage; RFC 3339 offsets; device time vs received time; clock skew; local-day boundaries; DST 23/25-hour days |
| Events | At-least-once delivery; client-supplied event IDs; deduplication; late and out-of-order arrival; occurrence order vs arrival order |
| Async processing | `202 Accepted` + status resource; job states; retries; poison messages; testing eventual consistency by polling with a timeout, not sleeping |
| API hygiene | Schema validation; object-level authorization (BOLA); cursor pagination with a stable sort; idempotency keys; RFC 9457 errors; size limits |

## Part B — Invented design (all decisions arbitrary; change freely)

### 1. System and entities

**Demo Energy Hub:** households register virtual meters; meters upload "reports" containing 15-minute interval readings and device events; a background worker stores them; household members query usage and events.

- **Stack:** FastAPI `api` + Python `worker` + PostgreSQL, via Docker Compose. The queue is an `ingest_jobs` table claimed with `SELECT … FOR UPDATE SKIP LOCKED`; each job is processed in one transaction, so a worker crash returns it to `queued`.
- **Auth:** static synthetic bearer tokens seeded at startup; no sign-up or token issuance.
- **Out of scope for v1:** billing, tariffs, device commands, firmware, user management, materialized aggregates, rate limiting.

| Entity | Key fields | Rule |
|---|---|---|
| Account | `account_id` | Tenancy boundary |
| Principal (token) | `role`: `household_admin`, `household_viewer`, `device_client`; `account_id`; `device_id` (device clients only) | Stored hashed |
| Device | `device_id`, `account_id`, `serial`, `display_name`, `timezone` (IANA), `created_at` | `serial` globally unique |
| Reading | `device_id`, `interval_start` (UTC, 15-minute aligned), `energy_wh` (int), `quality`, `received_at` | PK (device_id, interval_start) |
| DeviceEvent | `device_id`, `event_id` (client UUID), `type`, `occurred_at`, `received_at` | PK (device_id, event_id) |
| IngestJob | `job_id`, `device_id`, `status` (`queued`, `completed`, `failed`), counts, `rejections[]`, `attempts` | — |
| IdempotencyRecord | `device_id`, `key`, `request_sha256`, `job_id`, `created_at` | Unique (device_id, key); retained 24 h |

Usage is computed from readings at query time, so late readings are reflected automatically.

### 2. Endpoints

JSON throughout; errors use `application/problem+json` with a machine-readable `code`. A non-business `GET /health` is also provided.

| # | Endpoint | Caller | Success |
|---|---|---|---|
| 1 | `POST /v1/devices` | household_admin | `201` + `Location` |
| 2 | `POST /v1/devices/{device_id}/reports` | device_client of that device | `202` + job `Location` |
| 3 | `GET /v1/ingest-jobs/{job_id}` | account household members; submitting device | `200` |
| 4 | `GET /v1/devices/{device_id}/usage` | household admin/viewer | `200` |
| 5 | `GET /v1/devices/{device_id}/events` | household admin/viewer | `200` |

**1. Register a device**

```http
POST /v1/devices
Authorization: Bearer tok_admin_acc1

{"serial": "SIM-7Q2K9X4M", "display_name": "Garage meter", "timezone": "Europe/Berlin"}
```

```http
201 Created
Location: /v1/devices/dev_a1b2c3

{"device_id": "dev_a1b2c3", "serial": "SIM-7Q2K9X4M", "display_name": "Garage meter",
 "timezone": "Europe/Berlin", "created_at": "2026-03-02T09:00:00Z"}
```

**2. Submit a report** (validated synchronously, processed asynchronously)

```http
POST /v1/devices/dev_a1b2c3/reports
Authorization: Bearer tok_device_a1b2c3
Idempotency-Key: 4f1c2d9e-0b7a-4c55-9e1f-2a3b4c5d6e7f

{"readings": [
   {"interval_start": "2026-03-02T10:00:00+01:00", "energy_wh": 212, "quality": "measured"},
   {"interval_start": "2026-03-02T10:15:00+01:00", "energy_wh": 198, "quality": "measured"}],
 "events": [
   {"event_id": "8d0e6a52-3c1f-4b8e-a7d2-91f0c4e5b6a3", "type": "link.lost",
    "occurred_at": "2026-03-02T09:12:41Z"}]}
```

```http
202 Accepted
Location: /v1/ingest-jobs/job_5f6g7h

{"job_id": "job_5f6g7h", "status": "queued"}
```

**3. Job status** (the second reading conflicted with a stored value)

```json
{"job_id": "job_5f6g7h", "device_id": "dev_a1b2c3", "status": "completed", "attempts": 1,
 "readings": {"stored": 1, "duplicate": 0, "rejected": 1},
 "events":   {"stored": 1, "duplicate": 0, "rejected": 0},
 "rejections": [{"pointer": "/readings/1", "code": "reading_conflict"}],
 "submitted_at": "2026-03-02T09:31:03Z", "finished_at": "2026-03-02T09:31:04Z"}
```

**4. Usage** (25 October 2026 in Berlin is a 25-hour DST day)

```http
GET /v1/devices/dev_a1b2c3/usage?start=2026-10-24T22:00:00Z&end=2026-10-25T23:00:00Z&granularity=day
```

```json
{"device_id": "dev_a1b2c3", "timezone": "Europe/Berlin", "granularity": "day",
 "buckets": [{"start": "2026-10-24T22:00:00Z", "end": "2026-10-25T23:00:00Z",
   "energy_wh": 18450, "intervals_expected": 100, "intervals_received": 97,
   "intervals_estimated": 2, "complete": false}]}
```

**5. Events** (newest occurrence first)

```http
GET /v1/devices/dev_a1b2c3/events?limit=2
```

```json
{"items": [
   {"event_id": "1b9f3c7a-5e2d-4f60-8a14-6c2b9d0e7f35", "type": "link.restored",
    "occurred_at": "2026-03-02T09:14:05Z", "received_at": "2026-03-02T09:31:04Z"},
   {"event_id": "8d0e6a52-3c1f-4b8e-a7d2-91f0c4e5b6a3", "type": "link.lost",
    "occurred_at": "2026-03-02T09:12:41Z", "received_at": "2026-03-02T09:31:04Z"}],
 "next_cursor": "c2FtcGxlLWN1cnNvcg"}
```

**Error shape**

```json
{"title": "Request validation failed", "status": 422, "code": "validation_failed",
 "errors": [{"pointer": "/readings/0/interval_start", "code": "timestamp_offset_required"}]}
```

### 3. Requirements and acceptance criteria

**R1 Device registration**

- AC1.1 A household_admin registers a device and receives `201`, a generated `device_id`, and a `Location` header.
- AC1.2 `serial` matches `^SIM-[A-Z0-9]{8}$`; `timezone` is a valid IANA name; `display_name` is optional, 1–60 characters after trimming. Violations return `422` listing every invalid field.
- AC1.3 An already-registered serial (any account) returns `409 serial_already_registered`, identical regardless of the owning account.

**R2 Report submission (synchronous checks)**

- AC2.1 A report holds 0–500 readings and 0–100 events, with at least one item in total; otherwise `422`. A body over 256 KiB returns `413`.
- AC2.2 Readings: `interval_start` has an explicit offset and falls on a 15-minute UTC boundary; `energy_wh` is an integer from 0 to 25,000; `quality` is `measured` or `estimated`.
- AC2.3 The interval end is no later than server receipt + 2 minutes, and the interval start is no earlier than receipt − 35 days. Event `occurred_at` uses the same window.
- AC2.4 A repeated `interval_start` or `event_id` within one report returns `422`.
- AC2.5 An `Idempotency-Key` UUID header is required; otherwise `400`. A valid report returns `202`; nothing is stored synchronously.

**R3 Idempotency**

- AC3.1 The same key with the same canonical body (SHA-256 of sorted-key JSON) within 24 h returns the original status and body plus `Idempotent-Replayed: true`. No new job is created.
- AC3.2 The same key with a different body returns `422 idempotency_key_reused`.
- AC3.3 Concurrent identical requests create exactly one job.

**R4 Async processing**

- AC4.1 Job status moves from `queued` to `completed` or `failed`. Each job is applied atomically.
- AC4.2 A reading with an existing (device, interval_start) and identical values counts as `duplicate`; different values are rejected as `reading_conflict`, and the first write wins.
- AC4.3 Events follow the same rule on (device, event_id), with conflicts rejected as `event_conflict`.
- AC4.4 Transient errors are retried up to 3 attempts with backoff, then the job becomes `failed` with `last_error_code`. Retries never create duplicate rows.

**R5 Usage**

- AC5.1 `start` and `end` are required RFC 3339 values with offsets, `end > start`, aligned to bucket boundaries in the device timezone. The maximum range is 31 days for `hour` and 366 days for `day`; otherwise `422`.
- AC5.2 `intervals_expected` reflects the actual local duration of the bucket (92, 96, or 100 intervals per day).
- AC5.3 A bucket with no readings has `energy_wh: null` and `complete: false`, never `0`. A partial bucket sums only the received readings. No interpolation.

**R6 Event listing**

- AC6.1 Events are sorted by `occurred_at` descending, then `event_id` ascending. Late arrivals appear at their occurrence position.
- AC6.2 `limit` is 1–100 (default 20); `next_cursor` is `null` on the last page.
- AC6.3 Paging never repeats an item and never skips an item that existed when paging began.
- AC6.4 A tampered cursor, or a cursor reused with a different device or filter, returns `400 invalid_cursor`.

**R7 Authorization**

- AC7.1 A missing or invalid token returns `401`.
- AC7.2 A device or job belonging to another account returns `404`, identical to a nonexistent ID.
- AC7.3 A visible resource accessed with the wrong role returns `403`. A device_client can reach only its own device.
- AC7.4 Checks run in order: authentication, resource visibility, role, validation.

**R8 Timestamps:** responses use UTC with `Z`; input without an offset is always rejected.

### 4. API test scenarios

| ID | Category | Scenario → expected | AC |
|---|---|---|---|
| T01 | Validation | Lowercase serial, `Mars/Olympus` timezone, 61-character or blank name → `422` with each pointer | 1.2 |
| T02 | Validation | `energy_wh` 0 and 25000 accepted; −1, 25001, `12.5`, `"212"` rejected (Pydantic lax mode would coerce `"212"`; use strict types) | 2.2 |
| T03 | Validation | 500 readings → `202`; 501 → `422`; empty report → `422`; body over 256 KiB → `413` | 2.1 |
| T04 | Authorization | No token, malformed token, unknown token → `401` | 7.1 |
| T05 | Authorization | Account B requests account A's device usage or job → `404`, byte-identical to a missing ID | 7.2 |
| T06 | Authorization | Viewer sends an *invalid* body to `POST /devices` → `403`, not `422` | 7.4 |
| T07 | Authorization | Device X's client posts to device Y in the same account → `404`; device client calls usage → `403` | 7.3 |
| T08 | Missing data | Day with no readings → `energy_wh: null`; day with 95 of 96 → partial sum, `complete: false` | 5.3 |
| T09 | Missing data | All readings 0 Wh → `energy_wh: 0`, `complete: true` (zero is not missing) | 5.3 |
| T10 | Missing data | Missing or non-UUID `Idempotency-Key` → `400` | 2.5 |
| T11 | Timestamps | No offset → `422`; 10:07 not aligned → `422`; `15:45+05:45` (= 10:00Z) accepted | 2.2, R8 |
| T12 | Timestamps | Same instant sent as `+01:00` and as `Z` in two reports → one interval (duplicate) | 4.2 |
| T13 | Timestamps | Window boundaries (+2 minutes, −35 days) tested with an injected fixed clock | 2.3 |
| T14 | Timestamps | Berlin 2026-03-29 → 92 expected intervals; 2026-10-25 → 100, with the repeated 02:00 hour as two hourly buckets | 5.2 |
| T15 | Timestamps | Day range not starting at local midnight → `422`; unencoded `+` in the query string arrives as a space → clear `422` | 5.1 |
| T16 | Pagination | 45 events, `limit=20` → pages of 20/20/5, final `next_cursor` `null`, 45 unique items | 6.2 |
| T17 | Pagination | Ties on `occurred_at` across a page boundary → no duplicates or gaps | 6.1, 6.3 |
| T18 | Pagination | Older event inserted mid-paging → appears exactly once on a later page | 6.3 |
| T19 | Pagination | `limit` 0, 101, `abc` → `422`; tampered or cross-filter cursor → `400` | 6.2, 6.4 |
| T20 | Duplicates | Same key and body → same `job_id`, replay header, job count unchanged | 3.1 |
| T21 | Duplicates | Same key, changed body → `422` | 3.2 |
| T22 | Duplicates | 10 concurrent identical requests → exactly one job | 3.3 |
| T23 | Duplicates | New key, identical readings → counted as duplicates; new key, different value → `reading_conflict`, original value kept | 4.2 |
| T24 | Async | Poll the job to a final state with a timeout and assert the counts; never use a fixed sleep | 4.1 |
| T25 | Async | Worker stopped → job stays `queued` and usage excludes the data; worker restart → job completes | 4.1 |
| T26 | Async | Kill the worker mid-job or inject one database fault → completes with `attempts` = 2 and no duplicate rows | 4.4 |

**Test hooks (invented):** an injectable clock and worker fault injection, available only when the app runs with a test profile and never enabled by default.

### 5. Later, optional: Kafka workflow

1. The API validates the report and writes the report row and an *outbox* row in one transaction. The `202` contract is unchanged.
2. A relay publishes outbox rows to `deh.device-reports.v1`, keyed by `device_id`. The relay may publish twice, by design.
3. Optionally, a device simulator publishes directly to the topic to create deliberate reordering and late data.
4. Consumer group `deh-ingest` processes each message in one transaction (items, a `processed_messages` row, and the job update), then commits the offset.
5. After 3 failed attempts, the message goes to `deh.device-reports.v1.dlt` with reason headers.

- **Duplicates** are handled at three levels: message ID (inbox table), (device, interval_start), and (device, event_id).
- **Out-of-order data** comes from offline device buffering, multiple producers, and dead-letter replays. Kafka orders messages only within a partition, and changing the partition count remaps keys.
  - Store data by occurrence time.
  - Derive state, such as a device `link_state`, from the greatest `occurred_at`, never from arrival order.
  - Compute usage on read; any later materialized aggregate must recompute the buckets that late readings fall into.
- **Kafka test scenarios:**
  - A message published twice is stored once.
  - Publishing the later event before the earlier one leaves `link_state` at the later event.
  - A crash after the database commit but before the offset commit causes no duplicates.
  - A malformed message or unknown `schema_version` goes to the dead-letter topic while the consumer continues.
  - After a rebalance, each message still takes effect exactly once.

**Learning value:**

- **Adds:** delivery semantics and offsets, the limits of ordering by partition key, redelivery after a crash, dead-letter handling, the outbox solution to the dual-write problem, and running a broker in CI.
- **Does not add:** idempotency, out-of-order rules, and async job status are already covered by the v1 PostgreSQL queue.
- **Costs:** broker memory and startup time in Docker and CI, timing-sensitive tests that can become flaky, and more moving parts.
- **Recommendation:** add Kafka in v2, after the v1 API tests are stable, as "swap the transport, keep the contract." Most v1 scenarios then run unchanged against both transports, which makes a strong portfolio demonstration. Skip it if time is short; deeper API testing and the QA Intelligence milestones come first.

## Open questions

- Should Demo Energy Hub be a separate repository or a folder in this one?
- M3 plans Playwright tests, but v1 is API-only. Is a minimal UI needed?
- Should the evaluation set include requirement variants with deliberately planted ambiguities, to check that the analyzer flags them?

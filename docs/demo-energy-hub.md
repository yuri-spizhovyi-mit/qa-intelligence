# Demo Energy Hub — synthetic test fixture

Status: specification only. Nothing described here is implemented.

**Provenance:** an invented fixture built from general engineering knowledge. All names, fields, limits, and data are fictional and do not represent any real product, company, or system.

**Purpose:** the small owned application under test for [M3](milestones.md), where QA Intelligence generates reviewed automation and runs it in isolation. The same energy-reading scenario supplies synthetic examples elsewhere in the project. It is a test target, not a second product; the QA Intelligence roadmap is unchanged.

**Placement and runtime:** `demo/energy-hub/` in this repository, as a separate runnable demo target. It processes requests synchronously, keeps events in memory, and loses all data on restart. A small browser page is added in M3, when browser automation needs it. It runs only as a controlled local test target; no public hosting or production-security claims are made.

## Event

| Field | Rule |
|---|---|
| `event_id` | Required UUID. Compared as a parsed UUID; responses use lowercase canonical form. |
| `device_id` | Required string. Surrounding whitespace is trimmed; empty or whitespace-only values are invalid. |
| `occurred_at` | Required RFC 3339 timestamp with an explicit offset. Normalized to UTC (`Z`) in responses. |
| `energy_wh` | Required strict integer from 0 to 25,000 inclusive. Strings, booleans, and decimals are invalid. |

## Endpoints

**`POST /v1/events`** accepts one event.

```http
POST /v1/events
Content-Type: application/json

{"event_id": "8d0e6a52-3c1f-4b8e-a7d2-91f0c4e5b6a3", "device_id": "  meter-garage-01 ",
 "occurred_at": "2026-03-02T10:15:00+01:00", "energy_wh": 212}
```

```http
201 Created
Location: /v1/events/8d0e6a52-3c1f-4b8e-a7d2-91f0c4e5b6a3

{"event_id": "8d0e6a52-3c1f-4b8e-a7d2-91f0c4e5b6a3", "device_id": "meter-garage-01",
 "occurred_at": "2026-03-02T09:15:00Z", "energy_wh": 212}
```

**`GET /v1/events/{event_id}`** returns a stored event with `200`, using the same body shape as above.

## Replay rule

A request is first validated and normalized: `device_id` is trimmed, `occurred_at` is converted to a UTC instant, and `event_id` is parsed as a UUID. Only a valid request is compared with a stored event that has the same `event_id`. The two are **equivalent** when `device_id`, the `occurred_at` instant, and `energy_wh` are all equal after normalization. For example, `10:15:00+01:00` and `09:15:00Z` are the same instant.

- Equivalent content returns `200` with the stored event, and no new record is created.
- Different content returns `409`, and the stored event is unchanged.
- An invalid request returns `422`, even if its `event_id` is already stored.

## Acceptance criteria

1. **AC1:** A valid new event returns `201`, a `Location` header for its GET URL, and the normalized event.
2. **AC2:** Each field rule in the table above is enforced; any violation returns `422` and stores nothing.
3. **AC3:** Responses show `device_id` trimmed and `occurred_at` in UTC with a `Z` suffix.
4. **AC4:** Replaying an equivalent event returns `200` with the stored event and creates no extra record.
5. **AC5:** Reusing an `event_id` with different normalized content returns `409` and leaves the stored event unchanged.
6. **AC6:** `GET` for a stored event returns `200` and the stored event; for an unknown ID it returns `404`; for a malformed ID it returns `422`.
7. **AC7:** All events are lost on restart, and this behavior is documented.

## Test scenarios

| ID | Scenario → expected result | AC |
|---|---|---|
| S1 | Post a valid event → `201`, `Location` header, normalized body; GET of that location → `200` with the same body | 1, 6 |
| S2 | Missing field, malformed UUID, or timestamp without an offset → `422`; a GET afterwards → `404` | 2 |
| S3 | `energy_wh` boundaries: 0 and 25000 accepted; −1, 25001, `12.5`, `"212"`, `true` → `422` | 2 |
| S4 | `device_id` of `"   "` → `422`; `"  meter-01 "` is stored as `"meter-01"` | 2, 3 |
| S5 | `occurred_at` sent as `+01:00` → returned as the matching UTC instant with `Z` | 3 |
| S6 | Same event posted twice → `201`, then `200` with an identical body; still one stored event | 4 |
| S7 | Replay using `Z` instead of the original offset and extra whitespace around `device_id` → `200` (equivalent) | 4 |
| S8 | Same `event_id` with a different `energy_wh` → `409`; GET still returns the original values | 5 |
| S9 | Invalid body reusing a stored `event_id` → `422`, not `409` or `200`; stored event unchanged | 2, 5 |
| S10 | Restart the demo, then GET a previously stored event → `404` | 7 |

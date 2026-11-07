# Analyses and review history

The M2 storage adapter uses SQLite from the Python standard library. The API stores immutable analysis snapshots and append-only review records. PostgreSQL replaces this adapter in M4.

## Create and retrieve an analysis

`POST /api/v1/analyses` keeps its HTTP 200 response and existing draft fields. It additionally returns `analysis_id`, `created_at` in UTC and `draft_sha256`. Saving happens after output structure and criterion-reference validation. A storage failure returns 503.

`GET /api/v1/analyses/{analysis_id}` returns the normalized original `request`, immutable `draft`, `reviews` in insertion order and a `review_status` derived from the latest review. Status begins as `pending`. An unknown UUID returns 404 and a malformed UUID returns 422.

Each analysis POST creates a new snapshot and may incur a new model call. Save its returned ID for subsequent retrieval and review. Failed provider responses are rejected before storage.

## Record a review

Copy the saved `analysis_id` into `POST /api/v1/analyses/{analysis_id}/reviews`. Use a newly generated review UUID and the exact `draft_sha256` returned with that draft.

```json
{
  "review_id": "a735bf05-39e3-4ede-b639-b915140ca871",
  "draft_sha256": "<copy the saved 64-character digest>",
  "decision": "changes_requested",
  "reviewer": "reviewer-1",
  "comment": "Clarify the expected HTTP status when an event is accepted."
}
```

The decision is either `approved` or `changes_requested`. Reviewer names are required, and change requests require a nonempty comment. Comments are limited to 2,000 characters. Review POST bodies share the analysis endpoint's 262,144-byte limit.

A new review returns 201. Retrying the same review ID with equivalent normalized content for the same analysis returns the existing record with 200. A conflicting review ID or a mismatched draft digest returns 409. Reviews are serialized transactionally, so concurrent identical submissions append one record. Replaying an older review preserves subsequent decisions.

The digest covers the analysis ID, timestamp, normalized input and draft, including provider metadata. A new analysis has its own digest and starts with a pending review. Review history preserves the original draft and earlier decisions.

This is a local single-user workflow. The reviewer field is self-reported. Approval applies to the saved prose draft. Executable artifacts have a separate review and isolation gate in M3.

## Storage lifetime

Docker Compose mounts the named `qa-data` volume at `/var/lib/qa-intelligence`. The image prepares this directory for UID/GID 10001. The remaining root filesystem stays read-only.

The SQLite file is `analyses.sqlite3` beneath `QA_DATA_DIR`. Compose stop/start, restart, and normal container replacement preserve the named volume. `docker compose down` also preserves it. Removing the volume, including through `docker compose down --volumes`, deletes the saved data.

Platform verification containers direct `QA_DATA_DIR` into their ephemeral tmpfs. They receive no persistent volume or credentials.

## Verified behavior

The 32 reviewed platform scenarios passed in verified network-disabled Docker, including 12 persistence scenarios. A separate fake-provider HTTP verification saved an analysis and synthetic change request, removed the API container, and successfully retrieved both after creating a replacement container with the same disposable named volume. Verification resources were removed afterward.

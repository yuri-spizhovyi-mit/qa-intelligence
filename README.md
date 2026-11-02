# QA Intelligence

AI-assisted requirements analysis and test design, with explicit human review before test execution.

**Status:** M1 is incomplete. Implemented endpoints: `GET /health` (liveness) and `POST /api/v1/analyses`, which is backed only by a deterministic **fake** provider. There is no live LLM integration and no runner yet. The updated container starts and exposes the analysis API documentation; analysis behavior verification is pending human review of the new tests.

## Current foundation (first slice of M1)

Implemented: an installable Python 3.12 `src` package, a FastAPI app (`qa_intelligence.main:app`) with `GET /health` (process liveness only; no provider, database, or credentials), a Dockerfile, a Compose file, and one contract test for `/health`.

Not implemented: the live LLM analysis endpoint and the synthetic demo. M1 is not complete until a real-provider demonstration succeeds. M2–M6 are unchanged (see the roadmap below).

### Analysis endpoint (fake mode)

`POST /api/v1/analyses` validates the request and returns a draft produced by a **deterministic fake provider** (`provider=fake`). It performs no AI or semantic analysis, makes no external calls, uses no secrets, persists nothing, and generates no test cases (`test_cases` is always empty; test-case generation is M2). Output must not be read as real analysis.

Request (synthetic example):

```json
{
  "requirement_id": "REQ-ENERGY-001",
  "text": "The system accepts energy-reading events with energy_wh between 0 and 25000 inclusive.",
  "acceptance_criteria": [
    {"id": "AC-1", "text": "An event with energy_wh below 0 or above 25000 is rejected."}
  ]
}
```

Response (HTTP 200):

```json
{
  "requirement_id": "REQ-ENERGY-001",
  "status": "draft",
  "questions": [],
  "risks": ["Deterministic fixture only; no semantic analysis was performed."],
  "test_cases": [],
  "metadata": {
    "provider": "fake",
    "model": "deterministic-v1",
    "prompt_version": "fake-v1",
    "token_usage": null
  }
}
```

Fake behavior: `questions` is empty when criteria are supplied; with an empty `acceptance_criteria` list (allowed) it is `["What acceptance criteria define success for this requirement?"]`. Missing criteria are clarified, not invented.

Limits (independent; both apply):

- Total request body: 262144 bytes, enforced on this POST route before JSON parsing, including chunked bodies without `Content-Length`. Overflow returns HTTP 413 and no provider call is made.
- Characters per field (after trimming): `requirement_id` 1–100, `text` 1–10000, criterion `id` 1–100, criterion `text` 1–2000; at most 20 criteria with unique ids. Extra fields are rejected. Violations return HTTP 422 and no provider call is made.

Status of this slice: source syntax and package metadata were checked, the Docker image built, and container startup, `/health`, and OpenAPI documentation were inspected on 2026-11-02. Analysis behavior has not yet been exercised. `tests/test_analysis.py` has not been run, imported, or collected; it awaits human review before isolated execution.

### Setup and start

The package targets Python 3.12 and its dependencies are declared in `pyproject.toml` (not locked yet). Docker is the supported execution path for this slice.

Docker Compose (binds to `127.0.0.1` only):

```text
docker compose up --build
```

Health URL: <http://127.0.0.1:8000/health> returns `{"status":"ok"}`. Interactive API docs are at <http://127.0.0.1:8000/docs>.

Shut down the container:

```text
docker compose down
```

### Verification status

- Verified on 2026-11-01: the image builds and starts; `/health` returns HTTP 200 with exactly `{"status":"ok"}`; `/docs` and `/openapi.json` return HTTP 200.
- Inspected container settings: UID/GID 10001, read-only root filesystem, dropped capabilities, no-new-privileges, no host bind mounts, and bounded CPU, memory, and process count. The API port is bound to localhost.
- The reviewed health contract test passed in a separate Docker container with networking disabled and no host mounts: **1 passed**. No tests were executed on the host. Modified or additional generated tests require renewed human review before isolated execution.
- The test run emitted an upstream Starlette/httpx deprecation warning. Dependency compatibility and locking remain follow-up work; there is no CI pipeline yet.
- Dependencies are not locked, so the image build is not claimed to be reproducible.

## MVP

Submit a requirement and its acceptance criteria to a FastAPI endpoint. Receive a structured draft containing ambiguities, risks, and test cases linked to the supplied criteria. Review the draft and store the decision through a persistence adapter. PostgreSQL becomes the durable platform store in the retrieval milestone.

The first release is a local, single-user application. It does not execute generated code. Model output is a proposal, not an authoritative interpretation of the requirements.

### Acceptance criteria

- Reject empty or oversized input before contacting the model.
- Validate the output schema and references to acceptance criteria.
- Preserve unanswered questions instead of inventing business rules.
- Record the provider, model, prompt version, and review status.
- Save and retrieve analyses and review decisions, with migration to PostgreSQL in M4.
- Report quality against a small, versioned evaluation dataset with human labels.

## Technology

Python, FastAPI, PostgreSQL, an LLM API, and Docker. Playwright follows after the review workflow. GitHub Actions and Kubernetes are later infrastructure stages.

## Planned layout

```text
src/qa_intelligence/    API, schemas, analysis service, provider and storage adapters
tests/                 Tests of the platform itself
evals/                 Synthetic requirements, rubrics, and AI quality evaluations
docs/                  Architecture and operational documentation
infra/                 Docker configuration; Kubernetes added later
AGENTS.md              Repository instructions for coding agents
```

Directories are introduced when their first implementation lands. Generated test artifacts will be kept outside normal test discovery and outside the tracked source tree.

## First milestone

**M1 — Backend, Docker, and live requirements analysis**

Deliver a documented API contract, a FastAPI service, a labeled fake provider for deterministic checks, a first live LLM requirements-analysis endpoint, and a Docker development environment. A successful real-provider demonstration is required to complete M1.

See [architecture](docs/architecture.md) and [milestones](docs/milestones.md).

## Full roadmap

| Milestone | Deliverable |
| --- | --- |
| M1 | Backend, Docker, and live requirements analysis |
| M2 | Structured test-case generation, traceability, and review |
| M3 | Playwright generation and an isolated runner |
| M4 | PostgreSQL, embeddings, and source-grounded RAG |
| M5 | AI evaluation, statistical evidence, and failure analysis |
| M6 | Kubernetes deployment, GitHub Actions, monitoring, and rollback |

The MVP is an intermediate release. The complete project includes every milestone above.

## Execution policy

Generated tests require human review of the exact artifact and an isolated execution environment. Review alone does not authorize execution on the host. Future runner isolation must be verified before any generated code is run. No runtime execution capability is included in the MVP.

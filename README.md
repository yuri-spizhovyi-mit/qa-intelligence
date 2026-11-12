# QA Intelligence

AI-assisted requirements analysis and test design, with explicit human review before test execution.

**Status:** M1/M2 provide live requirements analysis, traceable test-case drafts and durable review history. M3 now includes the runnable Demo Energy Hub API and browser page. All 32 reviewed platform scenarios and 31 separate demo scenarios passed in isolated Docker.

## Current capabilities

The FastAPI platform supports health, analysis, saved snapshot retrieval and digest-bound review decisions. It has deterministic fake mode and optional live providers, strict input/output validation, SQLite storage and a locked Docker build. The separate Demo Energy Hub supplies the owned target for the next automation increment.

A successful real-provider demonstration is part of M1. See verification status and the roadmap below for remaining work.

### Analysis endpoint (fake mode)

`POST /api/v1/analyses` validates the request and returns a draft. The default **deterministic fake provider** (`provider=fake`) returns a fixed fixture with an empty `test_cases` list. Live Claude and OpenAI adapters support optional test-case drafts described below.

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

The eight reviewed fake-provider contract tests passed in isolated Docker before the OpenAI adapter was added. The run emitted a Starlette test-client deprecation warning.

### Live analysis

For Claude, create an API key in the Claude Console. API access needs available credits. Enter the key at a masked prompt in PowerShell 7, then start the API from this directory.

```powershell
$env:ANTHROPIC_API_KEY = Read-Host "Claude API key" -MaskInput
$env:QA_CLAUDE_MODEL = "claude-sonnet-5-5"
docker compose -p qi-m1-foundation stop api
docker compose -p qi-m1-foundation run --build --rm --service-ports -e QA_ANALYSIS_PROVIDER=anthropic -e ANTHROPIC_API_KEY -e QA_CLAUDE_MODEL api
```

If another one-off API container occupies port 8000, stop that session with Ctrl+C first. Submit the synthetic request above in Swagger and check for HTTP 200 with `metadata.provider=anthropic`. Claude uses structured output, a 30-second SDK timeout and zero automatic retries. The output cap is 1,000 tokens for findings and 3,000 tokens when case generation is requested. Responses remain drafts for human review. Completion reasons are checked before JSON validation. Cutoffs and refusals are rejected with HTTP 502 and a sanitized diagnostic reason.

A live Claude request for a clarified synthetic energy requirement returned HTTP 200 with `provider=anthropic`, `model=claude-sonnet-5-5` and 1,742 total tokens. This verifies the live integration for one example. The draft still contained redundant and out-of-scope questions. An earlier request produced a validation error whose exact cause was not established. After exact-file human review, all four mocked completion/failure regression scenarios passed in a non-root, network-disabled, read-only Docker container with no host mounts or credentials and bounded resources. They cover token cutoff, refusal, malformed completed JSON and valid completed output.

Eligible Claude Max, Ultra, and Team plans can claim API credits through a linked Console organization. Check the Console credit balance before making a request. See [Anthropic API credits](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers).

#### OpenAI configuration

Build the image using Docker Compose. To try live analysis, supply `OPENAI_API_KEY` in your local shell and set `QA_OPENAI_MODEL` to a model your API project can access that supports Structured Outputs. Use synthetic requirements for the demonstration.

```text
docker compose run --rm --service-ports -e QA_ANALYSIS_PROVIDER=openai -e OPENAI_API_KEY -e QA_OPENAI_MODEL api
```

Stop the normal fake-mode container first if it is using port 8000. Submit the synthetic request above via the interactive API docs. Check that `metadata.provider` is `openai`. The adapter uses a 20-second SDK timeout, zero automatic retries, and response storage disabled via `store=false`. Its output cap is 1,000 tokens for findings or 3,000 for requested cases. Live OpenAI verification remains pending. Missing configuration returns 503, a provider timeout returns 504, and other provider failures or unusable output return 502.

### Draft test cases

Add `"generate_test_cases": true` to an analysis request to ask a live provider for up to 12 prose test cases. This strict boolean defaults to false, preserving findings-only requests.

Each case contains `id`, `title`, `category` (positive, negative or boundary), `preconditions`, `steps`, `expected_result`, and `source_criterion_ids`. Cases require nonempty steps and criterion references, unique case IDs and references to supplied criteria. Invalid structures or references return HTTP 502. Unrequested cases are also rejected.

A valid source ID establishes structural traceability. A reviewer must still decide whether the criterion supports the case's steps and expected result. Missing rules remain clarification questions.

A live Claude demonstration using four clarified synthetic energy criteria returned ten draft cases across all three categories with references to all four criteria. For example, the case submitting `energy_wh=-1` expects HTTP 422 and cites AC-2. This single result is demonstration evidence.

### Saved analyses and reviews

An analysis response includes `analysis_id`, `created_at` and `draft_sha256`. Retrieve its normalized input, immutable draft and review history with `GET /api/v1/analyses/{analysis_id}`.

Submit an `approved` or `changes_requested` decision through `POST /api/v1/analyses/{analysis_id}/reviews`, identifying the draft digest and a unique review ID. Identical retries return the existing decision. SQLite transactions preserve an ordered review history.

Docker Compose stores data in the named `qa-data` volume. See [persistence and reviews](docs/persistence.md) for request examples, status codes and data lifetime.

### Setup and start

The supported Docker target is Python 3.12 on Linux amd64. Dependencies are declared in `pyproject.toml` and pinned with hashes in the runtime, development and build lock files. The Dockerfile pins its Python base image by digest. See [locked builds](docs/builds.md) for the refresh workflow and verification scope.

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
- A clean Docker build installed the locked runtime and package-build dependencies with hash checking. The local package installation uses the locked build backend with network access and dependency resolution disabled.
- All 32 reviewed platform scenarios passed together against the locked environment in a verified network-disabled Docker container. This includes structural, traceability, storage, review-history, retry and concurrency scenarios. `pip check` previously reported no broken requirements for these locked dependencies.
- A separate fake-provider API verification saved an analysis and a synthetic review, removed the container, and retrieved the same snapshot and review from a new container using the same named volume.
- Lock verification covers Python 3.12 on Linux amd64. CI is planned in M6.

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

The synthetic [Demo Energy Hub](demo/energy-hub/README.md) is the M3 application under test, with a [two-endpoint specification](docs/demo-energy-hub.md) and browser page at port 8002. Start it with `docker compose -p qi-m1-foundation --profile demo up -d --build demo`.

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

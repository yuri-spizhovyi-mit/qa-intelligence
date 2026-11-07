# Architecture

Status: analysis and local review boundaries implemented; later milestone boundaries remain planned.

## Core flow

Requirement and acceptance criteria → request validation → analysis service → LLM provider → output and reference validation → draft analysis → human review → stored review decision.

Start with one FastAPI application. Keep HTTP handling, schema validation, provider calls, and persistence separate, without introducing microservices, queues, or an agent framework.

## Proposed API

| Endpoint | Purpose | Stage |
| --- | --- | --- |
| `GET /health` | Process liveness; no provider request | M1 |
| `POST /api/v1/analyses` | Analyze a requirement and return a draft | M1 fake and live; M2 richer test-case generation |
| `GET /api/v1/analyses/{id}` | Retrieve a persisted analysis | M2 |
| `POST /api/v1/analyses/{id}/reviews` | Record approval or requested changes | M2 |

Input contains a requirement identifier, its text, and acceptance criteria with stable identifiers. The initial proposed limit is 10,000 characters for requirement text and 20 criteria, each up to 2,000 characters. Enforce a separate total request-body limit at implementation time. Limits are application policy, not model limits.

Draft output contains `questions`, `risks`, and `test_cases`. Each test case has a title, preconditions, steps, an expected result, and `source_criterion_ids`. Case references must resolve to supplied criteria. Missing business rules become questions. A syntactically valid result can still be semantically wrong and requires review.

Provider metadata includes provider name, model identifier, prompt version, and token usage when available. Use `provider=fake` for deterministic fixtures. Do not present fixture behavior as AI capability.

Map invalid requests, provider timeout, provider refusal, and invalid model output to distinct documented outcomes. Do not persist an invalid response as a successful analysis. Live calls need explicit timeouts, bounded retries, and output limits.

## Persistence and deployment

A SQLite adapter stores immutable input/draft snapshots and append-only digest-bound review records in M2. Docker Compose persists its database in a named volume. Review IDs provide transactional idempotency and the latest appended review determines review status. See [persistence](persistence.md). PostgreSQL in M4 stores requirements, immutable analysis revisions, test-case drafts, review records, document chunks, and embedding metadata. The first deployment binds the API to localhost. Authentication, multi-tenancy, external websites, and public hosting are outside the MVP. Public source code does not imply a publicly accessible service.

## Evaluation

Maintain synthetic requirements and a human-authored rubric in `evals/`. Keep prompt-development examples separate from held-out examples. Measure schema validity, reference validity, coverage of labeled acceptance criteria, unsupported assumptions, and reviewer acceptance separately. Report sample counts and failures, not a single unsupported “AI accuracy” number.

## Later execution boundary

The generator can produce a narrow Playwright artifact for an owned local demo application. Every artifact starts as a draft. Approval must identify its exact digest; edits require renewed review. Test-case approval and approval of executable code are separate decisions.

A trusted launcher, outside the generated code, must enforce ephemeral non-root containers, no host filesystem mounts or Docker socket, no credentials, bounded CPU/memory/process count/runtime, and network access restricted to the demo application. Use a read-only root filesystem with explicit temporary storage. Keep the runner off the API/database network. Verify these properties before enabling execution.

Docker is one layer of isolation, not a guarantee that arbitrary code is safe. The Playwright image requires explicit security configuration; its documented default root user disables the Chromium sandbox. See [Playwright Docker guidance](https://playwright.dev/python/docs/docker).

## Retrieval and operations roadmap

M4 adds ingestion and retrieval over synthetic requirements and documentation. Chunks retain stable source identifiers and version metadata. Retrieved passages are treated as data; outputs cite their supporting sources and expose missing evidence. Evaluate retrieval separately from generated-answer quality.

M5 adds labeled development/held-out evaluation sets and evidence-based failure analysis. M6 adds GitHub Actions, a local Kubernetes deployment, health probes, configuration/secrets management, prompt/model/configuration versioning, operational monitoring, and rollback. Runner isolation must be verified again in the Kubernetes environment before generated-code execution there.

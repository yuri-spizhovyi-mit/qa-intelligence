# QA Intelligence

AI-assisted requirements analysis and test design, with explicit human review before test execution.

**Status:** initial design. The API and runner are not implemented yet.

## MVP

Submit a requirement and its acceptance criteria to a FastAPI endpoint. Receive a structured draft containing ambiguities, risks, and test cases linked to the supplied criteria. Review the draft and store the decision in PostgreSQL.

The first release is a local, single-user application. It does not execute generated code. Model output is a proposal, not an authoritative interpretation of the requirements.

### Acceptance criteria

- Reject empty or oversized input before contacting the model.
- Validate the output schema and references to acceptance criteria.
- Preserve unanswered questions instead of inventing business rules.
- Record the provider, model, prompt version, and review status.
- Save and retrieve analyses and review decisions in PostgreSQL.
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

**M1 — Requirements analysis API foundation**

Deliver a documented API contract, a FastAPI service with a deterministic fake provider, and a Docker development environment. The fake provider must be clearly identified; M1 does not claim live AI analysis. A real LLM provider and PostgreSQL persistence follow in M2.

See [architecture](docs/architecture.md) and [milestones](docs/milestones.md).

## Execution policy

Generated tests require human review of the exact artifact and an isolated execution environment. Review alone does not authorize execution on the host. Future runner isolation must be verified before any generated code is run. No runtime execution capability is included in the MVP.

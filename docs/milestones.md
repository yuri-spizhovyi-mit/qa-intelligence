# Delivery milestones

These are scope targets, not completion claims. The complete roadmap includes retrieval, controlled execution, quality evaluation, and Kubernetes operations. Milestones have no due dates yet.

## M1 — Backend, Docker, and live requirements analysis

Deliver a documented API contract, `/health`, and a first requirements-analysis endpoint. Use a labeled deterministic fake provider for repeatable service checks, and add one real LLM provider with timeouts, bounded retries, configuration, and usage limits. Provide a reproducible Docker development environment.

Definition of done:

- A valid synthetic request returns a validated draft analysis.
- Empty or oversized input and invalid criterion references are rejected.
- `/health` works without a model request or API key.
- A live-provider request is demonstrated; fake output alone does not complete M1.
- Refusals, timeouts, and invalid provider output have documented outcomes.
- Startup is verified with the API bound to localhost; credentials are excluded from source and logs.
- Generated platform tests are reviewed by the user and run only in verified isolation.

## M2 — Traceable test-case generation and review

Version prompts and structured output schemas. Generate positive, negative, and boundary cases linked to acceptance criteria. Preserve ambiguities as questions. Add retrieval of analyses and review decisions through a persistence adapter; a small file-backed store may precede the PostgreSQL migration in M4.

Definition of done: representative synthetic requirements yield reviewable cases; structural and reference checks pass; unsupported business rules can be identified and rejected; review decisions survive restart; prompt/model versions are recorded. Deliver the first requirements-analysis MVP here. Execution is introduced separately in M3.

## M3 — Playwright generation and isolated runner

Generate a constrained Playwright artifact for an owned local demo application. Require human review tied to the exact artifact digest. Verify an ephemeral non-root runner with bounded runtime/resources, no credentials or host mounts, and network access restricted to the demo target before any generated code is executed.

Definition of done: edits invalidate approval; unreviewed artifacts are blocked; isolation checks pass; reviewed scenarios produce reports and screenshots; product failures, test failures, and infrastructure errors are distinguished. Generated artifacts remain outside automatic platform test discovery.

## M4 — PostgreSQL, embeddings, and RAG

Introduce PostgreSQL migrations and migrate early persisted records. Ingest synthetic requirements and documentation with chunk/source identifiers and version metadata. Store embeddings and retrieve relevant passages. Ground analysis in retrieved sources and represent missing evidence explicitly.

Definition of done: persistence and migration are demonstrated; retrieval returns source-linked passages for labeled queries; generation identifies its supporting sources; retrieval quality and generation quality can be evaluated separately.

## M5 — AI evaluation and failure analysis

Build human-labeled development and held-out datasets. Evaluate validity, traceability, coverage, unsupported assumptions, reviewer acceptance, and retrieval quality. Analyze controlled failures using logs/screenshots and separate evidence from hypotheses.

Definition of done: compare a baseline with a changed prompt/model configuration; report sample counts, uncertainty, and dependent observations; reproduce the evaluation and failure reports without exposing private data.

## M6 — Kubernetes, CI/CD, and MLOps

Build GitHub Actions pipelines for reviewed platform checks and container images. Deploy the platform to a local Kubernetes lab with appropriate configuration, secrets, health probes, and the runner's isolation controls. Version prompts/models/configuration, monitor latency/errors/usage and quality signals, and document release and rollback procedures.

Definition of done: the deployment is reproducible, isolation is reverified in Kubernetes, CI results are inspectable, operational signals are visible, a rollback is demonstrated, and the runbook describes limitations. Paid cloud hosting is a separate deployment decision; a local cluster is sufficient for this milestone.

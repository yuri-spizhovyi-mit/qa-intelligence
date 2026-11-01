# Delivery milestones

These are scope targets, not completion claims. Dates remain unset until implementation starts.

## M1 — Requirements analysis API foundation

1. Define request/response models, stable acceptance-criterion references, and synthetic examples.
2. Implement `/health` and `/api/v1/analyses` with a deterministic fake provider.
3. Add Docker development configuration and reproducible startup instructions.
4. Review platform tests and run them only in a verified isolated environment.

Definition of done:

- A valid synthetic request yields a clearly labeled draft from the fake provider.
- Empty and oversized inputs are rejected; unknown criterion references are rejected.
- `/health` does not contact an LLM or require a key.
- API documentation describes success and error responses.
- Docker startup is verified; the API is bound to localhost.
- Reviewed checks pass in isolation, with results recorded.
- There is no generated-code execution endpoint.

## M2 — Reviewable AI analysis MVP

Introduce one real LLM provider, PostgreSQL migrations, analysis retrieval, and review decisions. Demonstrate a live request using synthetic data; fake-provider tests alone do not complete this milestone. Validate behavior for malformed output, refusal, and timeouts. Evaluate a small held-out set and publish the dataset limitations. Target the first usable release after the evaluation pass.

## M3 — Controlled Playwright demonstration

Generate a small test artifact for a local demo application. Add digest-bound human review and verify the runner's isolation before execution. Report passed, failed, and infrastructure-error outcomes with bounded artifacts.

## M4 — Delivery and evidence

Add GitHub Actions for reviewed platform checks, document evaluation results and limitations, and prepare a reproducible demonstration. Generated unreviewed test artifacts must never enter automatic CI discovery. Kubernetes is a follow-on deployment experiment once the Docker workflow is stable.

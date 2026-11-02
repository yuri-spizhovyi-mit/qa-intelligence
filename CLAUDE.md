# Claude Code project guidance

Read and follow the shared repository instructions:

@AGENTS.md

Read README.md and docs/architecture.md before proposing implementation changes. The project is currently at the design stage; do not claim planned features are implemented.

## Collaboration

- Codex leads architecture, scope, and integration. Claude executes assigned tasks, reports findings and risks, and does not independently expand scope or begin a new milestone. These instructions do not replace enforced execution controls.
- Coordinate work through explicit tasks and small diffs. Do not edit the same files concurrently with another coding assistant.
- Review the working tree before editing. Preserve other contributors' uncommitted changes.
- Separate observed behavior, documented requirements, and hypotheses. Database contents alone do not establish intended business rules.
- Company-specific API specifications, database information, credentials, and work-system findings must stay outside this public repository. Use synthetic examples in tracked files.
- Existing database access is not authorization to query a database for this project. Confirm the intended environment and scope with the user before accessing work systems. Prefer approved read-only inspection.
- Generated tests require human review of the exact artifact and verified isolation before execution. Do not trigger device commands or other state-changing operations without explicit authorization for that operation.
- Do not push changes unless the user has authorized publication of those changes. Keep personal learning materials outside the repository.

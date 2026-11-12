# Restricted runner preparation

Status: the local approval-and-hash launcher is implemented. The reviewed lower-boundary scenario passed inside restricted Docker after source, integrity and sandbox checks. This demonstrates one constrained scenario; general generation and post-Docker failure-path coverage remain pending.

The platform's prose approval and executable-code review are separate decisions. `qa_intelligence.artifacts` prepares one fixed template: submit an otherwise valid new event with `energy_wh=0` and expect HTTP 201 through the owned demo page. It requires an approved source snapshot and retains its analysis ID, digest, case and criterion references. Eligibility checks do not establish semantic equivalence; a person must review the exact code. This is a single constrained template, not general natural-language code generation.

The local review verifier checks explicit approval, a nonempty reviewer, the exact bundle bytes and executable SHA-256. The receipt is a local operator record, not authentication or a cryptographic signature. Neither a prose approval nor a matching digest alone authorizes execution. Generated bundles, receipts and reports belong outside version control and normal test discovery.

## Trusted preflight

Build from the repository root:

```powershell
docker build -f infra/runner/Dockerfile -t qi-playwright-runner .
& ./infra/runner/Test-RunnerPreflight.ps1 -OutputDirectory '<private-output-directory>'
```

The demo image `qi-m1-foundation-demo` must already exist. The preflight never receives or imports an artifact. It creates a fresh demo and runner, checks their actual Docker configuration, launches Chromium with its sandbox enabled, and removes temporary containers and network in a finally block. It writes `preflight.json` on browser completion; setup failures raise before that report is written. An old report is not evidence for a later attempt.

Controls include a non-root user, read-only root filesystem, bounded temporary storage, dropped capabilities, no-new-privileges, the pinned seccomp profile, private IPC, resource limits, no host mounts or published ports, and no credential environment variables. A dedicated internal network with isolated gateway mode contains only the disposable demo and runner. IPv6 is disabled in the runner; a static demo host entry and loopback DNS avoid upstream DNS resolution. The preflight rejects a default route and sandbox-disabling Chromium arguments. It also verifies an actual renderer has a deeper PID namespace hierarchy and more seccomp filters than the controller, zero effective capabilities, and no-new-privileges. A bounded readiness wait handles fresh demo startup. These checks are defense in depth, not a claim that Docker is a complete boundary against arbitrary hostile code.

Use the trusted host launcher below for generated artifacts. It verifies source approval, exact executable approval, isolation and runtime limits before the controller loads code. Reports emitted by generated code share its process and must be treated as untrusted observations, not independent attestation.

Do not add container capabilities, disable Chromium's sandbox, use host IPC, or disable seccomp. The explicit policy adjustment below enables a syscall needed to construct Chromium's namespace sandbox; it does not grant a container capability. Other policy changes require separate review and verification.

## Dependency provenance

The Dockerfile pins the official Playwright Python v1.64.1 Noble image by digest. Python dependencies are hash-locked separately. The vendored `seccomp_profile.json` comes from the Microsoft Playwright v1.64.1 `utils/docker/seccomp_profile.json`; SHA-256 is `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`. Its upstream Apache license is included as `LICENSE.playwright`.

## Chromium namespace compatibility adjustment

The untouched upstream profile permits `chroot` only when Docker grants `CAP_SYS_CHROOT`. With `cap-drop ALL`, Chromium failed its sandbox setup at `sys_chroot("/proc/self/fdinfo/")`. The derived `seccomp_chromium.json` removes that capability condition from the single existing chroot allow rule. All other syscall rules retain their upstream behavior. This widens the syscall allowlist; it is an explicit compatibility tradeoff, not an unchanged security policy. Kernel namespace/capability checks still apply to the call.

The derived profile SHA-256 is `0cd2663c21e39bf5c4861f26266b49a2b5b6faa0adff4a645068a5e394426a49`. The trusted launcher checks this hash before creating resources. The original profile and license remain unchanged for provenance.

Verification: the trusted preflight returned `outcome=ready`, `code_executed=false`, `isolated_renderers=1` and `sandbox_verified=true`. Docker configuration checks passed for both disposable containers and their isolated network. No generated code was copied into the preflight. Temporary resources were removed afterward. This is environment/preflight evidence; it is not a test result for an energy event.

## Execute an approved artifact (PowerShell 7)

Keep the artifact directory outside this repository. It contains `bundle.json`, the exact `scenario.py` reviewed by the operator, and `review.json`. The receipt must contain `decision: approved`, a nonempty reviewer, and SHA-256 values in `bundle_sha256` and `artifact_sha256`. A receipt is a local record of a real review; creating one does not substitute for reviewing the code.

```powershell
& ./infra/runner/Invoke-ReviewedScenario.ps1 `
  -BundlePath '<private-artifact-directory>/bundle.json' `
  -ReviewPath '<private-artifact-directory>/review.json' `
  -OutputDirectory '<private-results-directory>'
```

The API must be running at `http://localhost:8000`. Only GET requests retrieve the source analysis; no model calls are made. The launcher compares the exact source case, current approval and draft digest, then checks again immediately before starting the runner. This is a local single-user gate, not an atomic authorization lock against concurrent review changes.

The gate hashes the original bundle bytes and the UTF-8 executable text, verifies the separate reviewed file matches, and copies only those verified in-memory bytes into a temporary image. A COPY-only Docker build runs no generated code. The trusted base image and demo image are captured by image ID; the artifact image must extend the captured base layers. No artifact directory is mounted into a container. The runner image runs its own browser/process checks and checks the artifact hash before importing it.

Every invocation creates a fresh demo, isolated network and runner. The host imposes a 60-second runtime ceiling. Logs, resources and screenshot sizes are bounded. A unique local run directory receives `result.json` and, when available, `screenshot.png`. The report binds analysis, case, reviewer, bundle/artifact/policy hashes and image IDs to the container exit code and observed outcome. Full-page PNG evidence is limited to width1280, height8192 and one million bytes. Reports and screenshots remain private local artifacts.

Temporary containers, network, image tags and build-context files are removed in a finally block. Docker's build cache can retain image layers containing the synthetic artifact; cleanup does not imply secure erasure from Docker storage. Setup and orchestration failures stop execution or produce a launcher-error report; a missing/failed report is never a passing scenario. Unexpected termination of the host process can interrupt cleanup, so inspect Docker resources before retrying after a crash.

Validation performed: PowerShell syntax parsing, browser-only preflight through the shared launcher, and the exact human-reviewed Playwright scenario in restricted Docker. Twenty approval/integrity/source gate regression scenarios passed in a separate, verified non-root, network-disabled, read-only Docker container without host mounts or credentials. HTTP and Docker calls were replaced with sentinels; no fixture Python code ran. Post-Docker resource rejection, timeout and cleanup failure-path regressions remain pending. Existing platform/demo tests were not rerun because their application code was unchanged.

## Approval gate regressions

`tests/Test-ApprovalGate.ps1` exercises the actual `Invoke-ReviewedScenario.ps1` / `Invoke-Runner.ps1` entry points. It uses synthetic records and exact file hashes. Nineteen invalid-input paths must reject before any Docker call; the valid control must reach the mocked Docker boundary. The suite verifies the expected error, HTTP/Docker invocation counts and absence of an output directory for every case. It does not start nested containers or execute the fixture Python string.

Coverage includes pending/missing approval, blank reviewer, changed bundle bytes/code/receipt digest/reviewed file, absent reviewed file, unsupported scenario, revoked source approval, empty or changed review history, mismatched draft/review digests, missing/duplicated/changed source case, unavailable API and oversized receipt.

The COPY-only `tests/Dockerfile` pins Microsoft PowerShell 7.5 on Ubuntu24.04 by digest. Build from the repository root using `docker build --network none -f infra/runner/tests/Dockerfile -t qi-gate-reviewed .`. Building does not run the suite. Before execution, obtain exact-file human review, compare the copied image test file with its approved SHA-256, and verify actual container configuration: user10001, networknone, read-only root, temporary storage only, no mounts/credentials/added capabilities, no-new-privileges, seccomp filtering, memory512MiB, CPU1, PIDs100 and a 60-second outer timeout. This suite needs no Docker socket, running API, browser or model key.

Verification result:20/20 passed, exit0. This establishes pre-Docker approval/source/integrity rejection behavior. It does not establish post-start resource-control rejection, timeout cleanup or independent authenticity of generated-code observations.

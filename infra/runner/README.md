# Restricted runner preparation

Status: the local approval-and-hash launcher is implemented. The reviewed lower-boundary scenario passed inside restricted Docker after source, integrity and sandbox checks. This demonstrates one constrained scenario; general generation and broader real-runtime failure injection remain pending.

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

Cleanup attempts every temporary container, network, image tag and build-context removal even when an earlier removal fails. It checks Docker exit codes, writes a separate `cleanup.json`, and throws `Cleanup failed` if any removal or cleanup-report write fails. A passed scenario observation does not override a cleanup failure; require a successful launcher exit and cleanup report. Docker's build cache can retain image layers containing the synthetic artifact; cleanup does not imply secure erasure from Docker storage. Setup and orchestration failures stop execution or produce a launcher-error report; a missing/failed report is never a passing scenario. Unexpected termination of the host process can interrupt cleanup, so inspect Docker resources before retrying after a crash.

Validation performed: PowerShell syntax parsing, browser-only preflight through the shared launcher, and the exact human-reviewed Playwright scenario in restricted Docker. Twenty approval/integrity/source gate regression scenarios passed in a separate, verified non-root, network-disabled, read-only Docker container without host mounts or credentials. HTTP and Docker calls were replaced with sentinels; no fixture Python code ran. Twenty-one additional lifecycle scenarios passed against simulated Docker/job boundaries, covering container/network rejection, timeout kill and cleanup, startup/report failures, and failed cleanup. This confirms launcher decisions; it is not real-runtime failure injection. Existing platform/demo tests were not rerun because their application code was unchanged.

## Approval gate regressions

`tests/Test-ApprovalGate.ps1` exercises the actual `Invoke-ReviewedScenario.ps1` / `Invoke-Runner.ps1` entry points. It uses synthetic records and exact file hashes. Nineteen invalid-input paths must reject before any Docker call; the valid control must reach the mocked Docker boundary. The suite verifies the expected error, HTTP/Docker invocation counts and absence of an output directory for every case. It does not start nested containers or execute the fixture Python string.

Coverage includes pending/missing approval, blank reviewer, changed bundle bytes/code/receipt digest/reviewed file, absent reviewed file, unsupported scenario, revoked source approval, empty or changed review history, mismatched draft/review digests, missing/duplicated/changed source case, unavailable API and oversized receipt.

The COPY-only `tests/Dockerfile` pins Microsoft PowerShell 7.5 on Ubuntu24.04 by digest. Build from the repository root using `docker build --network none -f infra/runner/tests/Dockerfile -t qi-gate-reviewed .`. Building does not run the suite. Before execution, obtain exact-file human review, compare the copied image test file with its approved SHA-256, and verify actual container configuration: user10001, networknone, read-only root, temporary storage only, no mounts/credentials/added capabilities, no-new-privileges, seccomp filtering, memory512MiB, CPU1, PIDs100 and a 60-second outer timeout. This suite needs no Docker socket, running API, browser or model key.

Verification result:20/20 passed, exit0. This establishes pre-Docker approval/source/integrity rejection behavior. It does not establish post-start resource-control rejection, timeout cleanup or independent authenticity of generated-code observations.

## Lifecycle regressions and cleanup failures

`tests/Test-RunnerLifecycle.ps1` invokes the actual preflight/shared launcher while substituting Docker and job boundaries. It covers unsafe user/rootfs/mount/capability/credential/port/resource/seccomp/IPC/network settings, a timed-out runner, failed startup, nonzero exit, unexpected execution, malformed/oversized output, successful cleanup and failed container removal. It checks that rejected configurations never start the runner, timeout triggers kill, jobs are removed, and remaining resource cleanup is attempted after an error.

The first reviewed run passed20 scenarios and failed the cleanup-error case: Docker returned a failed removal status but the launcher returned success. The fix checks every cleanup result and surfaces failures while continuing other cleanup attempts. Both unchanged reviewed suites then passed:21 lifecycle scenarios and20 approval scenarios. No fixture artifact, real Docker call or real job was invoked inside those tests.

The same pinned test image includes both suites. Its default entry point remains the approval suite. To select the lifecycle suite in an otherwise verified isolated container, override the entry point to `pwsh` and pass `-NoLogo -NoProfile -NonInteractive -File /work/infra/runner/tests/Test-RunnerLifecycle.ps1`. The same exact-file review, source/image hash checks, no-network/no-mount/no-credential restrictions and resource limits apply.

The separate cleanup report records whether all cleanup commands succeeded, their errors and any earlier operation error. Pre-Docker gate rejections still occur before runtime directories or cleanup reports are created. Host crashes or a broken Docker daemon can leave resources behind; the launcher reports failure rather than claiming successful cleanup. Broader real-runtime fault injection and artifact-mode image-removal failures are not covered by this simulated preflight suite.

A real browser-only preflight after the cleanup fix also returned ready with one verified isolated renderer and code_executed=false. Its cleanup report recorded succeeded=true, and no temporary preflight network remained. No generated artifact was rerun for this cleanup-only change.

## Outcome classification regressions

Nine exact-file-reviewed tests in `tests/test_runner_outcomes.py` passed in verified non-root, network-disabled, read-only Docker, with no host mounts or credentials and bounded resources. They call the trusted controller's main function while replacing browser/readiness/isolation checks and artifact loading. No real browser or generated artifact runs in this suite.

The controller reports an explicit `ProductFailure` as `product_failure`, other artifact/locator exceptions as `test_failure`, and startup, environment, digest or screenshot failures as `infrastructure_error`. Failure paths return a nonzero exit code; pre-execution failures must not load the artifact. A screenshot failure overrides a prior passing observation. Preflight returns ready without reading artifact code.

These categories describe where an observed failure occurred; they are not independent proof of a product defect. For example, a wrong expected HTTP status in a reviewed scenario can still produce a product-failure report. Human investigation and supporting evidence remain required.

`infra/runner/tests/Dockerfile.outcomes` supplies a pinned Python base and hash-locked dependencies. Its build allowlist includes only the required locks, trusted controller/contract and reviewed test file; builds do not run tests. It runs one explicit pytest file, not automatic discovery of generated artifacts. Apply the same exact-file approval and verified isolation policy as the other suites. This classification suite does not independently verify browser isolation; that evidence comes from the separate real restricted preflight and reviewed scenario run.

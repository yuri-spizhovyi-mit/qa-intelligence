FROM mcr.microsoft.com/powershell:7.5-ubuntu-24.04@sha256:042240d57ec9e47e511033b92625a8d95875ee5860af3015992c248b58a8be81

ENV HOME=/tmp \
    TMPDIR=/tmp \
    DOTNET_CLI_HOME=/tmp \
    DOTNET_EnableDiagnostics=0 \
    POWERSHELL_TELEMETRY_OPTOUT=1 \
    POWERSHELL_UPDATECHECK=Off
WORKDIR /work
COPY infra/runner/Invoke-Runner.ps1 infra/runner/Invoke-ReviewedScenario.ps1 infra/runner/seccomp_chromium.json ./infra/runner/
COPY infra/runner/tests/Test-ApprovalGate.ps1 ./infra/runner/tests/
USER 10001:10001
ENTRYPOINT ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", "/work/infra/runner/tests/Test-ApprovalGate.ps1"]

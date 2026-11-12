[CmdletBinding(DefaultParameterSetName = 'Preflight')]
param(
    [Parameter(Mandatory)]
    [string] $OutputDirectory,
    [Parameter(Mandatory, ParameterSetName = 'Preflight')]
    [switch] $Preflight,
    [Parameter(Mandatory, ParameterSetName = 'ReviewedRun')]
    [string] $BundlePath,
    [Parameter(Mandatory, ParameterSetName = 'ReviewedRun')]
    [string] $ReviewPath
)

$ErrorActionPreference = 'Stop'
$profile = Join-Path $PSScriptRoot 'seccomp_chromium.json'
$expectedProfile = '0cd2663c21e39bf5c4861f26266b49a2b5b6faa0adff4a645068a5e394426a49'
if ((Get-FileHash -LiteralPath $profile).Hash -ne $expectedProfile) {
    throw 'Seccomp policy changed'
}

function Invoke-Docker {
    $result = & docker.exe @args
    if ($LASTEXITCODE) {
        throw "Docker operation failed: $($args[0])"
    }
    return $result
}

function Assert-Container($Container, $User, $Memory, $Cpu, $Pids, $Network) {
    $hostConfig = $Container.HostConfig
    $networks = @($Container.NetworkSettings.Networks.PSObject.Properties.Name)
    $credentialVariables = @($Container.Config.Env | Where-Object {
        $_ -match '(?i)(token|secret|api_key|password|credential)='
    })
    if (
        $Container.Config.User -ne $User -or
        -not $hostConfig.ReadonlyRootfs -or $hostConfig.Privileged -or
        $Container.Mounts.Count -ne 0 -or $hostConfig.CapDrop -notcontains 'ALL' -or
        @($hostConfig.CapAdd | Where-Object { $null -ne $_ }).Count -ne 0 -or
        $hostConfig.SecurityOpt -notcontains 'no-new-privileges:true' -or
        $hostConfig.Memory -ne $Memory -or $hostConfig.NanoCpus -ne $Cpu -or
        $hostConfig.PidsLimit -ne $Pids -or
        @($hostConfig.PortBindings.PSObject.Properties).Count -ne 0 -or
        $credentialVariables.Count -ne 0 -or
        $networks.Count -ne 1 -or $networks[0] -ne $Network
    ) {
        throw 'Container controls could not be verified'
    }
}

function Get-BytesHash([byte[]] $Bytes) {
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

function Assert-SourceApproval($Bundle) {
    # Fixed loopback endpoint. No credentials, redirects or model requests.
    $id = [guid]::Parse($Bundle.analysis_id).ToString()
    $source = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/analyses/$id" -MaximumRedirection 0 -TimeoutSec 10
    $reviews = @($source.reviews)
    if (
        $source.review_status -cne 'approved' -or $reviews.Count -eq 0 -or
        $reviews[-1].decision -cne 'approved' -or
        $reviews[-1].draft_sha256 -cne $Bundle.draft_sha256 -or
        $source.draft.draft_sha256 -cne $Bundle.draft_sha256 -or
        $source.draft.analysis_id -cne $id
    ) { throw 'Source analysis is not approved at the supplied digest' }
    $cases = @($source.draft.test_cases | Where-Object { $_.id -ceq $Bundle.case.id })
    if ($cases.Count -ne 1) { throw 'Source case is missing or ambiguous' }
    $fields = @('id', 'title', 'category', 'preconditions', 'steps', 'expected_result', 'source_criterion_ids')
    $savedCase = $cases[0] | Select-Object -Property $fields | ConvertTo-Json -Depth 10 -Compress
    $bundledCase = $Bundle.case | Select-Object -Property $fields | ConvertTo-Json -Depth 10 -Compress
    if ($savedCase -cne $bundledCase) { throw 'Bundled case differs from the approved source' }
}

$isRun = $PSCmdlet.ParameterSetName -eq 'ReviewedRun'
$bundle = $null
$receipt = $null
$codeBytes = $null
if ($isRun) {
    if ((Get-Item -LiteralPath $BundlePath).Length -gt 262144 -or
        (Get-Item -LiteralPath $ReviewPath).Length -gt 16384) { throw 'Approval input exceeds its size limit' }
    $bundleBytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $BundlePath).Path)
    $receipt = Get-Content -Raw -LiteralPath $ReviewPath | ConvertFrom-Json
    $bundle = [Text.Encoding]::UTF8.GetString($bundleBytes) | ConvertFrom-Json
    if ($receipt.decision -cne 'approved' -or $receipt.reviewer -isnot [string] -or
        [string]::IsNullOrWhiteSpace($receipt.reviewer)) { throw 'Explicit executable approval is required' }
    if ((Get-BytesHash $bundleBytes) -cne $receipt.bundle_sha256) { throw 'Bundle changed after review' }
    if ($bundle.code -isnot [string] -or $bundle.scenario -cne 'energy_lower_boundary_v1') {
        throw 'Unsupported artifact bundle'
    }
    $codeBytes = [Text.Encoding]::UTF8.GetBytes($bundle.code)
    $digest = Get-BytesHash $codeBytes
    if ($digest -cne $receipt.artifact_sha256 -or $digest -cne $bundle.artifact_sha256 -or
        $digest -cnotmatch '^[0-9a-f]{64}$') { throw 'Executable artifact changed after review' }
    # scenario.py is a review convenience; execution uses the verified bundle bytes.
    $scenarioPath = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $BundlePath).Path) 'scenario.py'
    if (-not (Test-Path -LiteralPath $scenarioPath) -or
        (Get-FileHash -LiteralPath $scenarioPath).Hash.ToLowerInvariant() -cne $digest) {
        throw 'Reviewed scenario file differs from the executable bundle'
    }
    Assert-SourceApproval $bundle
}

$baseImage = Invoke-Docker image inspect --format '{{.Id}}' qi-playwright-runner
$demoImage = Invoke-Docker image inspect --format '{{.Id}}' qi-m1-foundation-demo
if ($baseImage -notmatch '^sha256:[0-9a-f]{64}$' -or $demoImage -notmatch '^sha256:[0-9a-f]{64}$') {
    throw 'Local image identities could not be pinned'
}
$runnerImage = $baseImage
$artifactImage = $null
$baseTag = $null
$stagePath = $null
$networkName = 'qi-preflight-' + [guid]::NewGuid().ToString('N')
$demo = $null
$runner = $null
$waitJob = $null
$networkCreated = $false
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$reportPath = Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path 'preflight.json'
if ($isRun) {
    $runId = [guid]::NewGuid().ToString('N')
    $OutputDirectory = Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path $runId
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
    $reportPath = Join-Path $OutputDirectory 'result.json'
}
if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath }
try {
    if ($isRun) {
        $stagePath = Join-Path $OutputDirectory 'build-context'
        New-Item -ItemType Directory -Path $stagePath | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $stagePath 'scenario.py'), $codeBytes)
        # BuildKit does not accept an image config ID as a FROM reference.
        # A private temporary tag points at the captured ID; verify the resulting layers.
        $baseTag = 'qi-trusted-' + $runId
        Invoke-Docker image tag $baseImage $baseTag | Out-Null
        [IO.File]::WriteAllText((Join-Path $stagePath 'Dockerfile'), "FROM $baseTag`nCOPY --chown=1001:1001 scenario.py /artifact/scenario.py`n")
        $artifactImage = 'qi-reviewed-' + $runId
        # COPY only: no generated code is executed during this offline build.
        Invoke-Docker build --quiet --network none --pull=false --tag $artifactImage $stagePath | Out-Null
        $runnerImage = Invoke-Docker image inspect --format '{{.Id}}' $artifactImage
        if ($runnerImage -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Artifact image identity is invalid' }
        $baseLayers = @((Invoke-Docker image inspect $baseImage | ConvertFrom-Json)[0].RootFS.Layers)
        $artifactLayers = @((Invoke-Docker image inspect $runnerImage | ConvertFrom-Json)[0].RootFS.Layers)
        if ($artifactLayers.Count -ne $baseLayers.Count + 1 -or
            ($artifactLayers[0..($baseLayers.Count - 1)] -join ',') -cne ($baseLayers -join ',')) {
            throw 'Artifact image did not extend the pinned trusted base'
        }
    }
    Invoke-Docker network create --internal --opt com.docker.network.bridge.gateway_mode_ipv4=isolated $networkName | Out-Null
    $networkCreated = $true
    $demo = Invoke-Docker create --network $networkName --network-alias demo --dns 127.0.0.1 --read-only --tmpfs '/tmp:rw,noexec,nosuid,size=64m' --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true --memory 256m --cpus 0.5 --pids-limit 100 --log-driver local --log-opt max-size=4m --log-opt max-file=1 --log-opt compress=false $demoImage
    $demoConfig = (Invoke-Docker inspect $demo | ConvertFrom-Json)[0]
    Assert-Container $demoConfig '10001:10001' 268435456 500000000 100 $networkName
    Invoke-Docker start $demo | Out-Null
    $demoConfig = (Invoke-Docker inspect $demo | ConvertFrom-Json)[0]
    $ip = $demoConfig.NetworkSettings.Networks.PSObject.Properties[$networkName].Value.IPAddress
    $runnerArguments = @('--preflight')
    if ($isRun) { $runnerArguments = @('--run', $digest) }
    $runner = Invoke-Docker create --init --network $networkName --dns 127.0.0.1 --add-host "demo:$ip" --sysctl net.ipv6.conf.all.disable_ipv6=1 --ipc private --shm-size 256m --read-only --tmpfs '/tmp:rw,noexec,nosuid,size=256m' --user 1001:1001 --cap-drop ALL --security-opt no-new-privileges:true --security-opt "seccomp=$profile" --memory 1g --cpus 1 --pids-limit 256 --log-driver local --log-opt max-size=4m --log-opt max-file=1 --log-opt compress=false $runnerImage @runnerArguments
    $config = (Invoke-Docker inspect $runner | ConvertFrom-Json)[0]
    Assert-Container $config '1001:1001' 1073741824 1000000000 256 $networkName
    $hostConfig = $config.HostConfig
    $seccomp = @($hostConfig.SecurityOpt | Where-Object { $_.StartsWith('seccomp=') })
    if (
        $seccomp.Count -ne 1 -or
        (($seccomp[0].Substring(8) | ConvertFrom-Json | ConvertTo-Json -Depth 30 -Compress) -cne
            (Get-Content -Raw -LiteralPath $profile | ConvertFrom-Json | ConvertTo-Json -Depth 30 -Compress)) -or
        -not $hostConfig.Init -or $hostConfig.IpcMode -ne 'private' -or
        $hostConfig.ShmSize -ne 268435456 -or
        $hostConfig.Sysctls.'net.ipv6.conf.all.disable_ipv6' -ne '1' -or
        $hostConfig.Dns.Count -ne 1 -or $hostConfig.Dns[0] -ne '127.0.0.1' -or
        $hostConfig.ExtraHosts -notcontains "demo:$ip"
    ) {
        throw 'Browser process controls could not be verified'
    }
    $network = (Invoke-Docker network inspect $networkName | ConvertFrom-Json)[0]
    $unexpectedPeers = @($network.Containers.PSObject.Properties.Name | Where-Object {
        $_ -ne $demo -and $_ -ne $runner
    })
    if (
        -not $network.Internal -or $network.EnableIPv6 -or
        $network.Options.'com.docker.network.bridge.gateway_mode_ipv4' -ne 'isolated' -or
        $unexpectedPeers.Count
    ) {
        throw 'Network restriction could not be verified'
    }
    if ($isRun) { Assert-SourceApproval $bundle }
    Invoke-Docker start $runner | Out-Null
    $waitJob = Start-Job -ArgumentList $runner -ScriptBlock {
        param($ContainerId)
        docker.exe wait $ContainerId
    }
    if (-not (Wait-Job $waitJob -Timeout 60)) {
        Invoke-Docker kill $runner | Out-Null
        throw 'Runner preflight exceeded 60 seconds'
    }
    Receive-Job $waitJob | Out-Null
    # The local log driver chunks long JSON records. Tail=1 can return only
    # the final screenshot fragment. The container log itself is capped at 4 MB.
    $text = (Invoke-Docker logs $runner) -join [Environment]::NewLine
    if ($text.Length -gt 1500000) {
        throw 'Preflight report exceeded its limit'
    }
    $report = $text | ConvertFrom-Json
    $exitCode = Invoke-Docker inspect --format '{{.State.ExitCode}}' $runner
    if ($isRun) {
        $screenshot = $report.screenshot_base64
        $report.PSObject.Properties.Remove('screenshot_base64')
        $evidence = [ordered]@{
            run_id = $runId; created_at = [DateTime]::UtcNow.ToString('o')
            analysis_id = $bundle.analysis_id; draft_sha256 = $bundle.draft_sha256
            case_id = $bundle.case.id; artifact_sha256 = $digest
            bundle_sha256 = $receipt.bundle_sha256; reviewer = $receipt.reviewer
            runner_base_image = $baseImage; artifact_image = $runnerImage; demo_image = $demoImage
            seccomp_sha256 = $expectedProfile; container_exit_code = [int]$exitCode
            observations = $report
            trust_note = 'Artifact and report share a process; observations are not independent attestation.'
        }
        if ($screenshot) {
            $png = [Convert]::FromBase64String($screenshot)
            if ($png.Length -lt 24 -or $png.Length -gt 1000000 -or
                [Convert]::ToHexString($png[0..7]) -cne '89504E470D0A1A0A' -or
                [Convert]::ToHexString($png[12..15]) -cne '49484452' -or
                [Convert]::ToHexString($png[16..19]) -cne '00000500') {
                throw 'Screenshot failed PNG signature/dimension/size checks'
            }
            $height = ([uint32]$png[20] * 16777216) + ([uint32]$png[21] * 65536) + ([uint32]$png[22] * 256) + $png[23]
            if ($height -lt 1 -or $height -gt 8192) { throw 'Screenshot height exceeds its limit' }
            [IO.File]::WriteAllBytes((Join-Path $OutputDirectory 'screenshot.png'), $png)
            $evidence.screenshot_sha256 = Get-BytesHash $png
        }
        $evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath
        if ($exitCode -ne '0' -or $report.outcome -cne 'passed' -or
            -not $report.code_executed -or -not $report.sandbox_verified -or -not $screenshot) {
            throw "Reviewed scenario did not pass. See $reportPath"
        }
        Write-Output "Reviewed scenario passed. Evidence: $reportPath"
        return
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath
    if ($exitCode -ne '0' -or $report.outcome -ne 'ready' -or $report.code_executed) {
        throw "Preflight blocked execution. See $reportPath"
    }
    Write-Output "Runner preflight ready. No artifact executed. Report: $reportPath"
} catch {
    if ($isRun -and -not (Test-Path -LiteralPath $reportPath)) {
        [ordered]@{
            run_id = $runId; outcome = 'launcher_error'
            detail = $_.Exception.Message; artifact_sha256 = $digest
            execution_status = 'Do not infer scenario outcome from this launcher failure'
        } | ConvertTo-Json | Set-Content -LiteralPath $reportPath
    }
    throw
} finally {
    if ($waitJob) {
        Remove-Job $waitJob -Force -ErrorAction SilentlyContinue
    }
    if ($runner) { & docker.exe rm -f $runner | Out-Null }
    if ($demo) { & docker.exe rm -f $demo | Out-Null }
    if ($networkCreated) { & docker.exe network rm $networkName | Out-Null }
    if ($artifactImage -and (& docker.exe image ls --quiet $artifactImage)) { & docker.exe image rm $artifactImage | Out-Null }
    if ($baseTag) { & docker.exe image rm $baseTag | Out-Null }
    if ($stagePath) {
        # Only these two explicitly created files; never recurse over caller paths.
        Remove-Item -LiteralPath (Join-Path $stagePath 'scenario.py') -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $stagePath 'Dockerfile') -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stagePath -ErrorAction SilentlyContinue
    }
}

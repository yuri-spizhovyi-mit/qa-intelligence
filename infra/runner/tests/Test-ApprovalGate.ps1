# Run only after exact-file human review, inside network-disabled Docker.
# Exercises the actual launcher. Both HTTP and Docker are replaced by sentinels.
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot '../Invoke-ReviewedScenario.ps1'
$global:GateTestState = $null

function global:docker.exe {
    $global:GateTestState.DockerCalls++
    throw 'REACHED_DOCKER_BOUNDARY'
}

function global:Invoke-RestMethod {
    param($Uri, $MaximumRedirection, $TimeoutSec)
    $global:GateTestState.HttpCalls++
    if ($Uri -cne 'http://localhost:8000/api/v1/analyses/11111111-1111-4111-8111-111111111111' -or
        $MaximumRedirection -ne 0 -or $TimeoutSec -ne 10) {
        throw 'Unexpected source request'
    }
    if ($global:GateTestState.Unavailable) { throw 'SOURCE_UNAVAILABLE' }
    return $global:GateTestState.Source
}

function Get-TestHash([byte[]] $Bytes) {
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

$cases = @(
    @{ Name = 'valid approval reaches Docker boundary'; Mutation = 'valid'; Error = 'REACHED_DOCKER_BOUNDARY'; Http = 1; Docker = 1 },
    @{ Name = 'pending executable approval'; Mutation = 'pending'; Error = 'Explicit executable approval is required'; Http = 0; Docker = 0 },
    @{ Name = 'missing executable decision'; Mutation = 'missing-decision'; Error = 'Explicit executable approval is required'; Http = 0; Docker = 0 },
    @{ Name = 'blank reviewer'; Mutation = 'blank-reviewer'; Error = 'Explicit executable approval is required'; Http = 0; Docker = 0 },
    @{ Name = 'changed bundle bytes'; Mutation = 'bundle-bytes'; Error = 'Bundle changed after review'; Http = 0; Docker = 0 },
    @{ Name = 'changed code with stale executable hash'; Mutation = 'code'; Error = 'Executable artifact changed after review'; Http = 0; Docker = 0 },
    @{ Name = 'receipt executable digest differs'; Mutation = 'receipt-digest'; Error = 'Executable artifact changed after review'; Http = 0; Docker = 0 },
    @{ Name = 'separate reviewed file changed'; Mutation = 'scenario-file'; Error = 'Reviewed scenario file differs from the executable bundle'; Http = 0; Docker = 0 },
    @{ Name = 'separate reviewed file missing'; Mutation = 'missing-file'; Error = 'Reviewed scenario file differs from the executable bundle'; Http = 0; Docker = 0 },
    @{ Name = 'unsupported scenario'; Mutation = 'unsupported'; Error = 'Unsupported artifact bundle'; Http = 0; Docker = 0 },
    @{ Name = 'source approval revoked'; Mutation = 'source-status'; Error = 'Source analysis is not approved at the supplied digest'; Http = 1; Docker = 0 },
    @{ Name = 'source review history empty'; Mutation = 'empty-history'; Error = 'Source analysis is not approved at the supplied digest'; Http = 1; Docker = 0 },
    @{ Name = 'latest source decision requests changes'; Mutation = 'latest-review'; Error = 'Source analysis is not approved at the supplied digest'; Http = 1; Docker = 0 },
    @{ Name = 'source draft digest differs'; Mutation = 'source-digest'; Error = 'Source analysis is not approved at the supplied digest'; Http = 1; Docker = 0 },
    @{ Name = 'review digest differs'; Mutation = 'review-digest'; Error = 'Source analysis is not approved at the supplied digest'; Http = 1; Docker = 0 },
    @{ Name = 'source case absent'; Mutation = 'missing-case'; Error = 'Source case is missing or ambiguous'; Http = 1; Docker = 0 },
    @{ Name = 'source case duplicated'; Mutation = 'duplicate-case'; Error = 'Source case is missing or ambiguous'; Http = 1; Docker = 0 },
    @{ Name = 'source case content changed'; Mutation = 'changed-case'; Error = 'Bundled case differs from the approved source'; Http = 1; Docker = 0 },
    @{ Name = 'source API unavailable'; Mutation = 'unavailable'; Error = 'SOURCE_UNAVAILABLE'; Http = 1; Docker = 0 },
    @{ Name = 'oversized receipt'; Mutation = 'large-receipt'; Error = 'Approval input exceeds its size limit'; Http = 0; Docker = 0 }
)

$passed = 0
try {
    foreach ($test in $cases) {
        $directory = Join-Path ([IO.Path]::GetTempPath()) ('qi-gate-test-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $directory | Out-Null
        $bundlePath = Join-Path $directory 'bundle.json'
        $reviewPath = Join-Path $directory 'review.json'
        $scenarioPath = Join-Path $directory 'scenario.py'
        $outputPath = Join-Path $directory 'results'
        try {
            $case = [ordered]@{
                id = 'TC-LOW'; title = 'Accept zero'; category = 'boundary'
                preconditions = @('Fresh synthetic event'); steps = @('Submit energy_wh=0')
                expected_result = 'HTTP 201'; source_criterion_ids = @('AC-LOW')
            }
            $bundle = [ordered]@{
                analysis_id = '11111111-1111-4111-8111-111111111111'
                draft_sha256 = 'a' * 64; case = $case; scenario = 'energy_lower_boundary_v1'
                code = "raise RuntimeError('Fixture must never execute')`n"
            }
            $bundle.artifact_sha256 = Get-TestHash ([Text.Encoding]::UTF8.GetBytes($bundle.code))
            # Round-trip removes shared references between the bundle and mocked source.
            $source = @{
                review_status = 'approved'
                draft = @{ analysis_id = $bundle.analysis_id; draft_sha256 = $bundle.draft_sha256; test_cases = @($case) }
                reviews = @(@{ decision = 'approved'; draft_sha256 = $bundle.draft_sha256 })
            } | ConvertTo-Json -Depth 12 | ConvertFrom-Json
            $receipt = [ordered]@{
                decision = 'approved'; reviewer = 'synthetic-reviewer'
                artifact_sha256 = $bundle.artifact_sha256; bundle_sha256 = ''
            }
            [IO.File]::WriteAllText($scenarioPath, $bundle.code)
            switch ($test.Mutation) {
                'pending' { $receipt.decision = 'pending' }
                'missing-decision' { $receipt.Remove('decision') }
                'blank-reviewer' { $receipt.reviewer = '   ' }
                'code' { $bundle.code += '# Changed after executable review' }
                'receipt-digest' { $receipt.artifact_sha256 = 'b' * 64 }
                'scenario-file' { [IO.File]::AppendAllText($scenarioPath, '# Changed review file') }
                'missing-file' { Remove-Item -LiteralPath $scenarioPath }
                'unsupported' { $bundle.scenario = 'unknown-template' }
                'source-status' { $source.review_status = 'changes_requested' }
                'empty-history' { $source.reviews = @() }
                'latest-review' { $source.reviews += [pscustomobject]@{ decision = 'changes_requested'; draft_sha256 = $bundle.draft_sha256 } }
                'source-digest' { $source.draft.draft_sha256 = 'b' * 64 }
                'review-digest' { $source.reviews[0].draft_sha256 = 'b' * 64 }
                'missing-case' { $source.draft.test_cases = @() }
                'duplicate-case' { $source.draft.test_cases += $source.draft.test_cases[0] }
                'changed-case' { $source.draft.test_cases[0].expected_result = 'HTTP 200' }
            }
            [IO.File]::WriteAllText($bundlePath, ($bundle | ConvertTo-Json -Depth 12))
            $receipt.bundle_sha256 = Get-TestHash ([IO.File]::ReadAllBytes($bundlePath))
            if ($test.Mutation -eq 'bundle-bytes') { [IO.File]::AppendAllText($bundlePath, "`n") }
            [IO.File]::WriteAllText($reviewPath, ($receipt | ConvertTo-Json))
            if ($test.Mutation -eq 'large-receipt') { [IO.File]::AppendAllText($reviewPath, (' ' * 16385)) }
            $global:GateTestState = @{
                Source = $source; Unavailable = ($test.Mutation -eq 'unavailable')
                HttpCalls = 0; DockerCalls = 0
            }
            $observed = $null
            try {
                & $launcher -BundlePath $bundlePath -ReviewPath $reviewPath -OutputDirectory $outputPath | Out-Null
            } catch { $observed = $_.Exception.Message }
            if ($observed -cne $test.Error -or
                $global:GateTestState.HttpCalls -ne $test.Http -or
                $global:GateTestState.DockerCalls -ne $test.Docker -or
                (Test-Path -LiteralPath $outputPath)) {
                throw "FAILED $($test.Name): error=[$observed], HTTP=$($global:GateTestState.HttpCalls), Docker=$($global:GateTestState.DockerCalls)"
            }
            $passed++
            Write-Output "PASS $($test.Name)"
        } finally {
            # Delete only known fixture files and their empty directory. Never recurse.
            foreach ($file in @($bundlePath, $reviewPath, $scenarioPath)) {
                if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
            }
            if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory }
        }
    }
    Write-Output "$passed/$($cases.Count) approval gate scenarios passed; no real HTTP, Docker or artifact execution."
} finally {
    Remove-Item -LiteralPath Function:\docker.exe -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath Function:\Invoke-RestMethod -ErrorAction SilentlyContinue
    Remove-Variable -Name GateTestState -Scope Global -ErrorAction SilentlyContinue
}

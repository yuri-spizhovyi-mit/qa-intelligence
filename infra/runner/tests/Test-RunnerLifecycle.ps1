# Exact-file human review is required before isolated Docker execution.
# Runs the real preflight launcher with simulated Docker and job boundaries.
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot '../Test-RunnerPreflight.ps1'
$global:LifecycleState = $null

function New-FakeContainer([bool] $Runner) {
    $s = $global:LifecycleState
    $network = @{}
    $network[$s.Network] = @{ IPAddress = '172.31.0.2' }
    $hostConfig = @{
        ReadonlyRootfs = $true; Privileged = $false; CapDrop = @('ALL'); CapAdd = @()
        SecurityOpt = @('no-new-privileges:true', ('seccomp=' + $s.Policy))
        Memory = 268435456; NanoCpus = 500000000; PidsLimit = 100
        PortBindings = @{}; Init = $true; IpcMode = 'private'; ShmSize = 268435456
        Sysctls = @{ 'net.ipv6.conf.all.disable_ipv6' = '1' }
        Dns = @('127.0.0.1'); ExtraHosts = @('demo:172.31.0.2')
    }
    $config = @{ User = '10001:10001'; Env = @('HOME=/tmp') }
    $mounts = @()
    if ($Runner) {
        $config.User = '1001:1001'
        $hostConfig.Memory = 1073741824
        $hostConfig.NanoCpus = 1000000000
        $hostConfig.PidsLimit = 256
        switch ($s.Mode) {
            'root' { $config.User = '0:0' }
            'writable' { $hostConfig.ReadonlyRootfs = $false }
            'mount' { $mounts = @(@{ Type = 'bind'; Source = '/synthetic-host'; Destination = '/host' }) }
            'capability' { $hostConfig.CapAdd = @('SYS_ADMIN') }
            'credential' { $config.Env += 'SYNTHETIC_API_KEY=fixture' }
            'port' { $hostConfig.PortBindings = @{ '8000/tcp' = @(@{ HostPort = '12345' }) } }
            'memory' { $hostConfig.Memory = 0 }
            'cpu' { $hostConfig.NanoCpus = 0 }
            'pids' { $hostConfig.PidsLimit = 0 }
            'seccomp' { $hostConfig.SecurityOpt = @('no-new-privileges:true', 'seccomp={"defaultAction":"SCMP_ACT_ALLOW"}') }
            'ipc' { $hostConfig.IpcMode = 'host' }
        }
    }
    return @{ Config = $config; HostConfig = $hostConfig; Mounts = $mounts; NetworkSettings = @{ Networks = $network } }
}

function global:docker.exe {
    $global:LASTEXITCODE = 0
    $s = $global:LifecycleState
    $a = @($args)
    $operation = ($a[0..([Math]::Min(1, $a.Count - 1))] -join ' ')
    switch ($a[0]) {
        'image' {
            if ($a[1] -cne 'inspect') { throw 'Unexpected image operation' }
            return ('sha256:' + ('1' * 64))
        }
        'network' {
            switch ($a[1]) {
                'create' { $s.Network = $a[-1]; return 'fake-network-id' }
                'inspect' {
                    $peers = @{ 'demo-id' = @{}; 'runner-id' = @{} }
                    $internal = $true
                    if ($s.Mode -eq 'peer') { $peers['foreign-id'] = @{} }
                    if ($s.Mode -eq 'egress') { $internal = $false }
                    return (ConvertTo-Json -Depth 12 -InputObject @(@{
                        Internal = $internal; EnableIPv6 = $false; Containers = $peers
                        Options = @{ 'com.docker.network.bridge.gateway_mode_ipv4' = 'isolated' }
                    }))
                }
                'rm' { $s.Cleanup.Add('network') | Out-Null; return }
                default { throw 'Unexpected network operation' }
            }
        }
        'create' {
            if ($a -contains '--preflight') { return 'runner-id' }
            return 'demo-id'
        }
        'inspect' {
            if ($a -contains '--format') {
                if ($s.Mode -eq 'exit') { return '1' }
                return '0'
            }
            return (ConvertTo-Json -Depth 20 -InputObject @((New-FakeContainer ($a[-1] -ceq 'runner-id'))))
        }
        'start' {
            $s.Started.Add($a[-1]) | Out-Null
            if ($s.Mode -eq 'start-failure' -and $a[-1] -ceq 'runner-id') {
                $global:LASTEXITCODE = 1
            }
            return
        }
        'kill' { $s.Killed.Add($a[-1]) | Out-Null; return }
        'logs' {
            if ($s.Mode -eq 'malformed') { return 'not-json' }
            if ($s.Mode -eq 'oversized') { return ('x' * 1500001) }
            $executed = $s.Mode -eq 'executed'
            return (ConvertTo-Json -Compress -InputObject @{ outcome = 'ready'; code_executed = $executed; sandbox_verified = $true })
        }
        'rm' {
            $s.Cleanup.Add($a[-1]) | Out-Null
            if ($s.Mode -eq 'cleanup-failure' -and $a[-1] -ceq 'runner-id') {
                $global:LASTEXITCODE = 1
            }
            return
        }
        default { throw "Unexpected simulated Docker operation: $operation" }
    }
}

function global:Start-Job {
    param($ArgumentList, $ScriptBlock)
    if ($ArgumentList -cne 'runner-id') { throw 'Unexpected job target' }
    # Never execute the supplied script block or launch a real job.
    return [pscustomobject]@{ Id = 123 }
}
function global:Wait-Job {
    param($Job, $Timeout)
    if ($Timeout -ne 60) { throw 'Outer timeout changed unexpectedly' }
    if ($global:LifecycleState.Mode -ne 'timeout') { return $Job }
}
function global:Receive-Job { param($Job) return '0' }
function global:Remove-Job {
    param($Job, [switch] $Force, $ErrorAction)
    $global:LifecycleState.JobRemoved = $true
}

$cases = @(
    @{ Mode = 'valid'; Error = ''; Start = $true },
    @{ Mode = 'root'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'writable'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'mount'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'capability'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'credential'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'port'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'memory'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'cpu'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'pids'; Error = 'Container controls could not be verified'; Start = $false },
    @{ Mode = 'seccomp'; Error = 'Browser process controls could not be verified'; Start = $false },
    @{ Mode = 'ipc'; Error = 'Browser process controls could not be verified'; Start = $false },
    @{ Mode = 'peer'; Error = 'Network restriction could not be verified'; Start = $false },
    @{ Mode = 'egress'; Error = 'Network restriction could not be verified'; Start = $false },
    @{ Mode = 'timeout'; Error = 'Runner preflight exceeded 60 seconds'; Start = $true },
    @{ Mode = 'start-failure'; Error = 'Docker operation failed: start'; Start = $true },
    @{ Mode = 'exit'; Error = 'Preflight blocked execution.'; Start = $true },
    @{ Mode = 'executed'; Error = 'Preflight blocked execution.'; Start = $true },
    @{ Mode = 'malformed'; Error = 'Conversion from JSON failed'; Start = $true },
    @{ Mode = 'oversized'; Error = 'Preflight report exceeded its limit'; Start = $true },
    @{ Mode = 'cleanup-failure'; Error = 'Cleanup failed'; Start = $true }
)

$passed = 0
try {
    foreach ($case in $cases) {
        $directory = Join-Path ([IO.Path]::GetTempPath()) ('qi-lifecycle-' + [guid]::NewGuid().ToString('N'))
        $global:LifecycleState = @{
            Mode = $case.Mode; Network = ''; Policy = (Get-Content -Raw (Join-Path $PSScriptRoot '../seccomp_chromium.json'))
            Started = [Collections.Generic.List[string]]::new()
            Killed = [Collections.Generic.List[string]]::new()
            Cleanup = [Collections.Generic.List[string]]::new()
            JobRemoved = $false
        }
        try {
            $observed = ''
            try { & $launcher -OutputDirectory $directory | Out-Null }
            catch { $observed = $_.Exception.Message }
            $s = $global:LifecycleState
            if (($case.Error -eq '' -and $observed -ne '') -or
                ($case.Error -ne '' -and -not $observed.StartsWith($case.Error)) -or
                ($s.Started.Contains('runner-id') -ne $case.Start) -or
                ($s.Cleanup -join ',') -cne 'runner-id,demo-id,network') {
                throw "FAILED $($case.Mode): error=[$observed], started=[$($s.Started -join ',')], cleanup=[$($s.Cleanup -join ',')]"
            }
            if ($case.Mode -eq 'timeout' -and ($s.Killed -join ',') -cne 'runner-id') {
                throw 'Timed-out runner was not killed'
            }
            if ($case.Start -and $case.Mode -ne 'start-failure' -and -not $s.JobRemoved) {
                throw 'Wait job was not removed'
            }
            $passed++
            Write-Output "PASS $($case.Mode)"
        } finally {
            foreach ($file in @('preflight.json', 'cleanup.json')) {
                $path = Join-Path $directory $file
                if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
            }
            if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory }
        }
    }
    Write-Output "$passed/$($cases.Count) lifecycle scenarios passed; Docker and jobs were simulated, no artifact executed."
} finally {
    foreach ($name in @('docker.exe', 'Start-Job', 'Wait-Job', 'Receive-Job', 'Remove-Job')) {
        Remove-Item -LiteralPath "Function:\$name" -ErrorAction SilentlyContinue
    }
    Remove-Variable -Name LifecycleState -Scope Global -ErrorAction SilentlyContinue
}

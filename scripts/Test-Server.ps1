param([Parameter(Mandatory=$true)][string]$Bundle)
# Run only against a disposable extracted portable, never an installed/user folder.
$ErrorActionPreference = 'Stop'
$Bundle = (Resolve-Path -LiteralPath $Bundle).Path
if (-not (Test-Path -LiteralPath (Join-Path $Bundle 'portable.flag'))) { throw 'A disposable portable bundle is required.' }
$configPath = Join-Path $Bundle 'userdata\config.json'
$original = [IO.File]::ReadAllBytes($configPath)
$server = $null
$collision = $null
$listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
function Test-Endpoint {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/hardware" -TimeoutSec 2
        throw 'Protected endpoint unexpectedly allowed anonymous access.'
    } catch [Net.WebException] {
        $response = $_.Exception.Response
        if (-not $response) { return $false }
        try {
            if ([int]$response.StatusCode -ne 401 -or $response.Headers['Server'] -notlike 'SemaforoIA/*') {
                throw 'Unexpected server response.'
            }
            return $true
        } finally { $response.Close() }
    }
}
try {
    $config = Get-Content -Raw -LiteralPath $configPath -Encoding UTF8 | ConvertFrom-Json
    $config.server_port = $port
    [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 30), (New-Object Text.UTF8Encoding($false)))
    $exe = Join-Path $Bundle 'SemaforoServer.exe'
    $server = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Bundle 'userdata\server-test.stdout') -RedirectStandardError (Join-Path $Bundle 'userdata\server-test.stderr')
    $ready = $false
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 30) {
        if ($server.HasExited) { throw 'Frozen server exited during startup; inspect server-test.stderr.' }
        if (Test-Endpoint) { $ready = $true; break }
        Start-Sleep -Milliseconds 200
    }
    if (-not $ready) { throw 'Frozen server did not become ready.' }
    $collision = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Bundle 'userdata\collision-test.stdout') -RedirectStandardError (Join-Path $Bundle 'userdata\collision-test.stderr')
    if (-not $collision.WaitForExit(15000) -or $collision.ExitCode -eq 0) { throw 'Occupied port did not fail clearly.' }
    if ($server.HasExited -or -not (Test-Endpoint)) { throw 'Port collision affected the original process.' }
    Write-Output 'Frozen server starts, protects endpoints and rejects occupied ports without a recursive GUI launch.'
} finally {
    foreach ($owned in @($collision, $server)) {
        if ($owned -and -not $owned.HasExited) { Stop-Process -Id $owned.Id; $owned.WaitForExit() }
    }
    [IO.File]::WriteAllBytes($configPath, $original)
}

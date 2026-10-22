param([Parameter(Mandatory=$true)][string]$Zip, [switch]$Production)
$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('Temp\Semaforo portable Unicode-' + [char]0x00f1 + '-' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $testRoot | Out-Null
Expand-Archive -LiteralPath $Zip -DestinationPath $testRoot
$bundle = Join-Path $testRoot 'SemaforoIA'
$environment = @{}
foreach ($name in 'Path','PYTHONHOME','PYTHONPATH','QT_QPA_PLATFORM') {
    $environment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:Path = "$env:WINDIR\System32;$env:WINDIR"
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $expected = Get-Content -Raw -LiteralPath (Join-Path $bundle '_internal\product.json') -Encoding UTF8 | ConvertFrom-Json
    if ($Production) {
        foreach ($exe in 'SemaforoIA.exe','SemaforoCLI.exe','SemaforoServer.exe') {
            & (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') -File (Join-Path $bundle $exe) -VerifyOnly -NativeOnly
        }
    }
    $version = & (Join-Path $bundle 'SemaforoCLI.exe') --version
    if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne $expected.version) { throw 'CLI/version mismatch.' }
    $diagnostics = & (Join-Path $bundle 'SemaforoCLI.exe') diagnose
    if ($LASTEXITCODE -ne 0) { throw 'CLI local smoke failed.' }
    $result = $diagnostics | ConvertFrom-Json
    if (-not $result.portable -or $result.data_root -ne (Join-Path $bundle 'userdata')) { throw 'Portable policy failed.' }
    $env:QT_QPA_PLATFORM = 'offscreen'
    try {
        $report = Join-Path $testRoot 'desktop-smoke.json'
        $process = Start-Process -FilePath (Join-Path $bundle 'SemaforoIA.exe') -ArgumentList @('--self-test','--smoke-report',('"' + $report + '"')) -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit(90000)) { throw 'GUI smoke timed out; inspect this test process without terminating unrelated applications.' }
        if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw 'GUI local smoke failed.' }
        $gui = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
        if (-not $gui.login_visible -or $gui.version -ne $expected.version) { throw 'GUI/version mismatch.' }
    } finally { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
    & (Join-Path $PSScriptRoot 'Test-Server.ps1') -Bundle $bundle
    Write-Output "Frozen GUI/CLI/server checks passed; retained test directory: $testRoot"
} finally {
    foreach ($name in $environment.Keys) { [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process') }
}

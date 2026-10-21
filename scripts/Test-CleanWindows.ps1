param([Parameter(Mandatory=$true)][string]$Setup,
      [Parameter(Mandatory=$true)][string]$Portable,
      [string]$PreviousSetup, [switch]$Production, [switch]$PurgeTestData)
# Run in Windows Sandbox / disposable Windows 10 1809+ or Windows 11 x64 VM as a standard user.
# This script does not use Python, pip, Git, Inno Setup or a compiler.
$ErrorActionPreference = 'Stop'
$local = [Environment]::GetFolderPath('LocalApplicationData')
$data = Join-Path $local 'SemaforoIA'
$app = Join-Path $local 'Programs\SemaforoIA'
if (Test-Path -LiteralPath $data) { throw 'Use a clean disposable user: data already exists. Nothing was deleted.' }
if (Test-Path -LiteralPath $app) { throw 'Use a clean disposable user: installation already exists.' }
function Install-Setup([string]$Path) {
    if ($Production) { & (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') -File $Path -VerifyOnly -NativeOnly }
    $process = Start-Process -FilePath $Path -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-' -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Setup exit code $($process.ExitCode)" }
}
if ($PreviousSetup) { Install-Setup $PreviousSetup } else { Install-Setup $Setup }
if ($Production) {
    foreach ($name in 'SemaforoIA.exe','SemaforoCLI.exe','SemaforoServer.exe','unins000.exe') {
        & (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') -File (Join-Path $app $name) -VerifyOnly -NativeOnly
    }
}
& (Join-Path $app 'SemaforoCLI.exe') diagnose
if ($LASTEXITCODE -ne 0) { throw 'Installed local features failed.' }
$testPassword = [guid]::NewGuid().ToString('N') + 'aA1@'
@($testPassword,$testPassword) | & (Join-Path $app 'SemaforoCLI.exe') init-admin --username validation_owner
if ($LASTEXITCODE -ne 0) { throw 'Initial administrator creation failed.' }
Remove-Variable testPassword
$sentinel = Join-Path $data 'upgrade-sentinel.txt'
'preserve-me' | Set-Content -LiteralPath $sentinel
$configHash = (Get-FileHash -LiteralPath (Join-Path $data 'config.json') -Algorithm SHA256).Hash
$databaseHash = (Get-FileHash -LiteralPath (Join-Path $data 'semaforo.sqlite3') -Algorithm SHA256).Hash
if ($PreviousSetup) {
    $before = & (Join-Path $app 'SemaforoCLI.exe') --version
    Install-Setup $Setup
    $after = & (Join-Path $app 'SemaforoCLI.exe') --version
    if ($Production) {
        foreach ($name in 'SemaforoIA.exe','SemaforoCLI.exe','SemaforoServer.exe','unins000.exe') {
            & (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') -File (Join-Path $app $name) -VerifyOnly -NativeOnly
        }
    }
    if ($before.Trim() -eq $after.Trim()) { throw 'Upgrade requires two actually compiled, different versions.' }
    if ((Get-FileHash -LiteralPath (Join-Path $data 'config.json') -Algorithm SHA256).Hash -ne $configHash) { throw 'Update overwrote config.' }
    if ((Get-FileHash -LiteralPath (Join-Path $data 'semaforo.sqlite3') -Algorithm SHA256).Hash -ne $databaseHash) { throw 'Update overwrote database.' }
}
& (Join-Path $PSScriptRoot 'Test-Bundle.ps1') -Zip $Portable -Production:$Production
if (-not (Test-Path -LiteralPath $sentinel)) { throw 'Portable affected installed data.' }
$uninstall = Join-Path $app 'unins000.exe'
$process = Start-Process -FilePath $uninstall -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $sentinel) -or (Test-Path -LiteralPath (Join-Path $app 'SemaforoIA.exe'))) { throw 'Uninstall/preservation check failed.' }
if ($PurgeTestData) {
    # The initial fresh-user guards above ensure this only contains test data.
    Install-Setup $Setup
    $process = Start-Process -FilePath (Join-Path $app 'unins000.exe') -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /PURGEUSERDATA=1' -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0 -or (Test-Path -LiteralPath $data)) { throw 'Explicit purge failed.' }
}
Write-Output 'Clean Windows installation, coexistence and uninstall checks passed.'

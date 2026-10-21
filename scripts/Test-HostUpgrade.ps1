param([Parameter(Mandatory=$true)][string]$PreviousSetup,
      [string]$NextSetup, [string]$StateFile)
# Optional developer-host test. It refuses existing installations and redirects
# ONLY application test data, never silently repurposing real user data.
$ErrorActionPreference = 'Stop'
$install = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\SemaforoIA'
$registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{48F91B83-1464-47F8-A13B-B2A64372D6D1}_is1'
function Run-Setup([string]$File) {
    $process = Start-Process -FilePath $File -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-' -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installer exit: $($process.ExitCode)" }
}
if (-not $StateFile) {
    if ((Test-Path -LiteralPath $install) -or (Test-Path -LiteralPath $registry)) { throw 'An existing installation is present; nothing was changed.' }
    $sandbox = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('Temp\Semaforo-host-validation-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $sandbox | Out-Null
    $StateFile = Join-Path $sandbox 'validation-state.json'
    Run-Setup $PreviousSetup
} else {
    $state = Get-Content -Raw -LiteralPath $StateFile | ConvertFrom-Json
    $sandbox = $state.sandbox
    if ($state.install -ne $install -or -not (Test-Path -LiteralPath (Join-Path $install 'unins000.exe'))) { throw 'Host validation installation missing.' }
}
$oldLocal, $oldPath = $env:LOCALAPPDATA, $env:Path
try {
    $env:LOCALAPPDATA = $sandbox
    $env:Path = "$env:WINDIR\System32;$env:WINDIR"
    $cli = Join-Path $install 'SemaforoCLI.exe'
    if (-not $state) {
        $password = [guid]::NewGuid().ToString('N') + 'Aa1@'
        @($password,$password) | & $cli init-admin --username validation_owner
        Remove-Variable password
        if ($LASTEXITCODE -ne 0) { throw 'Compiled first administrator creation failed.' }
        & $cli diagnose
        if ($LASTEXITCODE -ne 0) { throw 'Compiled installed diagnose failed.' }
        $state = [ordered]@{ sandbox=$sandbox; install=$install; previous=(& $cli --version).Trim();
            configHash=(Get-FileHash -LiteralPath (Join-Path $sandbox 'SemaforoIA\config.json')).Hash;
            databaseHash=(Get-FileHash -LiteralPath (Join-Path $sandbox 'SemaforoIA\semaforo.sqlite3')).Hash }
        $state | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
    }
    if ($NextSetup) {
        Run-Setup $NextSetup
        $after = (& $cli --version).Trim()
        if ($after -eq $state.previous) { throw 'Two actually compiled versions are required.' }
        if ((Get-FileHash -LiteralPath (Join-Path $sandbox 'SemaforoIA\config.json')).Hash -ne $state.configHash) { throw 'Configuration/accounts were overwritten.' }
        if ((Get-FileHash -LiteralPath (Join-Path $sandbox 'SemaforoIA\semaforo.sqlite3')).Hash -ne $state.databaseHash) { throw 'SQLite was overwritten.' }
        $info = Get-ItemProperty -LiteralPath $registry
        if ($info.DisplayVersion -ne $after) { throw 'Installed Apps version mismatch.' }
        & $cli diagnose
        if ($LASTEXITCODE -ne 0) { throw 'Updated installed features failed.' }
        $process = Start-Process -FilePath (Join-Path $install 'unins000.exe') -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0 -or (Test-Path -LiteralPath (Join-Path $install 'SemaforoIA.exe')) -or (Test-Path -LiteralPath $registry)) { throw 'Uninstall failed.' }
        if (-not (Test-Path -LiteralPath (Join-Path $sandbox 'SemaforoIA\semaforo.sqlite3'))) { throw 'Uninstall removed test data.' }
        Write-Output "Host update $($state.previous) -> $after and uninstall passed. Retained isolated data: $sandbox"
    }
    Write-Output "Validation state: $StateFile"
} finally { $env:LOCALAPPDATA=$oldLocal; $env:Path=$oldPath }

param([Parameter(Mandatory=$true)][string]$PreviousZip,
      [Parameter(Mandatory=$true)][string]$NextZip)
$ErrorActionPreference = 'Stop'
$root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('Temp\Semaforo portable upgrade-' + [char]0x00f1 + '-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $root | Out-Null
Expand-Archive -LiteralPath $PreviousZip -DestinationPath (Join-Path $root 'previous')
Expand-Archive -LiteralPath $NextZip -DestinationPath (Join-Path $root 'next')
$previous = Join-Path $root 'previous\SemaforoIA'
$next = Join-Path $root 'next\SemaforoIA'
foreach ($folder in $previous,$next) {
    if (-not (Test-Path -LiteralPath (Join-Path $folder 'portable.flag')) -or (Test-Path -LiteralPath (Join-Path $folder 'userdata'))) { throw 'Fresh portable archives are required.' }
}
$environment = @{}
foreach ($name in 'Path','PYTHONHOME','PYTHONPATH') { $environment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:Path = "$env:WINDIR\System32;$env:WINDIR"
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $cli = Join-Path $previous 'SemaforoCLI.exe'
    $password = [guid]::NewGuid().ToString('N') + 'aA1@'
    @($password,$password) | & $cli init-admin --username portable_owner
    Remove-Variable password
    if ($LASTEXITCODE -ne 0) { throw 'Portable initial administrator failed.' }
    $before = (& $cli --version).Trim()
    $configHash = (Get-FileHash -LiteralPath (Join-Path $previous 'userdata\config.json')).Hash
    $dbHash = (Get-FileHash -LiteralPath (Join-Path $previous 'userdata\semaforo.sqlite3')).Hash
    $moved = Join-Path $root ('moved with spaces-' + [char]0x00f1)
    # Validate the complete recursive move stays inside this freshly created test root.
    $prefix = [IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
    foreach ($candidate in $previous,$moved) {
        if (-not [IO.Path]::GetFullPath($candidate).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test move.' }
    }
    Move-Item -LiteralPath $previous -Destination $moved
    $diagnostic = & (Join-Path $moved 'SemaforoCLI.exe') diagnose
    if ($LASTEXITCODE -ne 0) { throw 'Moved portable failed.' }
    $result = $diagnostic | ConvertFrom-Json
    if (-not $result.portable -or $result.data_root -ne (Join-Path $moved 'userdata')) { throw 'Moved portable retained an old path.' }
    Copy-Item -LiteralPath (Join-Path $moved 'userdata') -Destination (Join-Path $next 'userdata') -Recurse
    $after = (& (Join-Path $next 'SemaforoCLI.exe') --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $before -eq $after) { throw 'Two actually compiled, different versions are required.' }
    & (Join-Path $next 'SemaforoCLI.exe') diagnose
    if ($LASTEXITCODE -ne 0) { throw 'Updated portable failed.' }
    foreach ($folder in $moved,$next) {
        if ((Get-FileHash -LiteralPath (Join-Path $folder 'userdata\config.json')).Hash -ne $configHash -or
            (Get-FileHash -LiteralPath (Join-Path $folder 'userdata\semaforo.sqlite3')).Hash -ne $dbHash) { throw 'Portable update changed accounts or SQLite.' }
    }
    Write-Output "Portable move and update $before -> $after passed. Retained evidence: $root"
} finally {
    foreach ($name in $environment.Keys) { [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process') }
}

param([string]$Python = 'py', [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$product = Get-Content -Raw -LiteralPath (Join-Path $root 'product.json') | ConvertFrom-Json
Set-Location -LiteralPath $root
if ($Python -eq 'py') { $version = & py -3.13 -c 'import platform; print(platform.python_version())' }
else { $version = & $Python -c 'import platform; print(platform.python_version())' }
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne $product.python) { throw "Se requiere Python $($product.python) x64 para compilar." }
$pythonExe = Join-Path $root '.build-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    if ($Python -eq 'py') { & py -3.13 -m venv (Join-Path $root '.build-venv') }
    else { & $Python -m venv (Join-Path $root '.build-venv') }
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de build.' }
}
& $pythonExe -c "import struct; assert struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) { throw 'El entorno no es x64.' }
if (-not $SkipInstall) {
    & $pythonExe -m pip install --disable-pip-version-check --require-hashes -r (Join-Path $root 'packaging\requirements-windows.lock')
    if ($LASTEXITCODE -ne 0) { throw 'La instalación del lock falló.' }
    & $pythonExe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependencias incompatibles.' }
}
Write-Output $pythonExe

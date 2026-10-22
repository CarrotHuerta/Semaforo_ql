param([ValidateSet('Development','Production')][string]$Channel = 'Development',
      [string]$ISCC, [switch]$SkipTests, [switch]$SkipFreeze)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$product = Get-Content -Raw -LiteralPath (Join-Path $root 'product.json') -Encoding UTF8 | ConvertFrom-Json
$python = Join-Path $root '.build-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Ejecute scripts/Initialize-Build.ps1 primero.' }
function Invoke-Python([string[]]$Arguments) {
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python falló: $($Arguments -join ' ')" }
}
$production = $Channel -eq 'Production'
if ($production -and ($SkipTests -or $SkipFreeze)) { throw 'Producción requiere pruebas y compilación limpia.' }
if ($production) {
    foreach ($name in 'SIGNTOOL_PATH','SIGN_CERT_SHA1','SIGN_CERT_SHA256','SIGN_EXPECTED_SUBJECT') {
        if (-not [Environment]::GetEnvironmentVariable($name)) { throw "Falta $name. Producción nunca usa fallback sin firma." }
    }
    $certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $env:SIGN_CERT_SHA1)
    if (-not $certificate.HasPrivateKey -or $certificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -cne $product.publisher) {
        throw 'Publisher de product.json debe coincidir con la identidad legal del certificado y su clave debe estar accesible.'
    }
}
Invoke-Python -Arguments @('-c',"import platform,struct; from importlib.metadata import version; assert platform.python_version() == '$($product.python)' and struct.calcsize('P') == 8; assert version('pyinstaller') == '$($product.pyinstaller)'")
if (-not $SkipTests) {
    $env:QT_QPA_PLATFORM = 'offscreen'
    Invoke-Python -Arguments @('-X','faulthandler','-m','unittest','-v')
    Remove-Item Env:QT_QPA_PLATFORM
}
if (-not $SkipFreeze) {
    $freezeRoot = Join-Path $root ("dist\windows-$($product.version)-" + $Channel.ToLowerInvariant())
    $existing = Join-Path $freezeRoot 'SemaforoIA'
    foreach ($personal in 'userdata','config.json','semaforo.sqlite3','portable.flag') {
        if (Test-Path -LiteralPath (Join-Path $existing $personal)) { throw "El destino contiene datos de uso: $existing. Muévalos antes de compilar." }
    }
    Invoke-Python -Arguments @('scripts/prepare_distribution.py')
    Invoke-Python -Arguments @('-m','PyInstaller','--noconfirm','--clean','--workpath','build/frozen','--distpath',$freezeRoot,'packaging/SemaforoIA.spec')
}
$bundle = Join-Path $root ("dist\windows-$($product.version)-" + $Channel.ToLowerInvariant() + '\SemaforoIA')
Invoke-Python -Arguments @('scripts/prepare_distribution.py','--verify',$bundle)
Invoke-Python -Arguments @('scripts/audit_native.py',$bundle)
if ($production) {
    foreach ($name in 'SemaforoIA.exe','SemaforoCLI.exe','SemaforoServer.exe') {
        & (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') -File (Join-Path $bundle $name)
    }
} else {
    'UNSIGNED DEVELOPMENT BUILD. Not a production release.' | Set-Content -LiteralPath (Join-Path $bundle 'DEVELOPMENT-UNSIGNED.txt') -Encoding UTF8
}
& (Join-Path $PSScriptRoot 'Inventory-Binaries.ps1') -Bundle $bundle -Production:$production
Invoke-Python -Arguments @('scripts/bundle_manifest.py',$bundle)
if (-not $ISCC) { $ISCC = Join-Path $root 'build\tools\InnoSetup\ISCC.exe' }
if (-not (Test-Path -LiteralPath $ISCC)) { throw 'Falta Inno Setup 6.7.3; ejecute Install-InnoSetup.ps1 o pase -ISCC.' }
$innoVersion = [version]$product.inno_setup
$compilerVersion = ($innoVersion.Major -shl 24) -bor ($innoVersion.Minor -shl 16) -bor ($innoVersion.Build -shl 8)
$output = Join-Path $root ("artifacts\" + $Channel.ToLowerInvariant() + '\' + $product.version)
if ($production -and (Test-Path -LiteralPath $output) -and @(Get-ChildItem -LiteralPath $output -File).Count -gt 0) {
    throw 'Ya existen artefactos de producción para esta versión. No se sobrescribirán.'
}
New-Item -ItemType Directory -Path $output -Force | Out-Null
$suffix = if ($production) { '' } else { '-dev' }
$signedUninstaller = Join-Path $root ('build\signed-uninstallers\' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $signedUninstaller -Force | Out-Null
$arguments = @("/DAppVersion=$($product.version)","/DPublisher=$($product.publisher)","/DBundleRoot=$bundle","/DRequiredCompilerVersion=$compilerVersion",
               "/DOutputRoot=$output","/DIconFile=$(Join-Path $root 'packaging\app.ico')","/DChannelSuffix=$suffix",
               "/DProduction=$([int]$production)","/DSignedUninstallerRoot=$signedUninstaller")
if ($production) {
    # Inno invokes the same fail-closed signer for the embedded uninstaller first,
    # then the finished setup. $f is substituted by Inno, including its quotes.
    $signer = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $q' + (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') + '$q -File $f'
    $arguments += '/Ssemaforo=' + $signer
}
& $ISCC @arguments (Join-Path $root 'packaging\SemaforoIA.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup falló.' }
$stem = "SemaforoIA-$($product.version)-windows-x64$suffix"
$setup = Join-Path $output "$stem-setup.exe"
if ($production) {
    & (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') -File $setup -VerifyOnly
    $uninstallers = @(Get-ChildItem -LiteralPath $signedUninstaller -File)
    if ($uninstallers.Count -eq 0) { throw 'Inno no produjo evidencia del desinstalador firmado.' }
    foreach ($file in $uninstallers) { & (Join-Path $PSScriptRoot 'Sign-Artifact.ps1') -File $file.FullName -VerifyOnly }
}
$stage = Join-Path $root ('build\portable-' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$portable = Join-Path $stage 'SemaforoIA'
Copy-Item -LiteralPath $bundle -Destination $portable -Recurse
New-Item -ItemType File -Path (Join-Path $portable 'portable.flag') | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'docs\PORTABLE.md') -Destination (Join-Path $portable 'PORTABLE.md')
Invoke-Python -Arguments @('scripts/bundle_manifest.py',$portable)
$zip = Join-Path $output "$stem-portable.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
Invoke-Python -Arguments @('scripts/verify_artifacts.py',$zip)
Invoke-Python -Arguments @('scripts/bundle_manifest.py',$bundle,'--verify')
@($setup,$zip) | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + [IO.Path]::GetFileName($_) } |
    Set-Content -LiteralPath (Join-Path $output 'SHA256SUMS.txt') -Encoding ASCII
& (Join-Path $PSScriptRoot 'Test-Checksums.ps1') -Directory $output -Production:$production
Write-Output "Artefactos listos para revisión: $output"

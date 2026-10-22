$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$tools = Join-Path $root 'build\tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$installer = Join-Path $tools 'innosetup-6.7.3.exe'
if (-not (Test-Path -LiteralPath $installer)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $installer
}
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne '9C73C3BAE7ED48D44112A0F48E66742C00090BDB5BEF71D9D3C056C66E97B732') { throw 'Hash de Inno Setup incorrecto.' }
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') { throw 'Firma del compilador Inno Setup no confiable.' }
$destination = Join-Path $tools 'InnoSetup'
$process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/CURRENTUSER',('/DIR="' + $destination + '"')) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Instalación de Inno Setup falló: $($process.ExitCode)" }
Write-Output (Join-Path $destination 'ISCC.exe')

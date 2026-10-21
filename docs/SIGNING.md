# Firma de producción

## Estado y requisitos externos

La canalización está implementada, pero **no se ha firmado una release de
producción en esta tarea**. No se proporcionó certificado ni acceso a un proveedor.
Los instaladores/ZIP generados localmente son de desarrollo sin firma.

Obtenga un certificado de firma de código de confianza pública cuya identidad
sea validable en Chile y un proveedor CSP/KSP compatible con SignTool. La clave
debe permanecer en token/HSM o servicio de firma; no exporte PFX para GitHub.
Confirme con la CA si admite su identidad jurídica, residencia, tipo de cuenta
(persona/organización) y operación automatizada antes de contratar.

No se presume acceso a Microsoft Artifact Signing: su lista pública de países
admitidos no incluye Chile a la fecha de consulta; las cuentas individuales
tienen restricciones adicionales. Verifique la elegibilidad vigente en la
[documentación oficial](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
Private Trust no sustituye un certificado público para distribuir esta app.

Si se elige un servicio remoto compatible con KSP, use su autenticación de
corta duración/OIDC cuando lo admita. El flujo actual usa un certificado ya
aprovisionado en `CurrentUser\My`, accesible por el proveedor de hardware; no
guarda tokens ni claves en GitHub. No se agrega `id-token: write` sin un proveedor
definido. Para una integración REST/OIDC distinta, mantenga este mismo contrato
de verificación y evite credenciales persistentes.

## Entorno protegido

Prepare un runner **dedicado, efímero o cuidadosamente administrado**, Windows
x64, con etiqueta `semaforo-signing`, Python 3.13.6 y Windows SDK SignTool.
Instale el proveedor del token/HSM bajo la cuenta que ejecuta el runner y
aprovisione su certificado público en `Cert:\CurrentUser\My`. La clave no debe
ser exportable. Confirme que firma sin diálogos interactivos, según las políticas
del proveedor. El runner de firma nunca debe ejecutar código de PR.

En GitHub cree el entorno `windows-production-signing`, con aprobación humana
obligatoria y regla de despliegue limitada a main protegido. Cree también
`windows-release-draft` con revisión. La comprobación `if` del YAML complementa
estas reglas, no las reemplaza. Proteja cambios de workflows/scripts mediante
revisión y reglas de rama. El job de firma solo tiene `contents: read`; únicamente
el job separado que crea el borrador obtiene `contents: write`.

Configure variables del entorno, sin claves privadas:

| Variable | Contenido |
| --- | --- |
| `SIGNTOOL_PATH` | Ruta absoluta al SignTool x64 del Windows SDK |
| `SIGN_CERT_SHA1` | Thumbprint de 40 hex para SELECCIONAR el certificado |
| `SIGN_CERT_SHA256` | SHA-256 de los bytes DER del certificado esperado, 64 hex |
| `SIGN_EXPECTED_SUBJECT` | Subject completo EXACTO que muestra Get-AuthenticodeSignature |
| `SIGN_TIMESTAMP_URL` | Endpoint RFC 3161 del proveedor; default `http://timestamp.digicert.com` |

La huella SHA-1 se usa como selector `/sha1`, nunca como algoritmo de firma.
El nombre simple/CN del certificado debe coincidir con `publisher` de
`product.json`; cambie ese campo al editor legal real antes de compilar producción.
Para calcular la huella pública SHA-256 sin exportar claves:

```powershell
$cert = Get-Item 'Cert:\CurrentUser\My\<thumbprint>'
$sha = [Security.Cryptography.SHA256]::Create()
[BitConverter]::ToString($sha.ComputeHash($cert.RawData)).Replace('-','')
$sha.Dispose()
$cert.Subject
```

No almacene contraseñas, PIN, certificados privados ni tokens en los comandos,
logs, variables de repositorio o artefactos. Configure sesiones/roles del
proveedor fuera del repositorio, con permisos mínimos y expiración.

## Ejecución y orden obligatorio

```powershell
./scripts/Build-Windows.ps1 -Channel Production
```

1. Pruebas, compilación limpia y metadatos de los tres EXE propios.
2. Firma de GUI, CLI y servidor mediante `/fd SHA256 /tr ... /td SHA256`.
3. Inno Setup usa `SignedUninstaller=yes` y el SignTool registrado por `/S`.
   Firma el desinstalador generado ANTES de incorporarlo, y firma el Setup
   final al terminar la compilación. No se firma solo un EXE de desinstalación
   suelto después de construir el instalador.
4. Se verifica el Setup final y cada uninstaller generado por Inno. El directorio
   de caché de desinstaladores es nuevo en cada build, evitando reutilizar una
   firma de otra identidad o versión.
5. Se crea el ZIP portable desde los EXE ya firmados, sin modificarlos, y se
   comprueba su manifiesto final. El marcador/guía no modifican los EXE.
6. Se generan checksums de los dos artefactos finales. El ZIP no tiene Authenticode.

Cada firma propia se verifica con `signtool verify /pa /all /v`, WinVerifyTrust
mediante Get-AuthenticodeSignature, certificado exacto SHA-256, Subject,
timestamp presente, digest CMS SHA-256 y atributo RFC 3161. Una firma ausente,
no confiable, de otra identidad o sin timestamp aborta. No hay fallback sin firma.
No se aceptan `-SkipTests` ni `-SkipFreeze` en producción ni se sobrescriben
artefactos existentes de esa versión.

`Inventory-Binaries.ps1` registra individualmente terceros. No se refirman sus
DLL/PYD. Los componentes sin firma conservan ese estado y quedan identificados
por hash/versión/paquete; un componente con firma existente inválida hace fallar
producción. No se afirma que todas las bibliotecas estén firmadas. Los textos
de licencia se incluyen en THIRD_PARTY.

En una VM sin Windows SDK, `Sign-Artifact.ps1 -VerifyOnly -NativeOnly` verifica
confianza Windows, identidad, digest y timestamp sin ejecutar SignTool. La
pipeline de build usa siempre SignTool además de esas verificaciones. El test
de Windows limpio verifica también el `unins000.exe` realmente instalado.

## Publicación y reputación

El workflow manual `windows-production.yml` crea únicamente un borrador tras
aprobar los entornos. No invoca `gh release edit --draft=false` ni publica nada.
Complete las pruebas de Windows 11 limpio, incluidas actualización entre dos
versiones compiladas y firma del desinstalador instalado, antes de publicar
manualmente. Compare hashes con SHA256SUMS.

Una firma válida no garantiza ausencia de avisos de reputación de SmartScreen
o Smart App Control. Un certificado EV tampoco garantiza eliminarlos. No se
instalan raíces, no se generan certificados autofirmados para distribución
pública y no se cambian Defender ni controles de Windows.

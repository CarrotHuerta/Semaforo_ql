# Build 1.0.2 para compartir y probar en Windows 10

Fecha: 21 de octubre de 2026. Build de desarrollo sin firma propia; no es una
release de producción. Mínimo configurado: Windows 10 1809 (build 17763), x64.
La compilación y todas las ejecuciones indicadas aquí ocurrieron en Windows 11
x64 build 26200 con herramientas de desarrollo instaladas. No se dispone de
evidencia de ejecución directa en Windows 10 ni de una VM Windows limpia.

## Artefactos compilados

Compilación limpia con `scripts/Build-Windows.ps1 -Channel Development`, Python
3.13.6 x64, PyInstaller 6.22.2, PySide6 6.11.2 e Inno Setup 6.7.3. Se reutilizó
el entorno dedicado con versiones fijadas; `pip check` terminó correctamente.
GUI, CLI y servidor contienen metadatos FileVersion/ProductVersion 1.0.2.

| Archivo | Tamaño en bytes |
| --- | ---: |
| `SemaforoIA-1.0.2-windows-x64-dev-setup.exe` | 124084101 |
| `SemaforoIA-1.0.2-windows-x64-dev-portable.zip` | 151333559 |

SHA-256 del instalador:
`ce23760d837c291d58368957d0442caed2a8aae1193ceb2bfb27d11f44872fcc`.

SHA-256 del portable:
`a4c33ec597faae611dbf5304798aa4858fb41d2e582d95f9547bdc7071c8150c`.

Originales en `artifacts/development/1.0.2/`. Copias para compartir en
`artifacts/compartir/SemaforoIA-1.0.2-Windows10-x64/`, junto con `LEEME.md`,
`RESULTADOS-PRUEBAS.md` y `SHA256SUMS.txt`. Los artefactos están ignorados por Git.

## Resultados comprobados

- **166 pruebas del código correctas**, 47,338 segundos.
- Auditoría de importaciones PE: **171 binarios nativos** y dependencias MSVC
  presentes en el paquete. La configuración inicial y la lista de distribución
  pasaron la validación de exclusión de datos personales/cuentas existentes.
- Inventario Authenticode: **126 firmas válidas de terceros y 45 componentes
  sin firma**, incluidos los tres ejecutables propios. El instalador y el
  desinstalador son de desarrollo sin firma propia. No se modificaron firmas
  existentes de terceros. El detalle está en `native-inventory.json` del paquete.
- `Test-Bundle.ps1`: ZIP extraído en ruta con espacios y `ñ`; PATH limitado a
  Windows, sin PYTHONHOME/PYTHONPATH. CLI 1.0.2, SQLite, exportaciones locales
  PDF/JSON/CSV/Excel e importaciones de dependencias pasaron. La GUI congelada
  mostró el login mediante Qt offscreen y coincidió en versión y persistencia.
- `Test-Server.ps1`: servidor congelado operativo, endpoint protegido con HTTP
  401, segundo proceso rechazado por puerto ocupado y cierre de procesos propios.
- `Test-PortableUpgrade.ps1`: traslado de toda la carpeta y actualización real
  **1.0.1 → 1.0.2**, conservando hashes de configuración/cuentas y SQLite.
- `Test-HostUpgrade.ps1`: instalación real por usuario de 1.0.1, creación de una
  cuenta de prueba en datos aislados, actualización a 1.0.2, diagnóstico local,
  versión en Aplicaciones instaladas y desinstalación silenciosa correctos.
  Conservó datos y cuentas. También se verificó que la configuración y SQLite
  personales existentes permanecieran intactos.
- `SHA256SUMS.txt` y manifiesto final del portable verificados. Los checksums se
  comprobaron otra vez sobre las copias de la carpeta para compartir.

La primera instalación de la versión anterior se detuvo con código 1: el host
tenía una preferencia de compatibilidad `WIN8RTM` para la ruta del instalador
1.0.1, por lo que Windows se identificaba como 8. Se conservó esa preferencia.
La prueba posterior utilizó una copia byte a byte del instalador anterior en
otra ruta; su hash coincidió y la actualización/desinstalación terminó con
código 0. No se alteró el instalador 1.0.2 para eludir requisitos del sistema.

Los logs locales están en `artifacts/validation/1.0.2/`: `build.log`,
`compiled-tests.log`, `installer-baseline.log` y `host-upgrade.log`.
`compiled-tests.log` contiene las pruebas portables correctas y el primer
intento de instalación interrumpido; `host-upgrade.log` registra la prueba
posterior correcta. Las carpetas de prueba se conservaron para inspección.

## Pendiente antes de producción

- Ejecución en Windows 10 x64 limpio, sin Python ni herramientas de desarrollo.
  El procedimiento está en `docs/WINDOWS-DISTRIBUTION.md`; la build 1.0.2 permite
  probar la instalación inicial sin instalar la versión histórica 1.0.1.
- Validación interactiva completa y en una unidad USB física. El login offscreen
  y las rutas Unicode locales no equivalen a esas pruebas.
- Certificado/proveedor confiable, firma y verificación positiva de EXE propios,
  instalador y desinstalador mediante la canalización de producción.

No se publicó ninguna release pública. Esta entrega se puede compartir como
build de prueba sin firma, conservando esa identificación y estas limitaciones.

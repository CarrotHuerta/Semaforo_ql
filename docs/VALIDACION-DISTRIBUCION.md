# Evidencia de validación Windows

Fecha: 20 de octubre de 2026. Equipo real Windows 11 x64, build 26200,
con herramientas de desarrollo instaladas. No equivale a una VM Windows limpia.
No se publicó ninguna release pública ni se ejecutó el workflow de firma.

## Implementación entregada

- Tres ejecutables onedir con runtime Python, Qt/plugins, MSVC app-local,
  exportaciones PDF/Excel/JSON/CSV y licencias. Un `.spec` mantenido y recursos
  propios autorizados individualmente; configuración inicial sin cuentas.
- Instalador y desinstalador Inno por usuario, AppId estable, actualización,
  accesos directos, preservación de datos y purga explícita con validación.
- ZIP portable completo, marcador explícito, datos aislados, errores de
  escritura sin cambiar silenciosamente de ubicación y guía de actualización.
- Primer administrador, migración explícita con respaldo, SQLite validado y
  claves Fernet portables; servicios externos y modelos no se instalan.
- Scripts y workflows separados de desarrollo/producción, firmas Authenticode
  SHA-256 con RFC 3161, verificación de identidad/confianza, inventarios,
  checksums y creación de borrador tras aprobación de entornos protegidos.

La implementación de firma no constituye evidencia de una firma realizada:
faltan certificado/proveedor y runner autorizado. Producción aborta ante su
ausencia. Los artefactos locales llevan `-dev` y `DEVELOPMENT-UNSIGNED.txt`.

## Pruebas del código

`Build-Windows.ps1 -Channel Development` ejecutó **166 pruebas**, todas correctas
en **46,768 segundos**, con Python 3.13.6 x64 y el lock instalado en `.build-venv`.
Incluyen GUI/CLI, rutas, defaults sin sobrescritura, primer administrador,
persistencia, respaldo de esquema, rechazo de esquema futuro, migración con
validación SQLite, copia solo de fotos referenciadas, descifrado después de mover
las claves, prevención de recursión MLflow y manipulación de ZIP.

La prueba adicional de puerto ocupado detectó un problema real con
`SO_REUSEADDR` en Windows. Se corrigió con `SO_EXCLUSIVEADDRUSE`, se agregó
regresión y el servidor respeta `server_host`, con localhost inicial.

`pip check` pasó. Ruff pasó con F821/F823/E9. Los scripts PowerShell y los JSON/YAML
de configuración/workflows se analizaron sin errores de sintaxis.

## Binarios y artefactos

Se compilaron dos versiones reales, 1.0.0 y 1.0.1, mediante el entorno fijado,
PyInstaller 6.22.2 e Inno Setup 6.7.3. Los artefactos revisables son de desarrollo:

```
artifacts/development/1.0.1/SemaforoIA-1.0.1-windows-x64-dev-setup.exe
artifacts/development/1.0.1/SemaforoIA-1.0.1-windows-x64-dev-portable.zip
artifacts/development/1.0.1/SHA256SUMS.txt
```

Los binarios, entornos, bases, secretos y artefactos no se agregan al commit.
Se conservó la distribución histórica `dist/SemaforoIA` y los archivos personales
del repositorio. Los recursos personales no forman parte del paquete nuevo.

## Pruebas reales de ejecución

Los scripts conservan directorios temporales con evidencia para inspección:

- `Test-Bundle.ps1`: extrae el ZIP en una ruta con espacios y `ñ`, reduce PATH
  a Windows/System32 y quita PYTHONHOME/PYTHONPATH. Ejecuta CLI y GUI congeladas,
  comprueba versión, login visible mediante Qt offscreen, datos en `userdata`,
  SQLite y exportaciones reales. No necesita iniciar Python, pip ni Git.
- `Test-Server.ps1`: ejecuta el servidor congelado, comprueba HTTP 401 sin token,
  segundo proceso con puerto ocupado y continuidad del primero; cierra solo
  procesos creados por la prueba y restaura la configuración temporal.
- `Test-HostUpgrade.ps1`: instaló realmente 1.0.0 por usuario, creó un administrador
  con la CLI congelada y datos de prueba aislados, actualizó a 1.0.1 y comparó
  hashes de config/SQLite. Comprobó versión en Aplicaciones instaladas y
  desinstalación silenciosa conservando los datos de prueba.
- `Test-PortableUpgrade.ps1`: extrajo los ZIP reales 1.0.0/1.0.1, creó una cuenta
  con la CLI anterior, movió toda su carpeta a otra ruta con espacios/Unicode,
  ejecutó el diagnóstico y copió `userdata` a la versión nueva. Ambos hashes
  de cuentas/config y SQLite permanecieron intactos; terminó con código 0 y
  PATH limitado a Windows. Se conservaron ambas carpetas de prueba.

Los servicios MLflow, Ollama y PostgreSQL no fueron necesarios para estos
diagnósticos locales. La suite incluye cancelación y cierre de procesos propios;
no se afirma una prueba de un servicio MLflow/Ollama real no instalado.

La auditoría PE exige MSVC dentro del paquete aunque exista en el host. El
inventario nativo identifica firmas existentes de terceros y componentes sin
firma; nunca se afirma que todo el paquete esté firmado. Consulte el inventario
de cada build y sus hashes, no una afirmación genérica de firma.

En la compilación final 1.0.1 se auditaron **171 binarios nativos**: Windows
informó **126 firmas válidas** y **45 componentes sin firma**, incluidos los tres
EXE propios de desarrollo. SHA256SUMS y el manifiesto final del ZIP pasaron.
Las pruebas finales de GUI/CLI/servidor y actualización/desinstalación indicadas
arriba terminaron con código 0, después de recompilar la corrección del socket.

Logs locales de esta ejecución (fuera de Git), bajo `%TEMP%`:

```
semaforo-final-1.0.1-build.log
semaforo-final-portable-verified.log
semaforo-final-baseline-install.log
semaforo-final-upgrade-verified.log
semaforo-portable-update-verified.log
```

## Pendientes externos antes de producción

1. Proveedor/certificado público elegible para la propietaria en Chile, identidad
   legal del editor y acceso CSP/KSP a la clave mediante hardware/servicio.
   Configurar variables, runner dedicado y entornos protegidos según `SIGNING.md`.
2. Ejecutar la compilación de producción y verificar positivamente firmas de los
   tres EXE, Setup y desinstalador instalado. Se comprobó el rechazo de un EXE
   sin firma y la negativa a compilar producción sin configuración de firma;
   no hubo una prueba positiva con certificado propio.
3. VM Windows 11 x64 limpia, cuenta estándar sin Python/Git/SDK: ejecutar
   `Test-CleanWindows.ps1` con dos versiones reales. Falta esa evidencia y la
   de su purga explícita en una cuenta desechable. Windows Sandbox no estaba
   disponible en este host.
4. Revisión interactiva de instalación, escritorio opcional, apertura final,
   login y checkbox de desinstalación desmarcado/marcado. El smoke offscreen no
   sustituye toda la interacción, aunque la actualización portable sí se comprobó
   con dos versiones reales y conservación de datos.
5. Unidad extraíble física: no había una conectada para probarla. Se probaron
   rutas locales con espacios/Unicode y traslado de claves mediante tests;
   falta validar la ejecución y persistencia desde hardware extraíble real.
6. Observar los resultados de GitHub Actions después del push y, tras firma y
   validación pendientes, revisar el borrador. Ningún workflow publica por sí solo.

El instalador exige Windows 11 build 22000 o superior. Solo se probó este host
build 26200; no se certifican todos los builds, Windows 10 ni ARM64.

El procedimiento reproducible de la VM está en `WINDOWS-DISTRIBUTION.md`.
Estas distinciones son condiciones pendientes de validación, no evidencias
inventadas ni una declaración de que la release de producción está terminada.

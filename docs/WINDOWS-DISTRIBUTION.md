# Distribución Windows

## Plataformas y alcance

Se mantiene Python/PySide6. Objetivo soportado por esta distribución: **Windows
10 versión 1809 (build 17763) o posterior, x64**, incluido Windows 11. El
instalador aplica ese mínimo contractual, derivado de la plataforma oficialmente
documentada por Qt 6.11 para Windows x64. Es una barrera del paquete, no una
afirmación de que se probaron todas las ediciones/builds. La validación directa
en Windows 10 sigue pendiente; el host disponible es Windows 11. No se anuncia
compatibilidad con ARM64/emulación, Wine o Windows de 32 bits. Ver
[plataformas de Qt](https://doc.qt.io/qt-6.11/supported-platforms.html) y
`docs/VALIDACION-DISTRIBUCION.md` para las pruebas realmente realizadas.

Windows 10 Home/Pro terminó soporte general de Microsoft el 14 de octubre de
2025 (ediciones LTSC tienen ciclos separados). Compatibilidad técnica no equivale
a recibir actualizaciones de seguridad del sistema; consulte el ciclo de vida de
[Windows 10 en Microsoft](https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro).

`product.json` es la fuente de versión, editor, versiones de herramientas y
requisito Windows. No reutilice una versión para dos releases de producción.
El AppId de Inno Setup se mantiene estable entre versiones. El script verifica
la versión exacta del compilador con el preprocesador de Inno.

## Compilar desde cero

En una máquina Windows de compilación instale **CPython 3.13.6 x64**. No se
instala Python en los equipos destino. Abra PowerShell en el repositorio:

```powershell
./scripts/Initialize-Build.ps1
./scripts/Install-InnoSetup.ps1
./scripts/Build-Windows.ps1 -Channel Development
```

Puede pasar `-Python 'C:\ruta\python.exe'` a Initialize-Build. Se crea
`.build-venv` sin reutilizar el entorno personal `.venv`. El lock fija ruedas
Windows y dependencias transitivas con SHA-256, incluido pip 25.2. `pip check`
debe pasar. Al actualizar dependencias regenere los hashes de las ruedas exactas,
revise licencias y pruebe una compilación limpia; no quite `--require-hashes`.

Inno Setup 6.7.3 se descarga de su release oficial, se verifica su hash y su
firma Pyrsys B.V., y se instala por usuario dentro de `build/tools`. No se
instala globalmente. Los artefactos quedan en:

```
artifacts/development/<version>/SemaforoIA-<version>-windows-x64-dev-setup.exe
artifacts/development/<version>/SemaforoIA-<version>-windows-x64-dev-portable.zip
artifacts/development/<version>/SHA256SUMS.txt
```

Los binarios intermedios se generan en `dist/windows-<version>-development`.
No se toca la distribución histórica `dist/SemaforoIA`. Un destino con datos
de uso o un marcador portable impide reconstruir encima de él. Las opciones
`-SkipTests` y `-SkipFreeze` sirven para depurar builds de desarrollo;
producción las rechaza. `build_exe.bat` es un acceso a este mismo proceso.

El `.spec` compartido genera tres EXE **onedir** con un único `_internal`:
GUI, CLI y servidor HTTP opcional. PyInstaller incluye Python, Qt, plugins,
extensiones nativas, gráficos/PDF/Excel/criptografía y cliente MLflow. La lista
`packaging/distribution-files.json` autoriza recursos propios individualmente;
no se incluyen el config/models personal, fotos, SQLite, secretos o backups.
`native-inventory.json` registra DLL/PYD/EXE, hashes, firmas y timestamps.
`distribution-manifest.json` fija el contenido final y se comprueba dentro del
ZIP. La reproducibilidad se refiere a entradas controladas y reconstrucción
limpia; timestamps Authenticode y ZIP no prometen identidad binaria entre builds.

## Instalación, actualización y desinstalación

El instalador no requiere administrador y usa
`%LOCALAPPDATA%\Programs\SemaforoIA`. Crea acceso en Inicio y ofrece escritorio.
Se registra en Aplicaciones instaladas. No instala servicios, tareas, reglas
de firewall, inicio automático ni entradas PATH. El servidor se ejecuta solo
manualmente: `SemaforoServer.exe` (escucha en `127.0.0.1` y el puerto de config.json;
puede configurar `server_host` explícitamente para otra interfaz). No abre el
firewall por sí mismo. Un puerto ocupado produce un error; no comparte el socket
con otro proceso en Windows. Cierre el servidor con Ctrl+C en su consola.

Ejecute el instalador nuevo para actualizar. Cierre previamente GUI, CLI y
servidor. Sus mutex impiden actualizar archivos en uso; el instalador no mata
procesos ni usa Restart Manager para cerrar aplicaciones ajenas. No borre una
instalación antigua a mano antes de actualizar. Los recursos se reemplazan y
los datos permanecen fuera de la instalación.
El mismo control protege el desinstalador: [AppMutex de Inno Setup](https://jrsoftware.org/ishelp/topic_setup_appmutex.htm).

```powershell
./SemaforoIA-<version>-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
& "$env:LOCALAPPDATA\Programs\SemaforoIA\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Instalación interactiva ofrece abrir la app al terminar. Instalación silenciosa
no abre la GUI. Inno documenta códigos: 0 éxito, 1 inicialización fallida,
2 cancelación inicial, 3 error de preparación, 4 error de instalación,
5 cancelación durante instalación, 6 terminación desde depurador,
7 no puede continuar, 8 requiere reinicio. Trate todo resultado distinto de cero
como fallo y registre `/LOG="ruta"` si necesita diagnóstico.
[Referencia oficial](https://jrsoftware.org/ishelp/topic_setupexitcodes.htm).

El desinstalador conserva datos por defecto. La opción interactiva de eliminación
empieza desmarcada. En silencio solo elimina datos con **`/PURGEUSERDATA=1`**.
La purga está limitada al directorio AppData de la cuenta actual, exige marcador
de propiedad y rechaza enlaces/reparse points antes del borrado. No recorre
exportaciones externas, portables ni datos de otros usuarios. No cambie la ruta
AppData entre usuarios para purgar. Cierre la aplicación antes de desinstalar.

## Datos y primer inicio

Los datos instalados viven en `%LOCALAPPDATA%\SemaforoIA`. El desarrollo usa
`userdata` del repositorio para no afectar la instalación. El portable usa
solo `userdata` al lado de `portable.flag`; no depende del cwd. El marcador se
busca junto a **cada ejecutable**, no en `_MEIPASS`. GUI, CLI y servidor comparten
la política. El lock de instancia también está en la carpeta de datos, por lo
que instalado y portable pueden coexistir.

Los defaults se copian solo si no existen. No se distribuyen cuentas. Cree su
administrador en la GUI o con `SemaforoCLI.exe init-admin --username propietario`
(contraseña oculta y confirmación). Para automatizar, este comando acepta dos
líneas por stdin; no ponga la contraseña en argumentos, archivos o logs.
Una cuenta existente impide inicializar otra vez. El archivo de exclusión de
primer inicio `.account-setup.lock` solo debe retirarse manualmente tras un
cierre anormal y comprobando que no hay procesos de Semáforo abiertos.

Migración antigua: en el login nuevo pulse **Migrar distribución anterior** o:

```
SemaforoCLI.exe migrate --source "D:\Semaforo antiguo" --confirm
```

La migración es explícita, exige destino vacío/default, valida JSON y SQLite,
respalda los originales en `backups/migration-*`, copia hashes de cuentas,
fotos referenciadas y claves Fernet, y conserva el origen. No importa
exportaciones externas. Si se interrumpe, conserve el respaldo y el origen;
restaure en una carpeta vacía antes de reintentar. `COMPLETED` indica finalización.
No combine a mano bases de dos instalaciones. Si el origen tiene datos MLflow,
respalde también `mlflow_data` por separado: no se mueve automáticamente, ya
que el servidor MLflow del paquete es externo.

Antes de convertir una base con `user_version` anterior se crea un respaldo
SQLite consistente en `backups/*-schema-*-to-*.sqlite3`. Una base de esquema
posterior bloquea el descenso de versión. Si una migración de esquema falla,
cierre todos los procesos, conserve la base fallida y restaure el respaldo con
`SemaforoCLI.exe --database "ruta\semaforo.sqlite3" restore --source "respaldo"`.
Conserve también config/models/secrets para recuperar credenciales y metadatos.

Las claves Fernet son archivos portables, no DPAPI: mover los datos junto con
`secrets/*.key` conserva el descifrado. Sin esas claves se deben reintroducir
las credenciales. Las cuentas usan hashes PBKDF2, nunca contraseñas en claro.

## Integraciones y funcionamiento local

SQLite, catálogos, cálculo, proyectos, historial y exportaciones funcionan sin
servicios externos. `SemaforoCLI.exe diagnose` prueba esos componentes usando
datos temporales y devuelve JSON. La GUI ofrece `--self-test --smoke-report ruta`
para pruebas del ejecutable real. No requiere cuentas ni conexión de red.
Las conversiones de divisas de FinOps requieren una tasa válida de la API o de
su caché local; sin ella se informa que la conversión no está disponible. No se
distribuyen tasas personales ni se inventa una tasa para aparentar conectividad.

MLflow es **cliente** `mlflow-skinny`: configure una Tracking URI de un servidor
externo. El ejecutable congelado nunca ejecuta `sys.executable -m mlflow` ni
incluye un servidor MLflow implícito. Un desarrollador con servidor MLflow
instalado aparte puede habilitar autostart en su entorno fuente. Ollama requiere
instalación y modelo previos; no se descargan modelos al abrir un chat. PostgreSQL
requiere un servidor ya existente. `DB_MODE=postgres`/`DB_*` son configuración
explícita; SQLite sigue siendo el modo local predeterminado.

## Automatización y evidencia

Las PR y main ejecutan pruebas y builds de desarrollo sin secretos en un runner
Windows alojado. Las acciones están fijadas por commit. Producción solo admite
ejecución manual desde main protegido y un runner de firma dedicado con entorno
aprobado; crea únicamente un **borrador** y nunca publica una release pública.
Consulte `SIGNING.md` para configurar esa máquina y `VALIDACION-DISTRIBUCION.md`
para distinguir implementado, compilado y probado.

## Verificación en Windows limpio

Copie a una VM Windows x64 desechable (Windows 10 1809+ y Windows 11) los artefactos de dos versiones
realmente compiladas, `scripts/Test-CleanWindows.ps1`, `Test-Bundle.ps1`, `Test-Server.ps1` y
`Sign-Artifact.ps1`. Use una cuenta nueva sin instalación/datos de Semáforo.
No instale Python, Git, pip ni SDK en esa VM:

```powershell
./Test-CleanWindows.ps1 -Setup 'C:\artefactos\SemaforoIA-1.0.1-windows-x64-dev-setup.exe' `
  -PreviousSetup 'C:\artefactos\SemaforoIA-1.0.0-windows-x64-dev-setup.exe' `
  -Portable 'C:\artefactos\SemaforoIA-1.0.1-windows-x64-dev-portable.zip' -PurgeTestData
```

Ese ejemplo histórico de actualización utiliza instaladores cuyo mínimo era
Windows 11. La build 1.0.2 es la primera entrega compilada con el mínimo Windows
10. Para comprobar su instalación inicial en una VM Windows 10 limpia:

```powershell
./Test-CleanWindows.ps1 -Setup 'C:\artefactos\SemaforoIA-1.0.2-windows-x64-dev-setup.exe' `
  -Portable 'C:\artefactos\SemaforoIA-1.0.2-windows-x64-dev-portable.zip' -PurgeTestData
```

Para probar una actualización instalada en Windows 10, use como `-PreviousSetup`
la build 1.0.2 y como `-Setup` y `-Portable` una versión posterior realmente
compilada con el mismo mínimo. No reutilice las builds históricas que bloquean
Windows 10. Ninguno de estos comandos implica una prueba de Windows 10 realizada.

Para producción use los nombres sin `-dev`, configure las huellas/Subject
públicos documentados en SIGNING.md y añada `-Production`. También pruebe
interactivamente el checkbox de escritorio, apertura final, login, desinstalación
con checkbox desmarcado/marcado y una unidad USB física. El script automatiza
las rutas con espacios/Unicode, creación de cuenta, update, hashes de datos,
coexistencia y desinstalación silenciosa/purga; no reemplaza esa comprobación
interactiva ni certifica hardware extraíble que no se haya conectado.

`Test-HostUpgrade.ps1` permite una prueba adicional en un equipo de desarrollo
sin instalación previa. Redirige solo los datos de la app a un sandbox temporal,
conserva el estado para una segunda llamada con `-NextSetup` y comprueba el
registro real de Aplicaciones instaladas. No es una prueba de Windows limpio.

Para verificar además el traslado y la actualización de portables con dos ZIP
realmente compilados, sin tocar instalaciones existentes:

```powershell
./scripts/Test-PortableUpgrade.ps1 -PreviousZip 'artifacts/development/1.0.0/SemaforoIA-1.0.0-windows-x64-dev-portable.zip' `
  -NextZip 'artifacts/development/1.0.1/SemaforoIA-1.0.1-windows-x64-dev-portable.zip'
```

El script usa carpetas temporales propias, mueve el portable cerrado, copia
`userdata` a la versión nueva y compara hashes de cuentas/SQLite. No sustituye
la prueba física en USB ni el traslado a otro equipo.

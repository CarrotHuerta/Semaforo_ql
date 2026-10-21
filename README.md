# Semáforo IA

Aplicación de escritorio en Python y PySide6 para registrar proyectos y modelos de IA, revisar costos e impacto ambiental y exportar informes. La persistencia local usa SQLite. Las integraciones con PostgreSQL, Ollama y MLflow requieren servicios configurados por separado.

## Desarrollo

Se requiere Python 3.13.6 x64 para el entorno de distribución de Windows. En Windows, el lanzador para desarrollo prepara `.venv`; la primera instalación de dependencias necesita internet:

```powershell
.\run_venv.bat
```

Para crear el entorno manualmente:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Ejecuta la interfaz con `python main.py` y la CLI con `python cli.py --help`. Las pruebas fuente se ejecutan con:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest -v
```

## Distribución de Windows

La versión, el editor y las versiones de las herramientas se definen en `product.json`. Para generar el instalador por usuario y el ZIP portable:

```powershell
.\scripts\Initialize-Build.ps1
.\scripts\Install-InnoSetup.ps1
.\scripts\Build-Windows.ps1 -Channel Development
```

La compilación fija las dependencias y sus hashes. Los artefactos de desarrollo aparecen en `artifacts/development/<versión>/`. El proceso de firma de producción exige un certificado Authenticode confiable y falla si no está configurado. Consulta las guías de [Windows](docs/WINDOWS-DISTRIBUTION.md), [portable](docs/PORTABLE.md), [firma](docs/SIGNING.md), [licencias de terceros](docs/THIRD_PARTY.md) y [validación](docs/VALIDACION-DISTRIBUCION.md).

## Datos locales

La app guarda la configuración, los modelos editables, SQLite, fotos y secretos en `userdata` durante el desarrollo y en `%LOCALAPPDATA%\SemaforoIA` cuando está instalada. En modo portable, esos datos van en `userdata` junto a `portable.flag`. No subas configuraciones, credenciales, bases de datos, fotos de perfiles, respaldos ni exportaciones.

**Antes de actualizar desde un clon anterior a la limpieza del repositorio, respalda `config.json`, `models.json` e `img/`.** Eran archivos versionados en la versión anterior del repositorio; ya no se distribuirán. La app no los sobrescribe y ofrece una migración explícita con respaldo: usa la opción **Migrar distribución anterior** o `SemaforoCLI.exe migrate --source "ruta\anterior" --confirm`.

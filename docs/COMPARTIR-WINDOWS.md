# Compartir Semáforo IA en Windows

La build 1.0.2 está preparada para Windows 10 versión 1809 (build 17763) o
posterior, x64, incluido Windows 11. Es una build de desarrollo sin firma
digital (`-dev`): todavía no es una release de producción firmada. La ejecución
directa en Windows 10 sigue pendiente de validación.

## Qué enviar

Los archivos se generan en `artifacts/development/1.0.2/`:

- `SemaforoIA-1.0.2-windows-x64-dev-setup.exe`: instalador por usuario con
  desinstalador incluido. Es la opción habitual.
- `SemaforoIA-1.0.2-windows-x64-dev-portable.zip`: alternativa sin instalación.
  Hay que extraer el ZIP completo y mantener todos sus archivos juntos.
- `SHA256SUMS.txt`: permite comprobar que los archivos recibidos están intactos.

Envíe el instalador **o** el ZIP según prefiera la persona que lo recibe, junto
con esta guía y los checksums. No necesita enviar el repositorio, Python, pip,
Git, bases de datos, cuentas ni carpetas personales. Los binarios se conservan
fuera de Git; no se publica automáticamente ninguna release en GitHub.

## Instalar y abrir

Ejecute el `setup.exe` y siga el asistente. La instalación predeterminada no
requiere administrador. Abra **Semáforo IA** desde el menú Inicio y cree su
cuenta administradora local en el primer inicio. No hay contraseña compartida.
La desinstalación se realiza desde Aplicaciones instaladas y conserva los datos
salvo que se seleccione expresamente eliminarlos.

## Usar el portable

Extraiga el ZIP en una carpeta con permiso de escritura y abra
`SemaforoIA/SemaforoIA.exe`. No ejecute el EXE desde la vista del ZIP.
Conserve `_internal`, `portable.flag` y los demás archivos. Los datos nuevos se
guardan en `userdata`; puede mover la carpeta completa con la app cerrada.

## Actualizar conservando datos

Instalado: cierre la aplicación, respalde `%LOCALAPPDATA%\SemaforoIA` y ejecute
el nuevo instalador. Portable: cierre la app, respalde `userdata`, extraiga la
versión nueva en otra carpeta y copie allí `userdata`. Conserve el respaldo y
la versión anterior hasta comprobar el acceso y los datos.

## Integridad y alcance

En PowerShell, dentro de la carpeta recibida:

```powershell
Get-FileHash .\SemaforoIA-1.0.2-windows-x64-dev-setup.exe -Algorithm SHA256
Get-FileHash .\SemaforoIA-1.0.2-windows-x64-dev-portable.zip -Algorithm SHA256
```

Compare los valores con `SHA256SUMS.txt`. Un checksum comprueba integridad;
esta build no tiene firma Authenticode propia. Para la distribución pública
de producción falta configurar un certificado/proveedor de firma confiable y
ejecutar la canalización de producción descrita en `docs/SIGNING.md`.

Las funciones locales no necesitan MLflow, Ollama ni PostgreSQL. Las funciones
de esas integraciones requieren servicios configurados por separado; el paquete
no instala esos servidores ni descarga modelos de IA automáticamente.

La carpeta para compartir incluye la evidencia en `RESULTADOS-PRUEBAS.md`
(también registrada en `docs/BUILD-1.0.2-WINDOWS10.md` en el repositorio).
La validación en una VM Windows 10 limpia debe completarse con el procedimiento
de `docs/WINDOWS-DISTRIBUTION.md` antes de dar por comprobada esa plataforma.

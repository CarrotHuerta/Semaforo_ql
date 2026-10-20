# Revisión de arranque y funciones — 20 de octubre de 2026

## Cambios

- `run_venv.bat` verifica las versiones instaladas sin cargar PySide6, MLflow o
  Matplotlib ni consultar la red. Instala dependencias únicamente cuando faltan
  o no cumplen `requirements.txt`; conserva el código de salida de la aplicación.
- El panel crea Inicio al entrar. Las otras diez pantallas se construyen al
  seleccionarlas y conservan su estado entre visitas. Actualizar datos o cambiar
  de idioma no construye pantallas ocultas. El bloqueo Cloud se aplica aunque
  Ajustes se abra después de seleccionar Cloud.
- La detección opcional de servicios comienza después de mostrar el login.
  Descubrir o detener MLflow ya no importa todo su SDK. Las consultas, pruebas
  de conexión y subidas a MLflow se ejecutan fuera del hilo de interfaz; los
  registros locales se conservan si falla la subida.
- El cierre conserva los propietarios de los hilos activos hasta que terminan,
  mientras Qt sigue procesando eventos. Se evita reemplazar un chat activo por
  otra ventana. La simulación reconoce correctamente el hilo de inferencia.
  Salir rápidamente de Hardware cancela su detección pendiente antes de que
  pueda arrancar sobre una pantalla cerrada.
- El menú de cuenta conecta perfil, foto, datos personales, preferencias y las
  acciones administrativas existentes. El cambio de contraseña local verifica
  la contraseña actual y mantiene sincronizados los hashes de configuración y
  SQLite; un fallo de escritura de configuración revierte la transacción SQL.
- Se validan URLs HTTP/HTTPS completas, respuestas de hardware/configuración
  inesperadas, entradas numéricas mal formadas, signos y valores no finitos.
- Los PDF admiten gráficos completamente vacíos y caracteres de la interfaz
  incompatibles con Helvetica mediante equivalentes legibles. JSON y XLSX
  conservan Unicode. Los trabajos de PDF/JSON serializan el acceso a Matplotlib,
  cargan configuración limpia y usan gráficos temporales independientes.
- Los informes también se pueden ejecutar desde otra carpeta. Los archivos
  generados y las bases de trabajo dejan de estar versionados, sin borrarlos
  del equipo.

## Medición

Comparación con `2d71c94`, cinco procesos nuevos por versión, en el mismo entorno
Windows/Python 3.13.6/PySide6. El benchmark usa Qt `offscreen`, recursos locales,
una base temporal y desactiva las consultas externas. Mide la construcción y
el primer procesamiento de eventos, sin incluir autenticación ni arranque de
servicios. Es una medición del código fuente, no de un ejecutable empaquetado.

| Panel principal | Mediana |
| --- | ---: |
| Versión anterior | 668,75 ms |
| Versión revisada | 57,18 ms |

La reducción observada fue aproximadamente 90%. El primer login del código fuente
se mostró en unos 0,4 s. Los tiempos varían con el disco, antivirus, carga del
equipo y cachés. El script permite repetir la medición y comparar otro checkout
con `--project-root`.

## Verificación

Resultado final: **153 pruebas aprobadas en 31,010 segundos**, incluidas 32
pruebas nuevas de regresión. La revisión estática no encontró nombres indefinidos
ni errores de sintaxis; se validaron 40 fuentes Python y 13 archivos JSON,
incluidas las copias históricas de `backup/`.

La suite incluye las pruebas anteriores de cálculos, proyectos, cuotas,
autenticación HTTP, bloqueos, cambio obligatorio de contraseña, importaciones,
sensores, restauración SQLite y errores de escritura. `test_regressions.py`
añade navegación por las once secciones, carga diferida, menús de cuenta,
contraseñas, eventos durante consultas/cierre, lanzador Windows y exportaciones.

La matriz de exportación genera archivos reales para Inicio, Ambiental, FinOps
y Proyectos en PDF, JSON, CSV, XLSX y PDF+JSON. Incluye datos cero, nombres con
acentos/símbolos y solicitudes concurrentes. Las pruebas usan directorios
temporales para los datos de sus escenarios.

También se comprobó manualmente la detección real de CPU/GPU/RAM en Windows,
el arranque y la consulta real del servidor MLflow local, y un turno real de
Ollama con el modelo `llama3.2:1b` ya instalado. Este último devolvió tokens y
duración reales. Se detuvieron los procesos iniciados para las pruebas. No se
descargaron modelos ni se registraron ejecuciones de prueba en proyectos reales.
Se inspeccionaron capturas de Inicio y Hardware con la fuente Segoe UI.

## Límites

- Dispositivos vinculados, verificación en dos pasos y cierre de otras sesiones
  no tienen backend en esta aplicación; se muestran deshabilitados con explicación.
- El servidor actual no ofrece edición de perfil/foto ni cambio voluntario de
  contraseña mediante sesión remota. Esas acciones locales se deshabilitan en
  modo Servidor. Se conserva el cambio remoto obligatorio de contraseña temporal.
- Las APIs comerciales y los sensores SNMP/Modbus físicos se cubren con dobles
  de prueba y escenarios de fallo. No se verificaron contra cuentas comerciales
  o dispositivos físicos que requieran credenciales.
- Esta revisión no genera una nueva distribución ni publica una Release. El
  ejecutable existente en `dist/` conserva su versión hasta reconstruirlo.

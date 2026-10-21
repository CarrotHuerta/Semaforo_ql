# Semáforo IA portable

Extraiga el ZIP completo en una carpeta con permiso de escritura. Abra
`SemaforoIA.exe`. Conserve `_internal` y `portable.flag` junto a los tres EXE.
No basta con copiar un EXE. No necesita Python, pip, Git ni administrador.

En el primer inicio cree su cuenta administradora. Los datos se guardan en
`userdata`. Puede mover TODA la carpeta a otro equipo Windows 11 x64,
incluido un disco extraíble, con la aplicación cerrada. Una carpeta de solo
lectura produce un error y no cambia a AppData. Evite FAT32 si un archivo
supera su límite de 4 GB; no extraiga encima de una app abierta.

Para actualizar: cierre GUI, CLI y servidor; respalde `userdata`; extraiga el
ZIP nuevo en otra carpeta; copie `userdata` al lado de su nuevo `portable.flag`.
Conserve la carpeta anterior hasta verificar cuentas, historial y exportación.
Los ZIP oficiales nunca contienen `userdata` y no deben borrarlo.

La versión instalada utiliza AppData y puede coexistir con esta carpeta. Un
segundo portable en otra carpeta también tiene sus propios datos y bloqueo.

`SemaforoCLI.exe --version` muestra la versión.
`SemaforoCLI.exe diagnose` verifica persistencia, recursos y exportaciones
locales sin conectarse a servicios. El servidor opcional se inicia manualmente
con `SemaforoServer.exe`; no se instala como servicio.

Ollama, modelos, PostgreSQL y servidor MLflow no están incluidos. Configure sus
servicios explícitamente para utilizarlos. La aplicación no descarga modelos.

Las claves Fernet en `userdata/secrets` no dependen de DPAPI, usuario ni equipo.
Para conservar credenciales cifradas mueva también estas claves. Quien tenga la
carpeta y las claves podrá descifrar las credenciales: proteja el disco/carpeta.
Si faltan las claves, vuelva a introducir las credenciales en Ajustes; nunca
copie contraseñas en texto plano. Guarde sus respaldos bajo el mismo cuidado.

Las builds que contienen `DEVELOPMENT-UNSIGNED.txt` son de desarrollo sin firma
y no son releases de producción verificadas.

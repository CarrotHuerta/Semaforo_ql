# Componentes redistribuidos

La carpeta THIRD_PARTY contiene el inventario de versiones, los metadatos y los
archivos LICENSE/LICENCE/COPYING/NOTICE/COPYRIGHT de las distribuciones fijadas
en `packaging/requirements-windows.lock`, además de la licencia de Python.
No se reemplazan ni eliminan las firmas de DLL/PYD/EXE de terceros.

PySide6/Qt se distribuye bajo las opciones de licencia publicadas por Qt. Esta
distribución utiliza bibliotecas compartidas, no enlaza Qt estáticamente y no
impide sustituir sus DLL por versiones compatibles. No todos los módulos de Qt
tienen la misma licencia; consulte los textos copiados y las fuentes exactas de
Qt/PySide6 6.11.2 antes de redistribuir una variante con otros módulos.

- [Licencias de Qt](https://doc.qt.io/qt-6/licensing.html)
- [Fuentes y archivos oficiales de Qt](https://download.qt.io/archive/qt/6.11/)
- [Fuentes de PySide](https://code.qt.io/pyside/pyside-setup.git/)
- [Licencia de Python](https://docs.python.org/3.13/license.html)
- [Excepción de redistribución del bootloader de PyInstaller](https://pyinstaller.org/en/stable/license.html)
- [Redistribución de runtime MSVC](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)

Las DLL de runtime MSVC que recoge PyInstaller deben conservar los términos de
redistribución de Microsoft. No se incluye un instalador global de VC++ ni se
modifica Windows. El inventario nativo generado identifica exactamente los
binarios incluidos; no se afirma que todos tengan firma.

El código del proyecto no recibe una licencia nueva por este empaquetado.

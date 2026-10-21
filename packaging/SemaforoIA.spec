# Maintained Windows x64 multiprogram onedir; no onefile extraction at startup.
import json
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
import PySide6

root = Path(SPECPATH).parent
product = json.loads((root / 'product.json').read_text(encoding='utf-8'))
manifest = json.loads((root / 'packaging/distribution-files.json').read_text())
datas = [(str(root / name), str(Path(name).parent)) for name in manifest['files']]
datas += [(str(root / 'build/distribution/THIRD_PARTY'), 'THIRD_PARTY')]
datas += [(str(root / 'packaging/app.ico'), 'img')]
datas += collect_data_files('mlflow', include_py_files=False)
for package in ['mlflow-skinny', 'requests', 'cryptography', 'PySide6', 'matplotlib', 'openpyxl']:
    datas += copy_metadata(package, recursive=True)

common = dict(pathex=[str(root), str(root / 'export handler')], datas=datas,
    binaries=[(str(Path(PySide6.__file__).parent / name), '.') for name in
              ['msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_codecvt_ids.dll',
               'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll', 'vcomp140.dll']],
    hiddenimports=['eco', 'economia', 'inicio', 'config_loader',
                   'matplotlib.backends.backend_agg', 'plyer.platforms.win.notification',
                   'mlflow.tracking', 'psycopg2', 'pymodbus.client', 'pysnmp.hlapi.v3arch.asyncio'],
    hookspath=[], hooksconfig={'matplotlib': {'backends': ['Agg']}},
    runtime_hooks=[str(root / 'packaging/runtime_hook.py')],
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'torch', 'tensorflow',
              'sklearn', 'scipy', 'pandas', 'pyarrow', 'IPython', 'pytest'],
    noarchive=False)
analyses = []
executables = []
for script, name, console in [('desktop_entry.py', 'SemaforoIA', False),
                              ('cli_entry.py', 'SemaforoCLI', True),
                              ('server_entry.py', 'SemaforoServer', True)]:
    analysis = Analysis([str(root / script)], **common)
    analyses.append(analysis)
    executables.append(EXE(PYZ(analysis.pure), analysis.scripts, [], exclude_binaries=True,
        name=name, console=console, debug=False, strip=False, upx=False,
        icon=str(root / 'packaging/app.ico'), version=str(root / 'build/distribution/version-info.txt'),
        contents_directory='_internal'))
collection = COLLECT(*executables, *[a.binaries for a in analyses], *[a.datas for a in analyses],
                     strip=False, upx=False, name='SemaforoIA')

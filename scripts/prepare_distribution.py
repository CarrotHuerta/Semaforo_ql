"""Prepare version metadata, explicit resources and installed dependency notices."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    product = json.loads((ROOT / 'product.json').read_text(encoding='utf-8'))
    target = ROOT / 'build/distribution'
    target.mkdir(parents=True, exist_ok=True)
    version = tuple(map(int, product['version'].split('.'))) + (0,)
    text = f'''VSVersionInfo(ffi=FixedFileInfo(filevers={version!r}, prodvers={version!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('CompanyName', {product['publisher']!r}), StringStruct('ProductName', {product['name']!r}), StringStruct('FileDescription', {product['name']!r}), StringStruct('FileVersion', {product['version']!r}), StringStruct('ProductVersion', {product['version']!r})])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])'''
    (target / 'version-info.txt').write_text(text, encoding='utf-8')
    notices = target / 'THIRD_PARTY'
    notices.mkdir(exist_ok=True)
    inventory = []
    for line in (ROOT / 'packaging/requirements-windows.lock').read_text().splitlines():
        if not line or line.startswith(('#', ' ', '--')):
            continue
        package = line.split('==')[0]
        dist = metadata.distribution(package)
        entry = {'name': dist.metadata['Name'], 'version': dist.version,
                 'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', ''), 'files': []}
        for file in dist.files or []:
            if any(word in str(file).lower() for word in ('license', 'licence', 'copying', 'notice', 'copyright')):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    destination = notices / package / str(file).replace('..', '_parent_')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    entry['files'].append(str(destination.relative_to(notices)))
        (notices / f'{package}-METADATA.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
        inventory.append(entry)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python LICENSE.txt missing')
    shutil.copyfile(python_license, notices / 'Python-LICENSE.txt')
    shutil.copyfile(ROOT / 'docs/THIRD_PARTY.md', notices / 'README.md')
    (notices / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')


def validate_bundle(folder):
    folder = Path(folder)
    for name in ('SemaforoIA.exe', 'SemaforoCLI.exe', 'SemaforoServer.exe', '_internal/python313.dll',
                 '_internal/msvcp140.dll', '_internal/msvcp140_1.dll', '_internal/msvcp140_2.dll',
                 '_internal/vcruntime140.dll', '_internal/vcruntime140_1.dll',
                 '_internal/PySide6/plugins/platforms/qwindows.dll', '_internal/defaults/config.json',
                 '_internal/THIRD_PARTY/inventory.json', '_internal/img/app.ico'):
        if not (folder / name).is_file():
            raise ValueError(f'Missing distribution file: {name}')
    config = json.loads((folder / '_internal/defaults/config.json').read_text())
    if config.get('users') or config.get('default_user'):
        raise ValueError('Distribution contains preconfigured accounts')
    for path in folder.rglob('*'):
        if path.is_file() and (path.suffix.lower() in {'.sqlite3', '.bak', '.key', '.pfx', '.log'} or
                               any(part in {'secrets', 'userdata', 'backup', 'exports'} for part in path.parts)):
            raise ValueError(f'Forbidden runtime/personal file: {path}')
    for name in ('config.json', 'models.json', 'portable.flag'):
        if (folder / name).exists():
            raise ValueError(f'Base distribution is not pristine: {name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        validate_bundle(args.verify)
    else:
        prepare()

"""Audit PE imports; MSVC must be app-local even if installed on the build host."""
import argparse
from pathlib import Path
import os
import pefile


def audit(root):
    files = [path for path in root.rglob('*') if path.suffix.lower() in {'.exe', '.dll', '.pyd'}]
    names = {path.name.lower() for path in files}
    system = Path(os.environ['WINDIR']) / 'System32'
    missing = set()
    for path in files:
        pe = pefile.PE(str(path), fast_load=True)
        try:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            for item in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
                name = item.dll.decode('ascii').lower()
                if name in names or name.startswith(('api-ms-', 'ext-ms-')):
                    continue
                if name.startswith(('msvcp', 'vcruntime', 'concrt', 'vcomp')) or not (system / name).is_file():
                    missing.add(f'{path.relative_to(root)} -> {name}')
        finally:
            pe.close()
    if missing:
        raise SystemExit('Missing native dependencies:\n' + '\n'.join(sorted(missing)))
    print(f'PE imports audited: {len(files)} native binaries')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    audit(parser.parse_args().root)

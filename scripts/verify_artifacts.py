import argparse
import hashlib
import json
from pathlib import PurePosixPath
import zipfile


def verify(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError('Duplicate ZIP entries')
        for name in names:
            parts = PurePosixPath(name).parts
            if '..' in parts or name.startswith(('/', '\\')) or '\\' in name or ':' in name:
                raise ValueError('Unsafe ZIP path')
            if any(part in {'userdata', 'secrets', 'backup', 'exports'} for part in parts):
                raise ValueError('ZIP contains personal data')
        if 'SemaforoIA/portable.flag' not in names:
            raise ValueError('Portable marker missing')
        manifest = json.loads(archive.read('SemaforoIA/distribution-manifest.json'))
        actual = {name.removeprefix('SemaforoIA/'): hashlib.sha256(archive.read(name)).hexdigest()
                  for name in names if not name.endswith('/') and name != 'SemaforoIA/distribution-manifest.json'}
        if manifest != actual:
            raise ValueError('ZIP differs from the final signed bundle manifest')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('zip')
    verify(parser.parse_args().zip)

"""Hash every final bundle file; fail on additions, removals or modifications."""
import argparse
import hashlib
import json
from pathlib import Path


def inventory(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file() and path != root / 'distribution-manifest.json'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    target = args.root / 'distribution-manifest.json'
    actual = inventory(args.root)
    if args.verify:
        if json.loads(target.read_text(encoding='utf-8')) != actual:
            raise SystemExit('Distribution content differs from its final manifest')
    else:
        target.write_text(json.dumps(actual, indent=2), encoding='utf-8')

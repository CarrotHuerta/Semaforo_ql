"""Check installed requirements without importing heavy modules or contacting PyPI."""

from importlib import metadata
from pathlib import Path


def missing_requirements(requirements_path=None):
    from packaging.requirements import Requirement

    path = Path(requirements_path or Path(__file__).with_name("requirements.txt"))
    missing = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.partition("#")[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            missing.append(line)
            continue
        if installed not in requirement.specifier:
            missing.append(line)
    return missing


if __name__ == "__main__":
    try:
        missing = missing_requirements()
    except (ImportError, OSError, ValueError) as exc:
        print(f"Dependency check: {exc}")
        raise SystemExit(1)
    if missing:
        print("Dependencies to install: " + ", ".join(missing))
    raise SystemExit(bool(missing))

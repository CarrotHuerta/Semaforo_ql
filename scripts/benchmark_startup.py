"""Measure source startup in fresh processes, without network or user data writes.

Run with .venv/Scripts/python scripts/benchmark_startup.py --samples 5.
Use --project-root to compare another checkout under the same conditions.
"""

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch


def sample(project_root):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(project_root))
    started = time.perf_counter()
    import main
    imported = time.perf_counter()
    app = main.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as directory:
        config = {"users": [], "language": "es", "notifications_os": False}
        with patch.object(main, "writable_path", side_effect=lambda *parts: str(Path(directory).joinpath(*parts))), patch.object(
            main, "load_config", return_value=config
        ), patch.object(main.i18n, "load_saved_language", return_value="es"), patch.object(
            main.FinOpsView, "_refresh_exchange_rates"
        ):
            main.apply_stylesheet(app)
            login = main.LoginWindow()
            login.show()
            app.processEvents()
            login_ready = time.perf_counter()
            dashboard_start = time.perf_counter()
            dashboard = main.DashboardWindow({"username": "benchmark", "role": "Administrador"})
            dashboard.show()
            app.processEvents()
            dashboard_ready = time.perf_counter()
            dashboard.close()
            login.close()
    return {
        "import_ms": round((imported - started) * 1000, 2),
        "login_ready_ms": round((login_ready - started) * 1000, 2),
        "dashboard_ready_ms": round((dashboard_ready - dashboard_start) * 1000, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--sample", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sample:
        print(json.dumps(sample(args.project_root.resolve())))
        return
    if args.samples < 1:
        parser.error("--samples must be positive")
    samples = []
    for _ in range(args.samples):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--project-root", str(args.project_root.resolve()), "--sample"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        samples.append(json.loads(result.stdout))
    print(json.dumps({
        "samples": samples,
        "median_ms": {key: round(statistics.median(row[key] for row in samples), 2) for key in samples[0]},
    }, indent=2))


if __name__ == "__main__":
    main()

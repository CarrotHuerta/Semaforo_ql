"""Tests callable from the actual frozen executables on a target without Python."""
import json
from pathlib import Path
import tempfile
from contextlib import redirect_stdout
import io


def diagnose():
    from app_paths import data_root, is_portable, resource_path
    from app_version import VERSION
    from functional_core import LocalStore, Execution
    from esg_export import export_esg_pdf
    import importlib
    import sys
    root = data_root()
    with tempfile.TemporaryDirectory(dir=root) as directory:
        store = LocalStore(Path(directory) / "smoke.sqlite3")
        try:
            project = store.add_project("Prueba local")
            model = store.add_model(project, "Modelo")
            store.add_execution(Execution(model, "2026-01-01 00:00:00", 1, 2, .1, .2, 1000, "Verde"))
            assert len(store.list_history()) == 1
        finally:
            store.close()
        export_esg_pdf({"project_name": "Prueba", "generated_at": "2026-01-01", "execution_count": 1,
                        "cost": 1, "carbon": 2, "kwh": .1, "water": .2}, Path(directory) / "esg.pdf")
        for module in ("openpyxl", "cryptography.fernet", "matplotlib.backends.backend_agg", "psycopg2", "pymodbus", "pysnmp", "mlflow.tracking"):
            importlib.import_module(module)
        sys.path.insert(0, resource_path("export handler"))
        # Exercise all available report formats without any network or GUI.
        from export_handler import _apply_report_data
        for fmt in ("pdf", "json", "csv", "xlsx"):
            with redirect_stdout(io.StringIO()):
                _apply_report_data("inicio", {"chart_values": [0, 0], "chart_labels": ["CPU", "GPU"]},
                                   str(Path(directory) / ("report." + fmt)), fmt, "es")
    return {"version": VERSION, "portable": is_portable(), "data_root": str(root), "local_checks": "passed"}


def desktop_smoke(argv):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import main
    output = Path(argv[argv.index("--smoke-report") + 1])
    app = QApplication([])
    window = main.LoginWindow()
    window.show()
    app.processEvents()
    result = diagnose()
    result["login_visible"] = window.isVisible()
    output.write_text(json.dumps(result), encoding="utf-8")
    QTimer.singleShot(50, app.quit)
    return app.exec()

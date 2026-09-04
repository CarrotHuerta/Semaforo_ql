"""Headless command-line entrypoint for Semaforo IA."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from esg_export import EsgExportError, export_esg_pdf
from functional_core import (
    DataIntegrityError,
    LocalStore,
    ValidationError,
    calculate_execution,
    export_records,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semaforo-cli", description="Motor headless de Semaforo IA")
    parser.add_argument("--database", default="semaforo.sqlite3", help="Ruta de la base SQLite")
    commands = parser.add_subparsers(dest="command", required=True)

    calculate = commands.add_parser("calculate", help="Calcula una ejecucion sin iniciar PySide6")
    calculate.add_argument("--model-id", type=int, required=True)
    for name in ("hourly-cost", "hours", "tdp-watts", "pue", "grid-factor", "wue", "wsi", "cost-limit", "carbon-limit"):
        calculate.add_argument(f"--{name}", type=float, required=True)
    calculate.add_argument("--currency", default="USD")
    calculate.add_argument("--persist", action="store_true")

    history = commands.add_parser("history", help="Lista el historial en JSON")
    history.add_argument("--project-id", type=int)
    history.add_argument("--model-id", type=int)

    export = commands.add_parser("export", help="Exporta historial a JSON o CSV")
    export.add_argument("--output", required=True)
    export.add_argument("--project-id", type=int)

    restore = commands.add_parser("restore", help="Restaura un backup SQLite validado")
    restore.add_argument("--source", required=True)

    esg = commands.add_parser("esg", help="Genera el certificado ESG de una campana completa")
    esg.add_argument("--project-id", type=int, required=True)
    esg.add_argument("--output", required=True)
    esg.add_argument("--close", action="store_true", help="Cierra primero la campana si todos sus modelos estan completos")
    return parser


def _open_store(path: str) -> LocalStore:
    return LocalStore(Path(path))


def run(args: argparse.Namespace) -> dict | list | None:
    store = _open_store(args.database)
    try:
        if args.command == "calculate":
            execution, badge = calculate_execution(
                model_id=args.model_id,
                hourly_cost=args.hourly_cost,
                hours=args.hours,
                currency=args.currency,
                tdp_watts=args.tdp_watts,
                pue=args.pue,
                grid_factor=args.grid_factor,
                wue=args.wue,
                wsi=args.wsi,
                cost_limit=args.cost_limit,
                carbon_limit=args.carbon_limit,
            )
            if args.persist:
                execution_id = store.add_execution(execution)
            else:
                execution_id = None
            return {"execution": asdict(execution), "badge": badge, "execution_id": execution_id}
        if args.command == "history":
            return [dict(row) for row in store.list_history(model_id=args.model_id, project_id=args.project_id)]
        if args.command == "export":
            rows = [dict(row) for row in store.list_history(project_id=args.project_id)]
            export_records(rows, args.output)
            return {"output": str(Path(args.output).resolve()), "records": len(rows)}
        if args.command == "restore":
            store.restore(args.source)
            return {"restored": str(Path(args.source).resolve())}
        if args.command == "esg":
            if args.close:
                store.close_project(args.project_id)
            data = store.consolidate_esg(args.project_id)
            export_esg_pdf(data, args.output)
            return {"output": str(Path(args.output).resolve()), "campaign": data}
        raise ValidationError("Comando no soportado.")
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(build_parser().parse_args(argv))
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValidationError, DataIntegrityError, EsgExportError, PermissionError, sqlite3.DatabaseError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except MemoryError:
        print("Error: memoria insuficiente para completar la operacion.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

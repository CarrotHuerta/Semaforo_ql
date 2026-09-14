"""ISO 14064-oriented ESG campaign certificate export."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class EsgExportError(RuntimeError):
    pass


def export_esg_pdf(data: dict[str, Any], destination: str | os.PathLike[str]) -> None:
    required = {"project_name", "generated_at", "execution_count", "cost", "carbon", "kwh", "water"}
    if not required.issubset(data) or int(data["execution_count"]) <= 0:
        raise EsgExportError("El consolidado ESG esta incompleto.")
    target = Path(destination)
    if target.suffix.lower() != ".pdf":
        raise EsgExportError("El certificado ESG debe exportarse como PDF.")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".pdf", dir=target.parent)
    os.close(descriptor)
    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_title(f"Certificado ESG - {data['project_name']}")
        pdf.set_author("Semaforo IA")
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, "Semaforo IA - Consolidado ESG", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(
            0, 6,
            "Declaracion cuantitativa orientada a los principios de ISO 14064-1. "
            "Este documento no sustituye una verificacion independiente ni constituye certificacion ISO.",
        )
        pdf.ln(4)
        rows = [
            ("Campana", data["project_name"]),
            ("Fecha UTC", data["generated_at"]),
            ("Ejecuciones", int(data["execution_count"])),
            ("Energia", f"{float(data['kwh']):.4f} kWh"),
            ("Emisiones", f"{float(data['carbon']):.4f} gCO2eq"),
            ("Agua", f"{float(data['water']):.4f} L"),
            ("Costo", f"USD {float(data['cost']):.2f}"),
        ]
        for label, value in rows:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(45, 8, str(label))
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 8, str(value), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(0, 5, "Limites: emisiones operacionales y consumo hidrico registrados por Semaforo IA para las ejecuciones asociadas a la campana.")
        pdf.output(temporary_name)
        os.replace(temporary_name, target)
    except MemoryError as exc:
        raise EsgExportError("No hay memoria suficiente para generar el certificado ESG.") from exc
    except (OSError, PermissionError) as exc:
        raise EsgExportError(f"No se pudo escribir el certificado ESG: {exc}") from exc
    except ImportError as exc:
        raise EsgExportError("La dependencia fpdf2 no esta instalada.") from exc
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass

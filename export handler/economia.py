import os
import sys
import argparse
from datetime import datetime
import matplotlib.pyplot as plt
from config_loader import export_json_report, load_config

try:
    from fpdf import FPDF
    if not hasattr(FPDF, 'polygon'):
        print("\n[!] ERROR DE LIBRERÍA: Tienes instalada la versión antigua 'fpdf'.")
        print("El diseño del PDF requiere la versión moderna 'fpdf2'.")
        print("Por favor, ejecuta estos comandos en tu terminal de VS Code para solucionarlo:\n")
        print("    pip uninstall fpdf -y")
        print("    pip install fpdf2\n")
        sys.exit(1)
except ImportError:
    print("Falta instalar fpdf2. Ejecuta: pip install fpdf2")
    sys.exit(1)

SHARED, REPORT, COLORS = load_config("economia")


class SemaforoPDF(FPDF):
    def add_gradient_background(self):
        """Dibuja un gradiente suave de celeste a blanco desde la mitad hacia abajo."""
        for i in range(150):
            ratio = i / 149
            r = int(255 - (255 - 224) * ratio)
            g = int(255 - (255 - 242) * ratio)
            b = int(255 - (255 - 254) * ratio)
            self.set_fill_color(r, g, b)
            self.rect(0, 147 + i, 210, 1.5, style='F')

    def draw_orange_cat(self, x, y):
        """Dibuja un avatar de gato más definido para el encabezado."""
        orange = COLORS['logo_orange']
        dark_orange = COLORS['logo_orange_dark']
        black = COLORS['logo_black']
        pink = COLORS['logo_pink']
        cream = COLORS['logo_cream']

        self.set_fill_color(*dark_orange)
        self.ellipse(x + 2, y + 8, 8, 7, style='F')
        self.set_fill_color(*orange)
        self.polygon([(x + 1, y + 5), (x + 2.5, y), (x + 5.5, y + 3)], style='F')
        self.polygon([(x + 6.5, y + 3), (x + 9.5, y), (x + 11, y + 5)], style='F')
        self.set_fill_color(*cream)
        self.polygon([(x + 2.2, y + 3.8), (x + 2.8, y + 1.8), (x + 4.5, y + 3.3)], style='F')
        self.polygon([(x + 7.5, y + 3.3), (x + 9.2, y + 1.8), (x + 9.8, y + 3.8)], style='F')
        self.set_fill_color(*orange)
        self.ellipse(x + 1, y + 2, 10, 10, style='F')
        self.set_fill_color(*black)
        self.ellipse(x + 3.1, y + 5.2, 1.4, 1.8, style='F')
        self.ellipse(x + 7.5, y + 5.2, 1.4, 1.8, style='F')
        self.set_fill_color(*COLORS['white'])
        self.ellipse(x + 3.35, y + 5.35, 0.4, 0.5, style='F')
        self.ellipse(x + 7.75, y + 5.35, 0.4, 0.5, style='F')
        self.set_fill_color(*pink)
        self.polygon([(x + 5.3, y + 7.2), (x + 6.7, y + 7.2), (x + 6, y + 8.2)], style='F')
        self.set_draw_color(*black)
        self.set_line_width(0.2)
        self.line(x + 5.8, y + 8.1, x + 5.8, y + 8.8)
        self.line(x + 5.8, y + 8.8, x + 4.7, y + 8.5)
        self.line(x + 6.2, y + 8.8, x + 7.3, y + 8.5)
        self.line(x + 2.3, y + 7.5, x - 0.5, y + 7)
        self.line(x + 2.3, y + 8.5, x - 0.5, y + 9)
        self.line(x + 9.7, y + 7.5, x + 12.5, y + 7)
        self.line(x + 9.7, y + 8.5, x + 12.5, y + 9)

    def draw_rounded_box(self, x, y, w, h, radius=3):
        self.set_fill_color(*COLORS['white'])
        self.set_draw_color(*COLORS['gray_200'])
        self.set_line_width(0.5)
        self.rect(x, y, w, h, style='FD', round_corners=True, corner_radius=radius)


def generate_charts():
    """Genera el gráfico de distribución mensual de costos."""
    fig, ax = plt.subplots(
        figsize=SHARED['chart_figure_size'], dpi=SHARED['chart_dpi'])
    wedges, _ = ax.pie(
        REPORT['chart_values'],
        colors=REPORT['chart_colors'],
        startangle=90,
        wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2)
    )
    ax.set_aspect('equal')
    ax.set_position(SHARED['chart_axes_position'])
    fig.legend(
        wedges,
        REPORT['chart_labels'],
        loc='lower center',
        bbox_to_anchor=(0.5, SHARED['chart_legend_y']),
        frameon=False,
        fontsize=7, ncol=1, handlelength=1.2, handletextpad=0.5,
        borderaxespad=0
    )
    plt.subplots_adjust(left=0.03, right=0.97, top=0.98,
                        bottom=SHARED['chart_bottom_margin'])
    plt.savefig(REPORT['chart_file'], transparent=True)
    plt.close(fig)


def create_pdf_report(filename=None, export_format="both"):
    if export_format not in {"pdf", "json", "both"}:
        raise ValueError("export_format debe ser 'pdf', 'json' o 'both'")

    filename = filename or REPORT['filename']
    if export_format == "json":
        json_filename = export_json_report(filename, "economia", SHARED, REPORT)
        print(f"¡Los datos se exportaron como: {json_filename}!")
        return

    generate_charts()

    pdf = SemaforoPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    pdf.add_gradient_background()
    pdf.draw_orange_cat(*SHARED['logo_position'])

    pdf.set_font("helvetica", "B", 20)
    pdf.set_text_color(*COLORS['gray_800'])
    pdf.set_xy(32, 13)
    pdf.cell(100, 10, SHARED['product_name'])

    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(32, 21)
    pdf.cell(100, 5, REPORT['subtitle'])

    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_800'])
    pdf.set_xy(110, 15)
    pdf.cell(85, 5, f"Exportado por: {SHARED['exported_by']}", align="R")

    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(110, 20)
    current_date = datetime.now().strftime(SHARED['date_format'])
    pdf.cell(85, 5, f"Fecha de exportación: {current_date}", align="R")

    pdf.set_draw_color(*COLORS['cyan_500'])
    pdf.set_line_width(0.8)
    pdf.line(15, 30, 195, 30)

    box_w = 87.5
    box_h = 25
    kpis = [(x, y, title, value, unit, COLORS[color])
            for x, y, title, value, unit, color in REPORT['kpis']]

    for x, y, title, value, unit, unit_color in kpis:
        pdf.draw_rounded_box(x, y, box_w, box_h)
        pdf.set_font("helvetica", "B", 8)
        pdf.set_text_color(*COLORS['gray_500'])
        pdf.set_xy(x + 5, y + 4)
        pdf.cell(box_w - 10, 5, title)

        pdf.set_font("helvetica", "B", 16)
        pdf.set_text_color(*COLORS['gray_800'])
        pdf.set_xy(x + 5, y + 11)
        value_width = pdf.get_string_width(value) + 2
        pdf.cell(value_width, 8, value)

        pdf.set_font("helvetica", "B", 9)
        pdf.set_text_color(*unit_color)
        pdf.set_xy(x + 5 + value_width, y + 13)
        pdf.cell(25, 5, unit)

    pdf.draw_rounded_box(15, 98, box_w, 65)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(15, 102)
    pdf.cell(box_w, 5, REPORT['chart_title'], align="C")
    chart_x, chart_y = SHARED['chart_image_position']
    pdf.image(REPORT['chart_file'], x=chart_x, y=chart_y,
              w=SHARED['chart_image_width'])

    pdf.draw_rounded_box(107.5, 98, box_w, 65)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(107.5, 102)
    pdf.cell(box_w, 5, REPORT['progress_title'], align="C")

    bar_x = 115
    bar_y = 125
    bar_w = 72.5
    bar_h = 8
    pdf.set_font("helvetica", "B", 8)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(bar_x, bar_y - 6)
    pdf.cell(20, 5, "0%")
    pdf.set_text_color(*COLORS['cyan_600'])
    pdf.set_xy(bar_x + bar_w / 2 - 10, bar_y - 6)
    pdf.cell(20, 5, f"{REPORT['progress']}%", align="C")
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(bar_x + bar_w - 20, bar_y - 6)
    pdf.cell(20, 5, "100%", align="R")

    pdf.set_fill_color(*COLORS['gray_200'])
    pdf.rect(bar_x, bar_y, bar_w, bar_h, style='F', round_corners=True, corner_radius=4)
    pdf.set_fill_color(*COLORS['cyan_100'])
    pdf.rect(bar_x, bar_y, bar_w * REPORT['progress'] / 100, bar_h, style='F', round_corners=True, corner_radius=4)

    pdf.set_fill_color(*COLORS['cyan_500'])
    pdf.rect(125, 142, 55, 7, style='F', round_corners=True, corner_radius=3.5)
    pdf.set_font("helvetica", "B", 8)
    pdf.set_text_color(*COLORS['cyan_600'])
    pdf.set_xy(125, 143)
    pdf.cell(55, 5, REPORT['badge'], align="C")

    pdf.draw_rounded_box(15, 168, box_w, 75)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(20, 172)
    pdf.cell(box_w - 10, 5, REPORT['details_title'])
    pdf.set_draw_color(*COLORS['gray_200'])
    pdf.line(20, 179, 15 + box_w - 5, 179)

    detalles = [(key, value, COLORS[color]) for key, value, color in REPORT['details']]
    y_offset = 182
    for key, value, value_color in detalles:
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(*COLORS['gray_500'])
        pdf.set_xy(20, y_offset)
        pdf.cell(40, 5, key)
        pdf.set_font("helvetica", "B", 9)
        pdf.set_text_color(*value_color)
        pdf.set_xy(60, y_offset)
        pdf.cell(37, 5, value, align="R")
        pdf.set_draw_color(*COLORS['gray_100'])
        pdf.line(20, y_offset + 6, 15 + box_w - 5, y_offset + 6)
        y_offset += 9

    pdf.draw_rounded_box(107.5, 168, box_w, 75)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(112.5, 172)
    pdf.cell(box_w - 10, 5, "Registro de Actividad")
    pdf.set_draw_color(*COLORS['gray_200'])
    pdf.line(112.5, 179, 107.5 + box_w - 5, 179)

    logs = [(text, COLORS[color]) for text, color in REPORT['logs']]
    y_offset = 183
    for text, dot_color in logs:
        pdf.set_fill_color(*dot_color)
        pdf.ellipse(112.5, y_offset + 1.5, 2.5, 2.5, style='F')
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(*COLORS['gray_700'])
        pdf.set_xy(117.5, y_offset)
        pdf.multi_cell(box_w - 15, 4, text)
        y_offset += 10

    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(15, 280)
    pdf.cell(180, 5, SHARED['footer'], align="C")

    pdf.output(filename)
    json_filename = None
    if export_format == "both":
        json_filename = export_json_report(filename, "economia", SHARED, REPORT)
    if os.path.exists(REPORT['chart_file']):
        os.remove(REPORT['chart_file'])

    print(f"¡El informe se ha exportado exitosamente como: {filename}!")
    if json_filename:
        print(f"¡Los datos también se exportaron como: {json_filename}!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exporta el informe económico")
    parser.add_argument(
        "--format", choices=("pdf", "json", "both"), default="both",
        help="Formato de exportación (por defecto: both)"
    )
    args = parser.parse_args()
    create_pdf_report(export_format=args.format)

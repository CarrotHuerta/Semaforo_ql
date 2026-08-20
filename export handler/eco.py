import os
import sys
import argparse
from datetime import datetime
import matplotlib.pyplot as plt
from config_loader import export_json_report, load_config

try:
    from fpdf import FPDF
    # Verificamos si es fpdf2 (que soporta polígonos) y no la versión antigua
    if not hasattr(FPDF, 'polygon'):
        print("\n[!] ERROR DE LIBRERÍA: Tienes instalada la versión antigua 'fpdf'.")
        print("El diseño del PDF requiere la versión moderna 'fpdf2'.")
        print("Por favor, ejecuta estos comandos en tu terminal de VS Code para solucionarlo:\n")
        print("    pip uninstall fpdf -y")
        print("    pip install fpdf2\n")
        raise ImportError("Falta instalar fpdf2 o está instalada la versión antigua")
except ImportError:
    print("Falta instalar fpdf2. Ejecuta: pip install fpdf2")
    raise ImportError("Falta instalar fpdf2 o está instalada la versión antigua")

SHARED, REPORT, COLORS = load_config("eco")

class SemaforoPDF(FPDF):
    def add_gradient_background(self):
        """Dibuja un gradiente suave de verde a blanco desde la mitad hacia abajo."""
        # A4 = 210mm ancho x 297mm alto. La mitad es ~148mm
        for i in range(150):
            ratio = i / 149
            # Interpolar entre Blanco (255,255,255) y Verde Suave (209,250,229)
            r = int(255 - (255 - 209) * ratio)
            g = int(255 - (255 - 250) * ratio)
            b = int(255 - (255 - 229) * ratio)
            
            self.set_fill_color(r, g, b)
            # Dibujamos líneas horizontales rectangulares muy finas para simular el degradado
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
        """Dibuja una caja blanca con bordes redondeados."""
        self.set_fill_color(*COLORS['white'])
        self.set_draw_color(*COLORS['gray_200'])
        self.set_line_width(0.5)
        self.rect(x, y, w, h, style='FD', round_corners=True, corner_radius=radius)

def generate_charts():
    # Gráfico de Dona
    fig, ax = plt.subplots(
        figsize=SHARED['chart_figure_size'], dpi=SHARED['chart_dpi'])
    wedges, texts = ax.pie(
        REPORT['chart_values'],
        colors=REPORT['chart_colors'],
        startangle=90,
        wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2)
    )
    ax.set_aspect('equal')
    ax.set_position(SHARED['chart_axes_position'])
    
    fig.legend(wedges, REPORT['chart_labels'],
               loc='lower center',
               bbox_to_anchor=(0.5, SHARED['chart_legend_y']),
               frameon=False, fontsize=7, ncol=1,
               handlelength=1.2, handletextpad=0.5, borderaxespad=0)

    plt.subplots_adjust(left=0.03, right=0.97, top=0.98,
                        bottom=SHARED['chart_bottom_margin'])
    plt.savefig(REPORT['chart_file'], transparent=True)
    plt.close()

def create_pdf_report(filename=None, export_format="both"):
    if export_format not in {"pdf", "json", "both"}:
        raise ValueError("export_format debe ser 'pdf', 'json' o 'both'")

    filename = filename or REPORT['filename']

    if export_format == "json":
        json_filename = export_json_report(filename, "eco", SHARED, REPORT)
        print(f"¡Los datos se exportaron como: {json_filename}!")
        return

    # 1. Generar gráficos
    generate_charts()
    
    pdf = SemaforoPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    # Fondo degradado
    pdf.add_gradient_background()

    # Gatito naranja chiquito
    pdf.draw_orange_cat(*SHARED['logo_position'])

    # Título principal
    pdf.set_font("helvetica", "B", 20)
    pdf.set_text_color(*COLORS['gray_800'])
    pdf.set_xy(32, 13)
    pdf.cell(100, 10, SHARED['product_name'])
    
    # Subtítulo
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(32, 21)
    pdf.cell(100, 5, REPORT['subtitle'])
    
    # Textos de la derecha (Fecha y Autor)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_800'])
    pdf.set_xy(110, 15)
    pdf.cell(85, 5, f"Exportado por: {SHARED['exported_by']}", align="R")
    
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(110, 20)
    current_date = datetime.now().strftime(SHARED['date_format'])
    pdf.cell(85, 5, f"Fecha de exportación: {current_date}", align="R")

    # Línea separadora del encabezado
    pdf.set_draw_color(*COLORS['emerald_500'])
    pdf.set_line_width(0.8)
    pdf.line(15, 30, 195, 30)

    # --- KPIs (TARJETAS SUPERIORES) ---
    kpis_raw = REPORT['kpis']
    num_kpis = len(kpis_raw)

    # Calculate box width dynamically
    # Margins: 15 left, 15 right -> 180 total width
    # Spacing between boxes: 5
    # width = (180 - (num_kpis - 1) * 5) / num_kpis
    box_w = (180 - (num_kpis - 1) * 5) / num_kpis
    box_h = 25
    
    # Recalculate X positions based on index instead of using the hardcoded ones
    kpis = []
    for i, (old_x, y, title, value, unit, color) in enumerate(kpis_raw):
        new_x = 15 + i * (box_w + 5)
        kpis.append((new_x, y, title, value, unit, COLORS[color]))

    for kpi in kpis:
        x, y, title, val, unit, unit_color = kpi
        val = str(val)
        unit = str(unit)
        pdf.draw_rounded_box(x, y, box_w, box_h)

        compact_mode = num_kpis >= 4
        title_font_size = 7 if compact_mode else 8
        value_font_size = 14 if compact_mode else 24
        unit_font_size = 8 if compact_mode else 12
        value_y = y + (12 if compact_mode else 10)
        unit_y = y + (16 if compact_mode else 13)
        
        # Título KPI
        pdf.set_font("helvetica", "B", title_font_size)
        pdf.set_text_color(*COLORS['gray_500'])
        pdf.set_xy(x + 5, y + 4)
        pdf.cell(box_w - 10, 5, title)
        
        # Valor KPI
        pdf.set_font("helvetica", "B", value_font_size)
        pdf.set_text_color(*COLORS['gray_800'])
        pdf.set_xy(x + 5, value_y)
        
        # Ajuste dinámico de ancho para poner la unidad pegada
        val_width = pdf.get_string_width(val) + 2
        pdf.cell(val_width, 10, val)
        
        # Unidad KPI
        pdf.set_font("helvetica", "B", unit_font_size)
        pdf.set_text_color(*unit_color)
        pdf.set_xy(x + 5 + val_width, unit_y)
        pdf.cell(max(12, box_w * 0.3), 5, unit)

    # --- SECCIÓN GRÁFICOS ---


    fixed_box_w = 87.5
    # Caja Dona
    pdf.draw_rounded_box(15, 98, fixed_box_w, 65)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(15, 102)
    pdf.cell(fixed_box_w, 5, REPORT['chart_title'], align="C")
    # Insertar imagen centrada y con margen para evitar superposición con el título.
    _, configured_chart_y = SHARED.get('chart_image_position', [15, 75])
    chart_w = min(SHARED.get('chart_image_width', 75), fixed_box_w - 16)
    chart_x = 15 + (fixed_box_w - chart_w) / 2
    chart_y = max(108, configured_chart_y)
    pdf.image(REPORT['chart_file'], x=chart_x, y=chart_y, w=chart_w)

    # Caja Barra Límite
    pdf.draw_rounded_box(107.5, 98, fixed_box_w, 65)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(107.5, 102)
    pdf.cell(fixed_box_w, 5, REPORT['progress_title'], align="C")
    
    # Barra de progreso nativa (FPDF)
    bar_x = 115
    bar_y = 125
    bar_w = 72.5
    bar_h = 8
    
    pdf.set_font("helvetica", "B", 8)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(bar_x, bar_y - 6)
    pdf.cell(20, 5, "0%")
    
    pdf.set_text_color(*COLORS['emerald_600'])
    pdf.set_xy(bar_x + bar_w/2 - 10, bar_y - 6)
    pdf.cell(20, 5, f"{REPORT['progress']}%", align="C")
    
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(bar_x + bar_w - 20, bar_y - 6)
    pdf.cell(20, 5, "100%", align="R")

    # Fondo gris de la barra
    pdf.set_fill_color(*COLORS['gray_200'])
    pdf.rect(bar_x, bar_y, bar_w, bar_h, style='F', round_corners=True, corner_radius=4)
    
    # Relleno verde de la barra (45%)
    pdf.set_fill_color(*COLORS['emerald_500'])
    pdf.rect(bar_x, bar_y, bar_w * REPORT['progress'] / 100, bar_h, style='F', round_corners=True, corner_radius=4)

    # Insignia (Badge) debajo
    pdf.set_fill_color(*COLORS['emerald_100'])
    pdf.rect(125, 142, 55, 7, style='F', round_corners=True, corner_radius=3.5)
    pdf.set_font("helvetica", "B", 8)
    pdf.set_text_color(5, 150, 105) # emerald-600
    pdf.set_xy(125, 143)
    pdf.cell(55, 5, REPORT['badge'], align="C")

    # --- SECCIÓN DETALLES Y LOGS ---
    # Detalles
    pdf.draw_rounded_box(15, 168, fixed_box_w, 75)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(20, 172)
    pdf.cell(fixed_box_w - 10, 5, REPORT['details_title'])
    
    # Linea separadora
    pdf.set_draw_color(*COLORS['gray_200'])
    pdf.line(20, 179, 15 + fixed_box_w - 5, 179)

    detalles = [(key, value, COLORS[color]) for key, value, color in REPORT['details']]

    y_offset = 182
    for key, val, val_color in detalles:
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(*COLORS['gray_500'])
        pdf.set_xy(20, y_offset)
        pdf.cell(40, 5, key)
        
        pdf.set_font("helvetica", "B", 9)
        pdf.set_text_color(*val_color)
        pdf.set_xy(60, y_offset)
        pdf.cell(37, 5, val, align="R")
        
        pdf.set_draw_color(*COLORS['gray_100'])
        pdf.line(20, y_offset + 6, 15 + fixed_box_w - 5, y_offset + 6)
        y_offset += 9

    # Log de Actividad
    pdf.draw_rounded_box(107.5, 168, fixed_box_w, 75)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*COLORS['gray_700'])
    pdf.set_xy(112.5, 172)
    pdf.cell(fixed_box_w - 10, 5, "Registro de Actividad")
    
    pdf.set_draw_color(*COLORS['gray_200'])
    pdf.line(112.5, 179, 107.5 + fixed_box_w - 5, 179)

    logs = [(text, COLORS[color]) for text, color in REPORT['logs']]

    y_offset = 183
    logs_bottom = 168 + 75 - 4
    for text, dot_color in logs:
        if y_offset >= logs_bottom:
            break

        # Punto de viñeta
        pdf.set_fill_color(*dot_color)
        pdf.ellipse(112.5, y_offset + 1.5, 2.5, 2.5, style='F')
        
        # Texto del log
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(*COLORS['gray_700'])
        pdf.set_xy(117.5, y_offset)
        start_y = y_offset
        pdf.multi_cell(fixed_box_w - 15, 3.8, text)
        consumed_h = pdf.get_y() - start_y
        y_offset += max(7, consumed_h + 1.5)

    # --- PIE DE PÁGINA ---
    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(*COLORS['gray_500'])
    pdf.set_xy(15, 280)
    pdf.cell(180, 5, SHARED['footer'], align="C")

    # 3. Guardar el PDF
    pdf.output(filename)
    json_filename = None
    if export_format == "both":
        json_filename = export_json_report(filename, "eco", SHARED, REPORT)
    
    # 4. Limpiar imagen temporal
    if os.path.exists(REPORT['chart_file']):
        os.remove(REPORT['chart_file'])
        
    print(f"¡El informe se ha exportado exitosamente como: {filename}!")
    if json_filename:
        print(f"¡Los datos también se exportaron como: {json_filename}!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exporta el informe ambiental")
    parser.add_argument(
        "--format", choices=("pdf", "json", "both"), default="both",
        help="Formato de exportación (por defecto: both)"
    )
    args = parser.parse_args()
    create_pdf_report(export_format=args.format)

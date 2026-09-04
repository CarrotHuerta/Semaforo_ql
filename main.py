import csv
import json
import math
import multiprocessing
import os
import re
import shutil
import sys
import threading
from html import escape as html_escape
from difflib import SequenceMatcher
from PySide6.QtCore import QDateTime, QDir, QEvent, QLockFile, QObject, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QAbstractScrollArea,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QCheckBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QMessageBox,
    QInputDialog,
)

from hardware_info import get_hardware_info
import i18n
from i18n import t
from app_paths import resource_path, writable_path
from functional_core import bootstrap_store, calculate_carbon, compare_models, export_records, green_score, import_records, rightsizing, semaphore_level, sensor_reading, validate_thresholds
from functional_core import classify_cpu_tier
from functional_core import convert_clp, fetch_exchange_rates, verify_security_answer
from functional_core import hash_password, validate_password, ValidationError
from functional_core import ApiKeyError, decrypt_api_key, encrypt_api_key, mask_api_key
from functional_core import calculate_energy, Execution, utc_iso


def make_label(text, object_name=None, alignment=Qt.AlignLeft):
    label = QLabel(text)
    if object_name:
        label.setObjectName(object_name)
    label.setAlignment(alignment | Qt.AlignVCenter)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return label


def load_config():
    config_path = writable_path("config.json")
    data = {
        "default_user": "nacha",
        "server_ip": "127.0.0.1",
        "server_port": 6767,
        "language": "es",
        "notifications_os": True,
        "users": [
            {
                "username": "nacha",
                "display_name": "Nacha",
                "role": "Administrador",
                "profile_photo": "img/nacha.png",
                "password_hash": "pbkdf2_sha256$260000$c37fe72f5445644395a019b205ee555d$c710c08721d36a2a6d6320a44d2c090ff6d45a9b099bceb05b863807efa7258d",
                "security_questions": [
                    {
                        "question": "Nombre de su mascota",
                        "answer_hash": "pbkdf2_sha256$260000$3dc1d0a00915fd901ae969f80da3ab56$666a99eb6cde4e9ca34b4739274edf604aee0ce55a19107e50445e79168d0758",
                    },
                    {
                        "question": "Nombre y Apellido",
                        "answer_hash": "pbkdf2_sha256$260000$1fcc8297118b9ccbd8567b748e13569e$51d0dfe7d18137c7cd57cbc71e2c93d196b0f8a7af1f60e559ecd9119962fec7",
                    },
                    {
                        "question": "Jefe del equipo",
                        "answer_hash": "pbkdf2_sha256$260000$fbe1f62806d5e91b2463fab820e180fb$cb043f4ddf3a51cd73f8514a54c49f59e893f0f5315cbe2ea5ac90d58dc9035f",
                    },
                ],
            },
            {
                "username": "maxine",
                "display_name": "Maxine",
                "role": "Usuario",
                "profile_photo": "img/maxine.jpg",
                "password_hash": "pbkdf2_sha256$260000$ac95afa719aaacd1f7c819b68936f308$74ba6a1be746a1322728cc890b406a339a0bf6560e0b200a46d8e2f6b5296d93",
            },
        ],
    }

    if not os.path.isfile(config_path):
        return data

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return data

    for key, value in config.items():
        if key != "users":
            data[key] = value

    users = []
    raw_users = config.get("users")
    if isinstance(raw_users, list):
        for entry in raw_users:
            if not isinstance(entry, dict):
                continue
            username = entry.get("username", "").strip()
            if not username:
                continue
            security_questions = []
            raw_questions = entry.get("security_questions")
            if isinstance(raw_questions, list):
                for question_entry in raw_questions:
                    if not isinstance(question_entry, dict):
                        continue
                    question_text = str(question_entry.get("question", "")).strip()
                    answer_hash = str(question_entry.get("answer_hash", "")).strip()
                    if question_text and answer_hash:
                        security_questions.append({"question": question_text, "answer_hash": answer_hash})
            users.append(
                {
                    "username": username,
                    "display_name": entry.get("display_name", username).strip() or username,
                    "role": entry.get("role", "Usuario").strip() or "Usuario",
                    "profile_photo": entry.get("profile_photo", "").strip(),
                    "password_hash": entry.get("password_hash", ""),
                    "security_questions": security_questions,
                }
            )
    else:
        legacy_name = str(config.get("user_name", "")).strip()
        legacy_role = str(config.get("user_role", "")).strip() or "Usuario"
        legacy_photo = str(config.get("profile_photo", "")).strip()
        if legacy_name:
            users.append(
                {
                    "username": legacy_name.lower(),
                    "display_name": legacy_name,
                    "role": legacy_role,
                    "profile_photo": legacy_photo,
                    "password": "",
                }
            )

    if users:
        data["users"] = users

    for key in ("thresholds", "local_metrics"):
        if isinstance(config.get(key), dict):
            data[key] = config[key]

    default_user = str(config.get("default_user", "")).strip()
    if default_user:
        data["default_user"] = default_user

    for key in ("server_ip", "server_port", "language", "notifications_os"):
        if key in config:
            data[key] = config[key]

    return data


def load_csv_rows(filename):
    data_path = resource_path("data", filename)
    if not os.path.isfile(data_path):
        return []
    try:
        import csv
        with open(data_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = []
            for row in reader:
                cleaned = {}
                for key, value in row.items():
                    cleaned[key] = value.strip() if isinstance(value, str) else value
                rows.append(cleaned)
            return rows
    except OSError:
        return []


def load_model_records():
    """Load offline models and merge user imports, excluding inactive records."""
    records = load_csv_rows("modelos_ia.csv")
    model_file = writable_path("models.json")
    if os.path.isfile(model_file):
        try:
            records.extend(import_records(model_file))
        except (OSError, ValueError):
            pass
    merged = {}
    for row in records:
        if not isinstance(row, dict) or row.get("is_active", True) is False:
            continue
        name = str(row.get("Nombre_Modelo") or row.get("name") or "").strip()
        if name:
            merged[name] = row
    return list(merged.values())


def load_finops_demo():
    """Load demo FinOps values from data instead of embedding them in the UI."""
    rows = load_csv_rows("finops_demo.csv")
    metrics = {"costo_actual": 0.0, "presupuesto_mensual": 0.0, "ahorro_estimado": 0.0}
    services = []
    for row in rows:
        metric = row.get("metrica", "").strip().lower()
        if metric in metrics:
            value = parse_number(row.get("valor_clp"))
            if value is not None:
                metrics[metric] = value
        elif metric == "servicio":
            percentage = parse_number(row.get("porcentaje"))
            service = row.get("servicio", "").strip()
            if service and percentage is not None:
                services.append((service, percentage))
    return metrics, services


class ExchangeRateThread(QThread):
    rates_ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, fallback_path, parent=None):
        super().__init__(parent)
        self.fallback_path = fallback_path

    def run(self):
        try:
            self.rates_ready.emit(fetch_exchange_rates(self.fallback_path))
        except Exception as exc:
            self.failed.emit(str(exc))


def parse_number(value):
    if value is None:
        return None
    text = "".join(ch for ch in str(value) if ch.isdigit() or ch == ".")
    return float(text) if text else None


def extract_cloud_entry(entorno):
    if not entorno:
        return [], ""
    entorno = entorno.strip()
    if "Cloud:" in entorno:
        cloud_spec = entorno.split("Cloud:", 1)[1].strip()
        region_code = ""
        provider_part = cloud_spec
        if "(" in cloud_spec and ")" in cloud_spec:
            provider_part, region_part = cloud_spec.split("(", 1)
            region_code = region_part.split(")", 1)[0].strip()
        providers = [
            part.strip()
            for part in provider_part.replace("/", ",").split(",")
            if part.strip()
        ]
        return providers, region_code
    if "Datacenter Local" in entorno or "Laboratorio Local" in entorno:
        return ["Local"], ""
    return [], ""


def build_cloud_region_map(rows):
    region_map = {}
    provider_order = []
    for row in rows:
        region_label = row.get("Region_Pais_Ubicacion", "").strip()
        entorno = row.get("Entorno_Ejecucion", "").strip()
        providers, region_code = extract_cloud_entry(entorno)
        if not providers or not region_label:
            continue
        if region_code:
            label = f"{region_label} ({region_code})"
        else:
            label = region_label
        for provider in providers:
            if provider not in region_map:
                region_map[provider] = []
                provider_order.append(provider)
            if label not in region_map[provider]:
                region_map[provider].append(label)
    return region_map, provider_order


def normalize_username(value):
    return value.strip().lower()


def find_user_profile(config, username):
    key = normalize_username(username)
    for user in config.get("users", []):
        if normalize_username(user.get("username", "")) == key:
            return user
        if normalize_username(user.get("display_name", "")) == key:
            return user
    return None


def save_users_to_config(users):
    """Persist the full users list to config.json, preserving other settings."""
    config_path = writable_path("config.json")
    config = load_config()
    config["users"] = users
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=True, indent=2)


def save_current_project_id(project_id):
    """Persist the active project selection to config.json, preserving other settings."""
    config_path = writable_path("config.json")
    config = load_config()
    config["current_project_id"] = project_id
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=True, indent=2)


def get_default_user(config):
    default_user = config.get("default_user", "")
    profile = find_user_profile(config, default_user)
    if profile:
        return profile
    users = config.get("users", [])
    return users[0] if users else {"display_name": "Usuario", "role": "", "profile_photo": ""}


def resolve_path(relative_path):
    if not relative_path:
        return ""
    writable_candidate = os.path.normpath(writable_path(relative_path))
    if os.path.isfile(writable_candidate):
        return writable_candidate
    return os.path.normpath(resource_path(relative_path))


PROFILE_PHOTO_SIZE = 400


def save_profile_photo(username, pixmap):
    """Save a cropped 400x400 PNG for the given user and return its config-relative path."""
    safe_name = re.sub(r"[^a-z0-9_-]+", "_", normalize_username(username)).strip("_") or "usuario"
    filename = f"user_{safe_name}.png"
    target = writable_path("img", filename)
    if not pixmap.save(target, "PNG"):
        raise OSError(f"No se pudo guardar la foto de perfil en {target}.")
    return f"img/{filename}"


def make_round_pixmap(image_source, size):
    pixmap = image_source if isinstance(image_source, QPixmap) else QPixmap(image_source)
    if pixmap.isNull():
        return None

    scaled = pixmap.scaled(
        size,
        size,
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation,
    )
    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)

    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)
    clip_path = QPainterPath()
    clip_path.addEllipse(0, 0, size, size)
    painter.setClipPath(clip_path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()

    return rounded


def make_separator(object_name="separator"):
    line = QFrame()
    line.setObjectName(object_name)
    line.setFixedHeight(1)
    return line


def format_energy_value(kwh):
    """Use Wh for sub-kWh values so short executions remain readable."""
    if abs(kwh) < 1:
        return f"{kwh * 1000:.2f} Wh"
    return f"{kwh:.2f} kWh"


def make_line_icon(size, color, draw_fn):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor(color))
    pen.setWidth(2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    draw_fn(painter, size)
    painter.end()

    return pixmap


def make_text_icon(text, size, color):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor(color))
    painter.setFont(QFont("Segoe UI", int(size * 0.7), QFont.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()

    return pixmap


def make_leaf_pixmap(size=18, color="#66bb22"):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)

    path = QPainterPath()
    path.moveTo(size * 0.2, size * 0.6)
    path.quadTo(size * 0.45, size * 0.1, size * 0.85, size * 0.4)
    path.quadTo(size * 0.6, size * 0.9, size * 0.2, size * 0.6)
    painter.drawPath(path)

    painter.setPen(QPen(QColor("#0b0b0b"), 1))
    painter.drawLine(int(size * 0.35), int(size * 0.7), int(size * 0.7), int(size * 0.35))
    painter.end()

    return pixmap


def make_money_pixmap(size=18, color="#d89a1d"):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size - 1, size - 1)

    painter.setPen(QPen(QColor("#0b0b0b"), 1))
    painter.setFont(QFont("Segoe UI", int(size * 0.6), QFont.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "$")
    painter.end()

    return pixmap


def make_home_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        roof = QPolygonF(
            [
                QPointF(side * 0.12, side * 0.6),
                QPointF(side * 0.5, side * 0.2),
                QPointF(side * 0.88, side * 0.6),
            ]
        )
        painter.drawPolyline(roof)
        painter.drawRect(QRectF(side * 0.22, side * 0.55, side * 0.56, side * 0.32))
        painter.drawRect(QRectF(side * 0.46, side * 0.68, side * 0.12, side * 0.19))

    return make_line_icon(size, color, draw)


def make_grid_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        cell = side * 0.26
        gap = side * 0.14
        start = side * 0.12
        for row in range(2):
            for col in range(2):
                x = start + col * (cell + gap)
                y = start + row * (cell + gap)
                painter.drawRect(QRectF(x, y, cell, cell))

    return make_line_icon(size, color, draw)


def make_bars_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        bar_width = side * 0.18
        gap = side * 0.1
        base = side * 0.78
        heights = [side * 0.3, side * 0.5, side * 0.68]
        for i, height in enumerate(heights):
            x = side * 0.18 + i * (bar_width + gap)
            painter.drawRoundedRect(
                QRectF(x, base - height, bar_width, height), 2, 2
            )

    return make_line_icon(size, color, draw)


def make_chip_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        painter.drawRect(QRectF(side * 0.25, side * 0.25, side * 0.5, side * 0.5))
        for i in range(3):
            offset = side * (0.3 + i * 0.2)
            painter.drawLine(QPointF(offset, side * 0.15), QPointF(offset, side * 0.25))
            painter.drawLine(
                QPointF(offset, side * 0.75), QPointF(offset, side * 0.85)
            )
            painter.drawLine(QPointF(side * 0.15, offset), QPointF(side * 0.25, offset))
            painter.drawLine(
                QPointF(side * 0.75, offset), QPointF(side * 0.85, offset)
            )

    return make_line_icon(size, color, draw)


def make_cloud_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        path = QPainterPath()
        path.moveTo(side * 0.22, side * 0.62)
        path.cubicTo(side * 0.18, side * 0.45, side * 0.32, side * 0.32, side * 0.46, side * 0.42)
        path.cubicTo(side * 0.5, side * 0.26, side * 0.74, side * 0.28, side * 0.74, side * 0.5)
        path.cubicTo(side * 0.86, side * 0.5, side * 0.86, side * 0.7, side * 0.72, side * 0.7)
        path.lineTo(side * 0.28, side * 0.7)
        path.cubicTo(side * 0.2, side * 0.7, side * 0.18, side * 0.64, side * 0.22, side * 0.62)
        painter.drawPath(path)

    return make_line_icon(size, color, draw)


def make_clock_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        painter.drawEllipse(QRectF(side * 0.18, side * 0.18, side * 0.64, side * 0.64))
        painter.drawLine(
            QPointF(side * 0.5, side * 0.5), QPointF(side * 0.5, side * 0.32)
        )
        painter.drawLine(
            QPointF(side * 0.5, side * 0.5), QPointF(side * 0.66, side * 0.56)
        )

    return make_line_icon(size, color, draw)


def make_gear_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        center = QPointF(side * 0.5, side * 0.5)
        radius = side * 0.2
        painter.drawEllipse(center, radius, radius)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            start = QPointF(
                center.x() + math.cos(rad) * (radius + side * 0.02),
                center.y() + math.sin(rad) * (radius + side * 0.02),
            )
            end = QPointF(
                center.x() + math.cos(rad) * (radius + side * 0.12),
                center.y() + math.sin(rad) * (radius + side * 0.12),
            )
            painter.drawLine(start, end)

    return make_line_icon(size, color, draw)


def make_hamburger_icon(size=18, color="#f2f2f2"):
    def draw(painter, side):
        left = side * 0.2
        right = side * 0.8
        for index in range(3):
            y = side * (0.3 + index * 0.2)
            painter.drawLine(QPointF(left, y), QPointF(right, y))

    return make_line_icon(size, color, draw)


def make_warning_icon(size=22, color="#f2f2f2"):
    def draw(painter, side):
        triangle = QPolygonF(
            [
                QPointF(side * 0.5, side * 0.12),
                QPointF(side * 0.1, side * 0.85),
                QPointF(side * 0.9, side * 0.85),
            ]
        )
        painter.drawPolygon(triangle)
        painter.drawLine(
            QPointF(side * 0.5, side * 0.35),
            QPointF(side * 0.5, side * 0.6),
        )
        painter.drawEllipse(QRectF(side * 0.46, side * 0.68, side * 0.08, side * 0.08))

    return make_line_icon(size, color, draw)


def make_exclamation_icon(size=22, color="#f2f2f2"):
    def draw(painter, side):
        painter.drawLine(
            QPointF(side * 0.5, side * 0.2),
            QPointF(side * 0.5, side * 0.65),
        )
        painter.drawEllipse(QRectF(side * 0.45, side * 0.73, side * 0.1, side * 0.1))

    return make_line_icon(size, color, draw)


def make_thumb_icon(size=22, color="#f2f2f2"):
    def draw(painter, side):
        path = QPainterPath()
        path.moveTo(side * 0.2, side * 0.55)
        path.lineTo(side * 0.45, side * 0.55)
        path.lineTo(side * 0.55, side * 0.32)
        path.lineTo(side * 0.72, side * 0.32)
        path.lineTo(side * 0.72, side * 0.75)
        path.lineTo(side * 0.2, side * 0.75)
        path.closeSubpath()
        painter.drawPath(path)

    return make_line_icon(size, color, draw)


def make_bulb_icon(size=22, color="#f2f2f2"):
    def draw(painter, side):
        painter.drawEllipse(QRectF(side * 0.26, side * 0.12, side * 0.48, side * 0.48))
        painter.drawLine(
            QPointF(side * 0.38, side * 0.66),
            QPointF(side * 0.62, side * 0.66),
        )
        painter.drawRect(QRectF(side * 0.4, side * 0.66, side * 0.2, side * 0.16))

    return make_line_icon(size, color, draw)



class MetricCard(QFrame):
    def __init__(
        self,
        title,
        icon_pixmap,
        value_text,
        percent_text,
        progress_value,
        progress_color,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        title_label = make_label(title, "metricTitle")

        icon_label = QLabel()
        icon_label.setPixmap(icon_pixmap)
        icon_label.setFixedSize(QSize(22, 22))

        value_label = make_label(value_text, "metricValue")
        percent_label = make_label(percent_text, "metricPercent", alignment=Qt.AlignRight)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(icon_label)
        top_row.addWidget(value_label, 1)
        top_row.addWidget(percent_label)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(progress_value)
        progress.setTextVisible(False)
        progress.setObjectName("standardProgressBar")
        progress.setFixedHeight(12)

        main_layout.addWidget(title_label)
        main_layout.addLayout(top_row)
        main_layout.addWidget(progress)


class SummaryCard(QFrame):
    def __init__(self, label_text, value_text, parent=None):
        super().__init__(parent)
        self.setObjectName("summaryCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        label = make_label(label_text, "summaryLabel")
        value = make_label(value_text, "summaryValue")

        layout.addWidget(label)
        layout.addWidget(value)


class PerformanceCard(QFrame):
    def __init__(self, title, value, parent=None):
        super().__init__(parent)
        self.setObjectName("performanceCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(make_label(title, "performanceTitle"))
        layout.addStretch()

        value_label = make_label(value, "performanceValue")
        value_label.setObjectName("performanceValue")
        value_label.setWordWrap(True)
        layout.addWidget(value_label)
        self.value_label = value_label

    def set_value(self, value):
        self.value_label.setText(str(value))

    def get_value(self):
        return self.value_label.text()


class ChevronComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._chevron = QLabel("v", self)
        self._chevron.setObjectName("comboChevron")
        self._chevron.setAlignment(Qt.AlignCenter)
        self._chevron.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._chevron.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_chevron()

    def _position_chevron(self):
        self._chevron.adjustSize()
        right_padding = 12
        x = self.width() - right_padding - self._chevron.width()
        y = (self.height() - self._chevron.height()) // 2
        self._chevron.move(x, y)


class DetailsPanel(QFrame):
    def __init__(self, title, rows, parent=None):
        super().__init__(parent)
        self.setObjectName("detailsPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.value_labels = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        layout.addWidget(make_label(title, "detailsTitle"))
        layout.addSpacing(4)

        for index, (label, value) in enumerate(rows):
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(make_label(label, "detailLabel"))
            value_label = make_label(value, "detailValue", alignment=Qt.AlignRight)
            self.value_labels.append(value_label)
            row.addWidget(value_label)
            layout.addLayout(row)
            if index < len(rows) - 1:
                layout.addWidget(make_separator("detailLine"))

    def set_values(self, values):
        for label, value in zip(self.value_labels, values):
            label.setText(value)


class StatusCard(QFrame):
    def __init__(
        self,
        tone_color,
        icon_pixmap,
        title,
        description,
        level=None,
        large=False,
        parent=None,
    ):
        self.default_description = description
        super().__init__(parent)
        self.setObjectName("statusCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if level:
            self.setProperty("level", level)
        self.setProperty("selected", False)

        layout = QVBoxLayout(self)
        if large:
            layout.setContentsMargins(26, 26, 26, 26)
            layout.setSpacing(14)
        else:
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(12)

        circle = QFrame()
        circle.setObjectName("statusCircle")
        circle_size = 116 if large else 88
        circle.setFixedSize(circle_size, circle_size)


        circle.setStyleSheet(
            "QFrame {"
            f"  background-color: {tone_color};"
            f"  border-radius: {circle_size // 2}px;"
            "}"
        )

        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        from PySide6.QtGui import QColor
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(40)
        effect.setColor(QColor(tone_color))
        effect.setOffset(0, 0)
        circle.setGraphicsEffect(effect)


        layout.addWidget(circle, 0, Qt.AlignHCenter)
        layout.addWidget(make_separator("statusDivider"))

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(icon_pixmap)
        icon_size = 28 if large else 24
        icon_label.setFixedSize(icon_size, icon_size)

        title_label = make_label(title, "statusTitle")

        title_row.addWidget(icon_label)
        title_row.addWidget(title_label, 1)

        layout.addLayout(title_row)

        note = QFrame()
        note.setObjectName("statusNote")
        note_layout = QVBoxLayout(note)
        if large:
            note_layout.setContentsMargins(14, 12, 14, 12)
        else:
            note_layout.setContentsMargins(12, 10, 12, 10)

        self.note_label = make_label(description, "statusNoteText")
        self.note_label.setWordWrap(True)
        note_layout.addWidget(self.note_label)

        layout.addWidget(note)
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(20)
        effect.setColor(QColor(0, 0, 0, 100))
        effect.setOffset(0, 4)
        self.setGraphicsEffect(effect)



    def update_description(self, new_text):
        self.note_label.setText(new_text)

    def set_selected(self, selected):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)


class InfoBar(QFrame):
    def __init__(self, title, text, compact=False, parent=None):
        super().__init__(parent)
        self.setObjectName("infoBar")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if compact:
            self.setProperty("compact", True)

        layout = QHBoxLayout(self)
        if compact:
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(6)
        else:
            layout.setContentsMargins(14, 10, 14, 10)
            layout.setSpacing(10)

        icon = QLabel()
        icon_size = 16 if compact else 26
        icon.setPixmap(make_bulb_icon(icon_size))
        icon.setFixedSize(icon_size, icon_size)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3 if compact else 6)

        title_label = make_label(title, "infoTitle")
        body_label = make_label(text, "infoText")
        body_label.setWordWrap(True)

        text_layout.addWidget(title_label)
        text_layout.addWidget(body_label)

        layout.addWidget(icon)
        layout.addLayout(text_layout, 1)


class InfoCard(QFrame):
    def __init__(self, title, value, parent=None):
        super().__init__(parent)
        self.setObjectName("infoCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)

        layout.addWidget(make_label(title, "infoCardTitle"))
        self.value_label = make_label(value, "infoCardValue")
        layout.addWidget(self.value_label)
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(20)
        effect.setColor(QColor(0, 0, 0, 100))
        effect.setOffset(0, 4)
        self.setGraphicsEffect(effect)



    def set_value(self, value):
        self.value_label.setText(value)

    def get_value(self):
        return self.value_label.text()


class ListPanel(QFrame):
    def __init__(self, title, items, separator_spacing=0, show_title=True, parent=None):
        super().__init__(parent)
        self.setObjectName("listPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        if show_title:
            layout.addWidget(make_label(title, "listTitle"))
            layout.addSpacing(4)

        for index, item in enumerate(items):
            item_label = make_label(item, "listItem")
            item_label.setWordWrap(True)
            layout.addWidget(item_label)
            if index < len(items) - 1:
                if separator_spacing:
                    layout.addSpacing(separator_spacing)
                layout.addWidget(make_separator("listLine"))
                if separator_spacing:
                    layout.addSpacing(separator_spacing)

    def set_items(self, items, separator_spacing=0):
        layout = self.layout()
        while layout.count() > 2:
            item = layout.takeAt(2)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, value in enumerate(items):
            item_label = make_label(value, "listItem")
            item_label.setWordWrap(True)
            layout.addWidget(item_label)
            if index < len(items) - 1:
                if separator_spacing:
                    layout.addSpacing(separator_spacing)
                layout.addWidget(make_separator("listLine"))
                if separator_spacing:
                    layout.addSpacing(separator_spacing)


class KpiCard(QFrame):
    def __init__(self, title, value, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        layout.addWidget(make_label(title, "kpiTitle"))
        layout.addStretch()
        layout.addWidget(make_label(value, "kpiValue"))


class ActivityPanel(QFrame):
    def __init__(
        self,
        items,
        title=None,
        title_alignment=Qt.AlignLeft,
        object_name="activityPanel",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title = t("Registro de Actividad") if title is None else title

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title_label = make_label(title, "activityTitle", alignment=title_alignment)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addSpacing(4)

        for text in items:
            item_label = make_label(f"•  {text}", "activityItem")
            item_label.setWordWrap(True)
            layout.addWidget(item_label)


class _OllamaChatWorker(QObject):
    """Corre un turno real de chat con Ollama en un hilo aparte para no congelar la UI."""
    finished = Signal(bool, str, dict)

    def __init__(self, uri, model, messages):
        super().__init__()
        self.uri = uri
        self.model = model
        self.messages = messages

    def run(self):
        import ollama_integration
        try:
            if not ollama_integration.is_reachable(self.uri):
                started = ollama_integration.start_local_server_if_needed(self.uri)
                if not started:
                    raise ollama_integration.OllamaError(
                        "No se encontro un servidor Ollama corriendo ni el binario 'ollama' "
                        "instalado. Instala Ollama desde https://ollama.com y vuelve a intentar."
                    )
            ollama_integration.ensure_model_available(self.uri, self.model)
            metrics = ollama_integration.run_chat(self.uri, self.model, self.messages)
        except Exception as exc:
            self.finished.emit(False, str(exc), {})
        else:
            self.finished.emit(True, "", metrics)


class _OllamaChatController(QObject):
    """Vive en el hilo principal: igual que _ExportController en export_handler.py,
    conectar la senal del worker (que corre en otro hilo) a un slot de un QObject con
    afinidad al hilo principal es lo que evita tocar la UI desde el hilo equivocado."""

    def __init__(self, chat_window, thread, worker):
        super().__init__()
        self.chat_window = chat_window
        self.thread = thread
        self.worker = worker

    @Slot(bool, str, dict)
    def on_finished(self, success, error_message, metrics):
        self.thread.quit()
        self.thread.wait()
        self.chat_window._thread = None
        self.chat_window._worker = None
        self.chat_window._handle_response(success, error_message, metrics)
        if self.chat_window._controller is self:
            self.chat_window._controller = None


class OllamaChatWindow(QDialog):
    """Ventana de chat real contra Ollama; cada respuesta real se registra en el
    proyecto activo (LocalStore + MLflow) via los helpers de HomeView."""

    def __init__(self, home_view, hardware, provider, region, tdp, intensity, parent=None):
        super().__init__(parent)
        self.home_view = home_view
        self.hardware = hardware
        self.provider = provider
        self.region = region
        self.tdp = tdp
        self.intensity = intensity
        self.messages = []
        self._thread = None
        self._worker = None
        self._controller = None

        import ollama_integration
        config = load_config()
        self.uri = config.get("ollama_uri") or ollama_integration.DEFAULT_OLLAMA_URI
        self.model = config.get("ollama_test_model") or ollama_integration.DEFAULT_TEST_MODEL

        self.setWindowTitle(t("Chat con Ollama"))
        self.resize(560, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(make_label(t("Modelo: {model}").format(model=self.model), "infoText"))

        self.history_view = QTextEdit()
        self.history_view.setReadOnly(True)
        layout.addWidget(self.history_view, 1)

        self.status_label = make_label("", "infoText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText(t("Escribe un mensaje..."))
        self.input_line.returnPressed.connect(self._send_message)
        input_row.addWidget(self.input_line, 1)

        self.send_btn = QPushButton(t("Enviar"))
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._send_message)
        input_row.addWidget(self.send_btn)

        layout.addLayout(input_row)
        self.input_line.setFocus()

    def _append_line(self, who, text):
        safe_who = html_escape(str(who))
        safe_text = html_escape(str(text)).replace("\n", "<br>")
        self.history_view.append(f"<b>{safe_who}:</b> {safe_text}<br>")

    def _send_message(self):
        prompt = self.input_line.text().strip()
        if not prompt or (self._thread is not None and self._thread.isRunning()):
            return

        self._append_line(t("Tú"), prompt)
        self.messages.append({"role": "user", "content": prompt})
        self.input_line.clear()
        self.input_line.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.status_label.setText(t("Esperando respuesta del modelo..."))

        self._thread = QThread(self)
        self._worker = _OllamaChatWorker(self.uri, self.model, list(self.messages))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._controller = _OllamaChatController(self, self._thread, self._worker)
        self._worker.finished.connect(self._controller.on_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _handle_response(self, success, error_message, metrics):
        self.input_line.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_line.setFocus()

        if not success:
            self.status_label.setText("")
            QMessageBox.critical(
                self, t("Chat con Ollama"),
                t("No se pudo ejecutar el modelo en Ollama:\n{error}").format(error=error_message),
            )
            return

        response_text = metrics.get("response_text", "")
        self.messages.append({"role": "assistant", "content": response_text})
        self._append_line(self.model, response_text)

        result = self.home_view._register_ollama_metrics(
            self.model, self.hardware, self.provider, self.region, self.tdp, self.intensity, metrics,
        )
        status_text = t("Tokens: {count} · {tps} tok/s · {ms:.0f} ms · {energy}").format(
            count=metrics.get("eval_count", 0), tps=metrics.get("tokens_per_second", 0),
            ms=metrics.get("total_duration_ms", 0), energy=format_energy_value(result["kwh"]),
        )
        if result["registered"]:
            status_text += " · " + t("registrado en el proyecto activo")
        elif result["error"]:
            status_text += " · " + t("no se pudo registrar: {error}").format(error=result["error"])
        elif result["carbon"] is None:
            status_text += " · " + t("sin región/proveedor: no se estimó carbono")
        else:
            status_text += " · " + t("sin proyecto activo: no se registró")
        self.status_label.setText(status_text)


class HomeView(QWidget):
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.main_window = main_window
        self._chat_window = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        header_icon = QLabel()
        header_icon.setPixmap(make_leaf_pixmap(22))
        header_icon.setFixedSize(QSize(22, 22))

        header_title = make_label(t("SEMÁFORO IA"), "pageTitle")

        header_layout.addWidget(header_icon)
        header_layout.addWidget(header_title, 1)

        # CU 57.2
        self.export_home_btn = QPushButton(t("Exportar"))
        self.export_home_btn.setObjectName("secondaryButton")
        self.export_home_btn.setCursor(Qt.PointingHandCursor)
        self.export_home_btn.clicked.connect(self.show_export_home_menu)
        header_layout.addWidget(self.export_home_btn)

        self.register_execution_btn = QPushButton(t("Registrar Ejecución"))
        self.register_execution_btn.setObjectName("secondaryButton")
        self.register_execution_btn.setCursor(Qt.PointingHandCursor)
        self.register_execution_btn.clicked.connect(self._register_execution)
        header_layout.addWidget(self.register_execution_btn)

        self.run_model_btn = QPushButton(t("Chat con Ollama"))
        self.run_model_btn.setObjectName("secondaryButton")
        self.run_model_btn.setCursor(Qt.PointingHandCursor)
        self.run_model_btn.clicked.connect(self._open_ollama_chat)
        header_layout.addWidget(self.run_model_btn)

        layout.addLayout(header_layout)
        layout.addWidget(make_separator("separator"))

        # Alert/Warning bar CU 11.2, 38.2
        self.alert_bar = QFrame()
        self.alert_bar.setObjectName("statusCard")
        self.alert_bar.setProperty("level", "alto")
        self.alert_bar.setStyleSheet("background-color: #b60f0f; border-radius: 8px;")
        alert_layout = QHBoxLayout(self.alert_bar)
        alert_layout.setContentsMargins(14, 10, 14, 10)
        alert_layout.setSpacing(14)

        alert_text = make_label(t("¡Alerta Crítica! Límite de emisiones proyectado al 95%."), "infoTitle")
        alert_layout.addWidget(alert_text, 1)

        snooze_btn = QPushButton(t("Silenciar Advertencia por Tiempo Limitado"))
        snooze_btn.setObjectName("secondaryButton")
        snooze_btn.setCursor(Qt.PointingHandCursor)

        close_btn = QPushButton(t("Cerrar"))
        close_btn.setObjectName("secondaryButton")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.alert_bar.setVisible(False))

        def toggle_alert():
            is_visible = alert_text.isVisible()
            alert_text.setVisible(not is_visible)
            close_btn.setVisible(not is_visible)

            if is_visible:
                snooze_btn.setText(t("Mostrar Advertencia"))
                alert_layout.setContentsMargins(14, 4, 14, 4)
            else:
                snooze_btn.setText(t("Silenciar Advertencia por Tiempo Limitado"))
                alert_layout.setContentsMargins(14, 10, 14, 10)

        snooze_btn.clicked.connect(toggle_alert)

        alert_layout.addWidget(snooze_btn)
        alert_layout.addWidget(close_btn)

        layout.addWidget(self.alert_bar)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(18)

        self.status_cards = {
            "alto": StatusCard(
                "#b60f0f",
                make_warning_icon(22),
                t("Huella de Carbono Alta"),
                t("Tu nivel de Huella de Carbono es alto. Se recomienda revisar el consumo energético y la configuración de hardware."),
                level="alto",
                large=True,
            ),
            "moderado": StatusCard(
                "#c4a600",
                make_exclamation_icon(22),
                t("Huella de Carbono Moderada"),
                t("Tu nivel de Huella de Carbono es estándar. Se mantiene estable, pero existen oportunidades de mejora."),
                level="moderado",
                large=True,
            ),
            "bajo": StatusCard(
                "#4eb541",
                make_thumb_icon(22),
                t("Huella de Carbono Baja"),
                t("Tu nivel de Huella de Carbono es bajo y se mantiene con muy poco uso adicional."),
                level="bajo",
                large=True,
            ),
        }

        for key in ("alto", "moderado", "bajo"):
            cards_layout.addWidget(self.status_cards[key], 1)

        info_bar = InfoBar(
            t("¿Cómo se calcula?"),
            t("Se estima con energía, hardware, tiempo de proceso y región/proveedor."),
            compact=True,
        )
        info_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        info_bar.setMaximumHeight(68)

        layout.addLayout(cards_layout, 1)
        layout.addWidget(info_bar)

    def set_semaforo_level(self, level, score=None, green_score_value=None):
        for key, card in self.status_cards.items():
            card.set_selected(level == key)
            if level == key and score is not None:
                # Dynamic green score and tips
                green_score = green_score_value if green_score_value is not None else max(0.0, 100.0 - (score / 5.0))

                # El idioma se resuelve dinamicamente vía el motor i18n compartido
                lang = getattr(self.window(), "current_lang", i18n.get_language())

                base_desc_key = "Tu nivel de Huella de Carbono es bajo."
                if level == "alto":
                    base_desc_key = "Nivel ALTO."
                elif level == "moderado":
                    base_desc_key = "Nivel MODERADO."

                if green_score < 50:
                    tip_key = "tip_mueve_cargas"
                elif green_score < 80:
                    tip_key = "tip_optimiza_duracion"
                else:
                    tip_key = "tip_excelente_green_score"

                base_desc = i18n.t(base_desc_key, lang)
                tip = f"\n{i18n.t(tip_key, lang)}"
                header = i18n.t("Impacto de Carbono: {score} | Green Score: {gs}/100.", lang).format(score=f"{score:.1f}", gs=f"{green_score:.1f}")
                full_text = f"{header}\n{base_desc}{tip}"

                card.update_description(full_text)
            else:
                card.update_description(card.default_description)

    def _save_execution_locally(self, *, project_id, model, cost, carbon, kwh, water, duration_ms, semaphore):
        """Persiste la ejecucion en LocalStore y devuelve el nombre real del proyecto."""
        config = load_config()
        store = None
        try:
            store = bootstrap_store(config, writable_path("semaforo.sqlite3"))
            project_row = store.connection.execute(
                "SELECT name FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project_row is None:
                raise ValidationError(t("El proyecto activo ya no existe."))
            project_name = project_row["name"]

            model_row = next((m for m in store.list_models(project_id) if m["name"] == model), None)
            model_id = model_row["id"] if model_row else store.add_model(project_id, model)

            store.add_execution(Execution(
                model_id=model_id, timestamp=utc_iso(), cost=cost, carbon=carbon,
                kwh=kwh, water=water, duration_ms=int(duration_ms), semaphore=semaphore,
            ))
            return project_name
        finally:
            if store is not None:
                store.close()

    def _log_execution_to_mlflow(self, *, project_name, model, hardware, provider, region,
                                  cost, carbon, kwh, water, duration_ms, semaphore):
        import mlflow_integration
        return mlflow_integration.log_execution_run(
            load_config(), project_name=project_name, model_name=model, hardware=hardware,
            provider=provider, region=region, cost=cost, carbon=carbon, kwh=kwh,
            water=water, duration_ms=int(duration_ms), semaphore=semaphore,
        )

    def _register_execution(self):
        """Persiste el calculo real actual (LocalStore + MLflow); no hay valores inventados."""
        if not self.main_window:
            return
        state = self.main_window.selection_state
        provider = state.get("provider")
        region = state.get("region")
        model = state.get("model")
        hardware = state.get("hardware")
        tdp = state.get("hardware_tdp")
        score = self.main_window.current_score
        semaphore_value = self.main_window.current_semaphore_level

        if not (provider and region and model and hardware) or score is None or semaphore_value is None:
            QMessageBox.warning(
                self, t("Registrar Ejecución"),
                t("Completa proveedor, región, modelo y hardware antes de registrar."),
            )
            return

        project_id = load_config().get("current_project_id")
        if project_id is None:
            QMessageBox.warning(
                self, t("Registrar Ejecución"),
                t("Selecciona un proyecto activo en la vista Proyectos primero."),
            )
            return

        kwh = calculate_energy(tdp, 1.0, 1.0)
        cost = 0.0
        water = 0.0
        duration_ms = 3600000

        try:
            project_name = self._save_execution_locally(
                project_id=project_id, model=model, cost=cost, carbon=score,
                kwh=kwh, water=water, duration_ms=duration_ms, semaphore=semaphore_value,
            )
            self.main_window.refresh_projects_view()
        except (OSError, ValidationError) as exc:
            QMessageBox.critical(self, t("Registrar Ejecución"), str(exc))
            return

        try:
            run_id = self._log_execution_to_mlflow(
                project_name=project_name, model=model, hardware=hardware, provider=provider,
                region=region, cost=cost, carbon=score, kwh=kwh, water=water,
                duration_ms=duration_ms, semaphore=semaphore_value,
            )
        except Exception as exc:
            QMessageBox.warning(
                self, t("Registrar Ejecución"),
                t("Ejecución guardada localmente, pero no se pudo registrar en MLflow:\n{error}").format(error=str(exc)),
            )
            return

        QMessageBox.information(
            self, t("Registrar Ejecución"),
            t("Ejecución registrada localmente y en MLflow (run {run_id}).").format(run_id=run_id),
        )

    def _open_ollama_chat(self):
        """Abre una ventana de chat real contra Ollama, ligada al hardware/región activos."""
        if not self.main_window:
            return
        state = self.main_window.selection_state
        hardware = state.get("hardware")
        tdp = state.get("hardware_tdp")
        provider = state.get("provider")
        region = state.get("region")
        intensity = state.get("region_intensity")

        if not hardware or tdp is None:
            QMessageBox.warning(
                self, t("Chat con Ollama"),
                t("Selecciona un hardware antes de ejecutar el modelo."),
            )
            return

        if self._chat_window is not None:
            self._chat_window.close()
        self._chat_window = OllamaChatWindow(self, hardware, provider, region, tdp, intensity, parent=self)
        self._chat_window.setAttribute(Qt.WA_DeleteOnClose)
        self._chat_window.destroyed.connect(lambda: setattr(self, "_chat_window", None))
        self._chat_window.show()

    def _register_ollama_metrics(self, model, hardware, provider, region, tdp, intensity, metrics):
        """Calcula energia/carbono reales desde un turno de Ollama y registra la ejecucion
        en el proyecto activo (LocalStore + MLflow) si hay uno seleccionado. No muestra
        dialogos: devuelve los valores calculados para que el llamador decida como mostrarlos."""
        duration_ms = metrics["total_duration_ms"]
        hours = duration_ms / 3_600_000.0
        kwh = calculate_energy(tdp, hours, 1.0)
        carbon = calculate_carbon(tdp, hours, 1.0, intensity) if intensity is not None else None

        result = {"kwh": kwh, "carbon": carbon, "registered": False, "error": None}

        project_id = load_config().get("current_project_id")
        semaphore_value = (self.main_window.current_semaphore_level if self.main_window else None) or "Verde"
        if carbon is not None and project_id is not None:
            try:
                project_name = self._save_execution_locally(
                    project_id=project_id, model=model, cost=0.0, carbon=carbon,
                    kwh=kwh, water=0.0, duration_ms=duration_ms, semaphore=semaphore_value,
                )
                if self.main_window:
                    self.main_window.refresh_projects_view()
                self._log_execution_to_mlflow(
                    project_name=project_name, model=model, hardware=hardware, provider=provider or "",
                    region=region or "", cost=0.0, carbon=carbon, kwh=kwh, water=0.0,
                    duration_ms=duration_ms, semaphore=semaphore_value,
                )
                result["registered"] = True
            except Exception as exc:
                result["error"] = str(exc)
        return result

    def show_export_home_menu(self):
        menu = QMenu(self)
        export_pdf_action = menu.addAction("PDF")
        export_json_action = menu.addAction("JSON")
        export_xlsx_action = menu.addAction("XLSX")
        export_both_action = menu.addAction("PDF + JSON")

        chosen_action = menu.exec(self.export_home_btn.mapToGlobal(self.export_home_btn.rect().bottomLeft()))
        if chosen_action == export_pdf_action:
            self.export_home_report("pdf")
        elif chosen_action == export_json_action:
            self.export_home_report("json")
        elif chosen_action == export_xlsx_action:
            self.export_home_report("xlsx")
        elif chosen_action == export_both_action:
            self.export_home_report("both")

    def export_home_report(self, export_format="pdf"):
        import export_handler

        score = None
        green_score_value = None
        semaphore_value = None
        selection = {}
        if self.main_window is not None:
            score = getattr(self.main_window, "current_score", None)
            green_score_value = getattr(self.main_window, "current_green_score", None)
            semaphore_value = getattr(self.main_window, "current_semaphore_level", None)
            selection = getattr(self.main_window, "selection_state", {}) or {}

        hardware = selection.get("hardware") or "N/A"
        provider = selection.get("provider") or "N/A"
        region = selection.get("region") or "N/A"
        model = selection.get("model") or "N/A"
        model_energy = selection.get("model_energy")
        model_energy_text = f"{model_energy} kWh" if model_energy is not None else "N/A"
        hardware_tdp = selection.get("hardware_tdp")
        hardware_tdp_text = f"{hardware_tdp} W" if hardware_tdp is not None else "N/A"

        has_selection = all(value != "N/A" for value in (hardware, provider, region, model))

        # ACCENT_COLORS: (main, dark, light) por nivel -- rojo/amarillo/verde
        ACCENT_COLORS = {
            "alto": ("red_500", "red_600", "red_100"),
            "error": ("red_500", "red_600", "red_100"),
            "advertencia": ("amber_500", "amber_600", "amber_100"),
            "moderado": ("amber_500", "amber_600", "amber_100"),
            "bajo": ("emerald_500", "emerald_600", "emerald_100"),
        }
        ACCENT_HEX = {
            "red_500": "#ef4444", "amber_500": "#f59e0b", "emerald_500": "#10b981",
        }

        if not has_selection:
            # Nada seleccionado: se advierte en vez de mostrar un Green Score engañoso de 0
            state = "advertencia"
            score_text = "N/A"
            green_score_text = "N/A"
            badge = t("Advertencia: Selección Incompleta")
            level = t("Sin selección")
            chart_values = [100]
            chart_labels = [t("Sin datos suficientes para calcular")]
            chart_colors = ["#d1d5db"]
            progress_value = 0
            logs_extra = [
                [t("Advertencia: faltan datos por seleccionar (proveedor, región, modelo u hardware)."), "amber_500"],
                [t("Impacto de Carbono y Green Score no disponibles sin selección completa."), "gray_500"],
            ]
        else:
            if score is None or green_score_value is None:
                state = "advertencia"
                score_text = "N/A"
                green_score_text = "N/A"
                badge = t("Advertencia: Datos incompletos")
                level = t("Sin datos suficientes")
                chart_values = [100]
                chart_labels = [t("Sin datos suficientes para calcular")]
                chart_colors = ["#d1d5db"]
                progress_value = 0
                logs_extra = [[t("Impacto de Carbono y Green Score no disponibles sin datos calculados."), "amber_500"]]
            else:
                green_score = float(green_score_value)
                score_text = f"{score:.1f}"
                green_score_text = f"{green_score:.1f}"
                margin = max(0.0, 100.0 - green_score)

                status_map = {
                    "Verde": ("bajo", t("Nivel Bajo"), "Bajo"),
                    "Amarillo": ("moderado", t("Nivel Moderado"), "Moderado"),
                    "Rojo": ("alto", t("Nivel Alto"), "Alto"),
                }
                state, badge, level = status_map.get(
                    semaphore_value,
                    ("advertencia", t("Advertencia: Estado no disponible"), t("Sin selección")),
                )
                logs_extra = [
                    [t("Impacto de Carbono y Green Score calculados correctamente."), "emerald_500"],
                    [t("Configuración completa: proveedor, región, modelo y hardware detectados."), "cyan_500"],
                ]
                chart_values = [round(green_score, 1), round(margin, 1)]
                chart_labels = [f"{t('Green Score')}: {green_score_text}", f"{t('Margen restante')}: {margin:.1f}"]
                chart_colors = ["#ef4444" if state == "alto" else "#f59e0b" if state == "moderado" else "#10b981", "#e5e7eb"]
                progress_value = round(green_score)

        accent, accent_dark, accent_light = ACCENT_COLORS[state]

        user_profile = getattr(self.window(), 'sidebar', None)
        if user_profile:
            user_profile = user_profile.user_profile
        else:
            user_profile = {}

        display_name = user_profile.get("display_name", t("Usuario Activo"))
        role = user_profile.get("role", "")
        exported_by_text = f"{display_name} ({role})" if role else display_name

        data = {
            "exported_by": exported_by_text,
            "chart_values": chart_values,
            "chart_labels": chart_labels,
            "chart_colors": chart_colors,
            "kpis": [
                [15, 60, t("Impacto de Carbono"), score_text, "pts", accent],
                [75, 60, t("Green Score"), green_score_text, "/100", accent],
            ],
            "details": [
                [t("Hardware"), hardware, "emerald_600"],
                [t("Proveedor Nube"), provider, "gray_800"],
                [t("Región Eléctrica"), region, "gray_800"],
                [t("Energía del Modelo"), model_energy_text, "gray_800"],
                [t("TDP Hardware"), hardware_tdp_text, "gray_800"],
                [t("Nivel Actual"), level, accent],
            ],
            "logs": [
                *logs_extra,
                [t("Sesión iniciada. Panel de Inicio actualizado."), "gray_500"],
            ],
            "progress": progress_value,
            "badge": badge,
            "accent_color": accent,
            "accent_color_dark": accent_dark,
            "accent_color_light": accent_light,
        }
        export_handler.generate_and_save_report(self, "inicio", data, export_format=export_format, lang=self.main_window.current_lang if self.main_window else i18n.get_language(), trigger_widget=self.export_home_btn)


class EnvironmentalPerformanceView(QWidget):
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(14)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        header_icon = QLabel()
        header_icon.setPixmap(make_leaf_pixmap(20))
        header_icon.setFixedSize(QSize(20, 20))

        header_title = make_label(t("Panel de Rendimiento Ambiental"), "pageTitle")

        header_layout.addWidget(header_icon)
        header_layout.addWidget(header_title, 1)

        # CU 57.2
        self.export_eco_btn = QPushButton(t("Exportar"))
        self.export_eco_btn.setObjectName("secondaryButton")
        self.export_eco_btn.setCursor(Qt.PointingHandCursor)
        self.export_eco_btn.clicked.connect(self.show_export_eco_menu)
        header_layout.addWidget(self.export_eco_btn)

        emissions_layout = QHBoxLayout()
        emissions_layout.setSpacing(12)
        self.emisiones_entrenamiento_card = PerformanceCard(t("Emisiones entrenamiento"), "0.00 gCO2eq")
        self.emisiones_ejecucion_card = PerformanceCard(t("Emisiones ejecución"), "0.00 gCO2eq")
        emissions_layout.addWidget(self.emisiones_entrenamiento_card, 1)
        emissions_layout.addWidget(self.emisiones_ejecucion_card, 1)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(12)
        self.consumo_energetico_card = PerformanceCard(t("Consumo Energético"), "0.00 Wh")
        self.tiempo_proceso_card = PerformanceCard(t("Tiempo de Procesamiento"), "0.00 s")
        metrics_layout.addWidget(self.consumo_energetico_card, 1)
        metrics_layout.addWidget(self.tiempo_proceso_card, 1)

        self.details_panel = DetailsPanel(t("Detalles del Cálculo"), [
            (t("Proyecto activo"), t("No seleccionado")),
            (t("Ejecuciones"), "0"),
            (t("Última ejecución"), t("Sin datos")),
            (t("Estado del cálculo"), t("Sin datos")),
        ])

        activity_items = [
            t("Cálculo Ambiental finalizado correctamente."),
            t("Métricas gCO2eq y kWh actualizadas en interfaz."),
            t("Variables aún no inicializadas -- mostrando aviso de cálculo en curso"),
            t("Sesión iniciada. Hardware detectado."),
            t("Excepción 1: datos no disponibles al iniciar."),
        ]
        activity_panel = ActivityPanel(activity_items, title_alignment=Qt.AlignLeft)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        bottom_row.addWidget(self.details_panel, 1)
        bottom_row.addWidget(activity_panel, 1)

        # CU 63.1, 63.2 (Ecological Limit & Insignia)
        from PySide6.QtWidgets import QProgressBar
        eco_limit_layout = QHBoxLayout()
        eco_limit_layout.setSpacing(12)

        eco_panel = QFrame()
        eco_panel.setObjectName("detailsPanel")
        eco_panel_layout = QVBoxLayout(eco_panel)
        eco_panel_layout.setContentsMargins(14, 10, 14, 10)

        eco_title_row = QHBoxLayout()
        eco_title_row.addWidget(make_label(t("% Límite Ecológico Utilizado"), "kpiTitle"))

        insignia_label = make_label(t("⭐ Insignia eficiencia: Uso < 50%"), "infoText")
        insignia_label.setStyleSheet("color: #4eb541;")
        eco_title_row.addWidget(insignia_label, 0, Qt.AlignRight)

        eco_panel_layout.addLayout(eco_title_row)

        self.eco_bar = QProgressBar()
        self.eco_bar.setRange(0, 100)
        self.eco_bar.setValue(0)
        self.eco_bar.setTextVisible(True)
        self.eco_bar.setObjectName("standardProgressBar")
        self.eco_bar.setFixedHeight(12)
        eco_panel_layout.addWidget(self.eco_bar)

        eco_limit_layout.addWidget(eco_panel, 1)

        main_layout.addLayout(header_layout)
        main_layout.addWidget(make_separator("separator"))
        main_layout.addLayout(emissions_layout)
        main_layout.addLayout(metrics_layout)
        main_layout.addLayout(bottom_row)
        main_layout.addLayout(eco_limit_layout)
        self.refresh_project_data()

    def refresh_project_data(self):
        metrics = self.main_window.get_active_project_metrics() if self.main_window else None
        if not metrics:
            return
        self.emisiones_entrenamiento_card.set_value("0.00 gCO2eq")
        self.emisiones_ejecucion_card.set_value(f"{metrics['carbon']:.4f} gCO2eq")
        self.consumo_energetico_card.set_value(format_energy_value(metrics["kwh"]))
        self.tiempo_proceso_card.set_value(f"{metrics['duration_ms'] / 1000:.2f} s")
        self.details_panel.set_values([
            metrics["project_name"],
            str(metrics["count"]),
            metrics["latest_timestamp"] or t("Sin datos"),
            t("Finalizado") if metrics["count"] else t("Sin datos"),
        ])
        self.eco_bar.setValue(max(0, min(100, round(metrics["carbon"]))))



    def show_export_eco_menu(self):
        menu = QMenu(self)
        export_pdf_action = menu.addAction("PDF")
        export_json_action = menu.addAction("JSON")
        export_xlsx_action = menu.addAction("XLSX")
        export_both_action = menu.addAction("PDF + JSON")

        chosen_action = menu.exec(self.export_eco_btn.mapToGlobal(self.export_eco_btn.rect().bottomLeft()))
        if chosen_action == export_pdf_action:
            self.export_eco_report("pdf")
        elif chosen_action == export_json_action:
            self.export_eco_report("json")
        elif chosen_action == export_xlsx_action:
            self.export_eco_report("xlsx")
        elif chosen_action == export_both_action:
            self.export_eco_report("both")

    def export_eco_report(self, export_format="pdf"):
        import export_handler

        consumo_val = self.consumo_energetico_card.findChild(QLabel, "performanceValue").text() if self.consumo_energetico_card.findChild(QLabel, "performanceValue") else "0 Wh"
        tiempo_val = self.tiempo_proceso_card.findChild(QLabel, "performanceValue").text() if self.tiempo_proceso_card.findChild(QLabel, "performanceValue") else "0 s"

        entrenamiento_text = self.emisiones_entrenamiento_card.findChild(QLabel, "performanceValue").text() if self.emisiones_entrenamiento_card.findChild(QLabel, "performanceValue") else "98"
        ejecucion_text = self.emisiones_ejecucion_card.findChild(QLabel, "performanceValue").text() if self.emisiones_ejecucion_card.findChild(QLabel, "performanceValue") else "44"

        def extract_emission_value(raw_text, default_value):
            cleaned = (raw_text or "").replace("gCO2eq", "").replace("gCO₂eq", "").strip()
            cleaned = cleaned.replace(",", ".")
            try:
                return int(round(float(cleaned)))
            except ValueError:
                match = re.search(r"\d+(?:[\.,]\d+)?", raw_text or "")
                if not match:
                    return default_value
                return int(round(float(match.group(0).replace(",", "."))))

        entrenamiento_val = extract_emission_value(entrenamiento_text, 0)
        ejecucion_val = extract_emission_value(ejecucion_text, 0)
        progress_val = self.eco_bar.value() if hasattr(self, "eco_bar") else 0
        detail_values = [label.text() for label in self.details_panel.value_labels]

        user_profile = getattr(self.window(), 'sidebar', None)
        if user_profile:
            user_profile = user_profile.user_profile
        else:
            user_profile = {}

        display_name = user_profile.get("display_name", t("Usuario Activo"))
        role = user_profile.get("role", "")
        exported_by_text = f"{display_name} ({role})" if role else display_name

        data = {
            "exported_by": exported_by_text,
            "chart_values": [entrenamiento_val, ejecucion_val],
            "chart_labels": [f"{t('Emisiones entrenamiento')}: {entrenamiento_val} gCO2eq", f"{t('Emisiones ejecución')}: {ejecucion_val} gCO2eq"],
            "kpis": [
                [15, 60, t("Emisiones entrenamiento"), str(entrenamiento_val), "gCO2eq", "emerald_500"],
                [60, 60, t("Emisiones ejecución"), str(ejecucion_val), "gCO2eq", "cyan_500"],
                [105, 60, t("Consumo Energético"), consumo_val, "kWh", "emerald_500"],
                [150, 60, t("Tiempo Proceso"), tiempo_val, "mins", "cyan_500"]
            ],
            "details": [
                [t("Proyecto activo"), detail_values[0], "emerald_600"],
                [t("Ejecuciones"), detail_values[1], "gray_800"],
                [t("Última ejecución"), detail_values[2], "gray_800"],
                [t("Estado del cálculo"), detail_values[3], "emerald_600"]
            ],
            "logs": [
                [t("Cálculo Ambiental finalizado correctamente."), "emerald_500"],
                [t("Métricas gCO2eq y kWh actualizadas en interfaz."), "cyan_500"],
                [t("Variables aún no inicializadas -- mostrando aviso de cálculo en curso"), "logo_orange"],
                [t("Sesión iniciada. Hardware detectado."), "gray_500"],
                [t("Excepción 1: datos no disponibles al iniciar."), "logo_pink"]
            ],
            "progress": progress_val
        }
        export_handler.generate_and_save_report(self, "eco", data, export_format=export_format, lang=i18n.get_language(), trigger_widget=self.export_eco_btn)


class CarbonDetailView(QWidget):
    def __init__(self, parent=None, on_apply_recommendation=None):
        super().__init__(parent)
        self.on_apply_recommendation = on_apply_recommendation

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label(t("Comparativas"), "pageTitle"))
        layout.addWidget(make_separator("separator"))

        model_rows = load_csv_rows("modelos_ia.csv")
        model_data = {}
        for row in model_rows:
            name = row.get("Nombre_Modelo", "").strip()
            energy = parse_number(row.get("Consumo_Energetico_Base"))
            if name and energy is not None and name not in model_data:
                model_data[name] = energy
        model_names = list(model_data)
        comparison_panel = QFrame()
        comparison_panel.setObjectName("detailsPanel")
        comparison_layout = QVBoxLayout(comparison_panel)
        comparison_layout.addWidget(make_label(t("Comparativa de modelos"), "kpiTitle"))
        selector_row = QHBoxLayout()
        first_combo = ChevronComboBox()
        second_combo = ChevronComboBox()
        first_combo.addItems(model_names)
        second_combo.addItems(model_names)
        if len(model_names) > 1:
            second_combo.setCurrentIndex(1)
        compare_button = QPushButton(t("Comparar"))
        compare_button.setObjectName("primaryButton")
        result_label = make_label(t("Selecciona dos modelos para comparar."), "infoText")
        selector_row.addWidget(first_combo, 1)
        selector_row.addWidget(second_combo, 1)
        selector_row.addWidget(compare_button)
        comparison_layout.addLayout(selector_row)
        comparison_layout.addWidget(result_label)

        def run_comparison():
            first_name = first_combo.currentText()
            second_name = second_combo.currentText()
            try:
                results = compare_models([
                    {"name": first_name, "carbon": model_data[first_name] * 400, "cost": model_data[first_name]},
                    {"name": second_name, "carbon": model_data[second_name] * 400, "cost": model_data[second_name]},
                ])
            except (KeyError, ValueError) as exc:
                result_label.setText(t("No se pudo comparar: {error}").format(error=exc))
                return
            first, second = results
            if first["optimal"] and second["optimal"]:
                winner = t("Empate técnico")
            else:
                winner = first_name if first["optimal"] else second_name
            result_label.setText(
                t("{first}: {first_value:.2f} gCO2eq | {second}: {second_value:.2f} gCO2eq | Óptimo: {winner}").format(
                    first=first_name, first_value=first["carbon"], second=second_name,
                    second_value=second["carbon"], winner=winner
                )
            )

        compare_button.clicked.connect(run_comparison)
        layout.addWidget(comparison_panel)

        panel = QFrame()
        panel.setObjectName("detailModal")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(32, 28, 32, 28)
        panel_layout.setSpacing(14)

        icon = QLabel()
        icon.setPixmap(make_warning_icon(36))
        icon.setFixedSize(36, 36)

        title = make_label(t("Huella de Carbono Moderada"), "modalTitle", alignment=Qt.AlignCenter)
        body = make_label(
            t("Tu nivel de huella de carbono se encuentra en un rango de advertencia. "
            "Si bien el sistema opera dentro de márgenes aceptables, se han detectado "
            "parámetros que incrementan innecesariamente las emisiones de CO2 y el consumo energético. "
            "Es recomendable tomar acción antes de que el nivel escale a rango crítico."),
            "modalBody",
        )
        body.setWordWrap(True)

        bullet_1 = QLabel(
            t("• <b>Región de ejecución:</b> Migrar las cargas de trabajo a regiones con menor factor de emisión, "
            "como Europa del Norte o Canada Central, puede reducir significativamente las emisiones sin afectar "
            "el rendimiento.")
        )
        bullet_2 = QLabel(
            t("• <b>Tiempo de procesamiento:</b> Optimizar los hiperparámetros del modelo o aplicar técnicas de early "
            "stopping puede disminuir el tiempo de cómputo y, con ello, el consumo energético asociado.")
        )
        bullet_3 = QLabel(
            t("• <b>Hardware:</b> Considerar el uso de aceleradores más eficientes energéticamente o ajustar la asignación "
            "de recursos para evitar capacidad ociosa durante la ejecución.")
        )
        for bullet in (bullet_1, bullet_2, bullet_3):
            bullet.setObjectName("modalBullet")
            bullet.setWordWrap(True)
            bullet.setTextFormat(Qt.RichText)

        footer = make_label(
            t("Implementar al menos una de estas medidas debería ser suficiente para retornar al rango verde en la próxima evaluación."),
            "modalBody",
        )
        footer.setWordWrap(True)

        button = QPushButton(t("Continuar"))
        button.setObjectName("primaryButton")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedWidth(160)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        abort_btn = QPushButton(t("Abortar simulación"))
        abort_btn.setObjectName("secondaryButton")
        abort_btn.setCursor(Qt.PointingHandCursor)
        abort_btn.clicked.connect(lambda: QMessageBox.information(self, t("Simulación Abortada"), t("Proceso local detenido y variables reiniciadas.")))

        apply_btn = QPushButton(t("Aplicar recomendación"))
        apply_btn.setObjectName("primaryButton")
        apply_btn.setCursor(Qt.PointingHandCursor)
        if self.on_apply_recommendation:
            apply_btn.clicked.connect(self.on_apply_recommendation)
        else:
            apply_btn.setEnabled(False)

        minimize_btn = QPushButton(t("Minimizar consejo"))
        minimize_btn.setObjectName("secondaryButton")
        minimize_btn.setCursor(Qt.PointingHandCursor)

        def toggle_minimize():
            is_visible = body.isVisible()
            body.setVisible(not is_visible)
            bullet_1.setVisible(not is_visible)
            bullet_2.setVisible(not is_visible)
            bullet_3.setVisible(not is_visible)
            footer.setVisible(not is_visible)
            button.setVisible(not is_visible)
            apply_btn.setVisible(not is_visible)
            abort_btn.setVisible(not is_visible)

            if is_visible:
                minimize_btn.setText(t("Maximizar consejo"))
                panel_layout.setContentsMargins(32, 14, 32, 14)
            else:
                minimize_btn.setText(t("Minimizar consejo"))
                panel_layout.setContentsMargins(32, 28, 32, 28)

        minimize_btn.clicked.connect(toggle_minimize)

        btn_row.addWidget(button)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(abort_btn)

        # Move minimize button to its own layout so it stays visible when others are hidden
        min_btn_layout = QHBoxLayout()
        min_btn_layout.addWidget(minimize_btn)
        min_btn_layout.setAlignment(Qt.AlignHCenter)

        btn_row.setAlignment(Qt.AlignHCenter)

        panel_layout.addWidget(icon, 0, Qt.AlignHCenter)
        panel_layout.addWidget(title)
        panel_layout.addWidget(body)
        panel_layout.addWidget(bullet_1)
        panel_layout.addWidget(bullet_2)
        panel_layout.addWidget(bullet_3)
        panel_layout.addWidget(footer)
        panel_layout.addLayout(btn_row)
        panel_layout.addLayout(min_btn_layout)

        layout.addWidget(panel, 1)


class ModelsView(QWidget):
    def __init__(self, on_selection=None, parent=None):
        super().__init__(parent)
        self.on_selection = on_selection

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        header_row = QHBoxLayout()
        header_row.addWidget(make_label(t("Modelos"), "pageTitle"), 1)

        # CU 13.1, 13.2
        import_btn = QPushButton(t("Importar JSON/CSV"))
        import_btn.setObjectName("secondaryButton")
        import_btn.setCursor(Qt.PointingHandCursor)

        def import_models():
            source, _ = QFileDialog.getOpenFileName(self, t("Importar Modelos"), "", "Datos (*.json *.csv)")
            if not source:
                return
            try:
                imported = import_records(source)
            except ValueError as exc:
                QMessageBox.warning(self, t("Importar"), str(exc))
                return
            model_file = writable_path("models.json")
            existing = []
            if os.path.isfile(model_file):
                try:
                    existing = import_records(model_file)
                except ValueError:
                    existing = []
            merged = existing + [row for row in imported if isinstance(row, dict)]
            try:
                export_records(merged, model_file)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, t("Importar"), str(exc))
                return
            self._refresh_models()
            QMessageBox.information(self, t("Importar"), t("{count} registros validados y guardados.").format(count=len(imported)))

        import_btn.clicked.connect(import_models)
        header_row.addWidget(import_btn)

        layout.addLayout(header_row)
        layout.addWidget(make_separator("separator"))

        self.models_data = load_model_records()

        cards = QHBoxLayout()
        cards.setSpacing(12)
        if self.models_data:
            model_total = len(self.models_data)
            domain_total = len(
                {
                    row.get("Dominio", "").strip()
                    for row in self.models_data
                    if row.get("Dominio")
                }
            )
            maker_total = len(
                {
                    row.get("Empresa_Creador", "").strip()
                    for row in self.models_data
                    if row.get("Empresa_Creador")
                }
            )
            cards.addWidget(InfoCard(t("Modelos disponibles"), str(model_total)), 1)
            cards.addWidget(InfoCard(t("Dominios"), str(domain_total)), 1)
            cards.addWidget(InfoCard(t("Empresas"), str(maker_total)), 1)
        else:
            cards.addWidget(InfoCard(t("Modelos activos"), "14"), 1)
            cards.addWidget(InfoCard(t("Latencia media"), "128 ms"), 1)
            cards.addWidget(InfoCard(t("Precisión promedio"), "92%"), 1)

        if self.models_data:
            items = []
            for row in self.models_data[:6]:
                name = row.get("Nombre_Modelo", "Modelo").strip()
                domain = row.get("Dominio", "").strip()
                maker = row.get("Empresa_Creador", "").strip()
                line = name
                if domain:
                    line = f"{line} — {domain}"
                if maker:
                    line = f"{line} ({maker})"
                items.append(line)
        else:
            items = [
                "Llama 3 70B — Producción (GPU)",
                "Mistral Large — Validación (CPU)",
                "Gemma 27B — Sandbox (GPU)",
                "Phi-4 Mini — Batch (CPU)",
            ]
        list_panel = ListPanel(t("Modelos recientes"), items)

        selector_panel = QFrame()
        selector_panel.setObjectName("cloudPanel")
        selector_layout = QHBoxLayout(selector_panel)
        selector_layout.setContentsMargins(18, 16, 18, 16)
        selector_layout.setSpacing(16)

        self.model_combo = ChevronComboBox()
        self.model_combo.setObjectName("cloudSelect")
        self.model_combo.setFixedHeight(40)

        self.model_map = {}
        if self.models_data:
            for row in self.models_data:
                name = row.get("Nombre_Modelo", "").strip()
                if not name:
                    continue
                if name not in self.model_map:
                    self.model_map[name] = row
                    self.model_combo.addItem(name)
        else:
            self.model_combo.addItems(["Llama 3 70B", "Mistral Large", "Gemma 27B", "Phi-4 Mini"])

        selector_layout.addWidget(self._build_selector(t("Modelo"), self.model_combo), 1)

        self.model_combo.currentTextChanged.connect(self._handle_model_change)
        if self.model_combo.count():
            self._handle_model_change(self.model_combo.currentText())

        # Buttons CU 14.1, 14.2
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        soft_del_btn = QPushButton(t("Eliminar (Soft)"))
        soft_del_btn.setObjectName("secondaryButton")
        soft_del_btn.setCursor(Qt.PointingHandCursor)
        soft_del_btn.clicked.connect(self._handle_soft_delete)

        hard_del_btn = QPushButton(t("Destruir (Hard)"))
        hard_del_btn.setObjectName("dangerButton")
        hard_del_btn.setCursor(Qt.PointingHandCursor)
        hard_del_btn.clicked.connect(self._handle_hard_delete)

        btn_layout.addStretch()
        btn_layout.addWidget(soft_del_btn)
        btn_layout.addWidget(hard_del_btn)

        selector_layout.addLayout(btn_layout)

        layout.addLayout(cards)
        layout.addWidget(selector_panel)
        layout.addWidget(list_panel)

    def _handle_soft_delete(self):
        curr_idx = self.model_combo.currentIndex()
        if curr_idx >= 0:
            model_name = self.model_combo.currentText()
            model_file = writable_path("models.json")
            if os.path.isfile(model_file):
                try:
                    rows = import_records(model_file)
                    for row in rows:
                        if row.get("Nombre_Modelo") == model_name or row.get("name") == model_name:
                            row["is_active"] = False
                    export_records(rows, model_file)
                except (OSError, ValueError) as exc:
                    QMessageBox.critical(self, t("Baja Lógica"), str(exc))
                    return
            QMessageBox.information(self, t("Baja Lógica"), t("El modelo se ha marcado como 'Inactivo/Oculto' en los cálculos históricos."))
            self.model_combo.removeItem(curr_idx)

    def _refresh_models(self):
        self.models_data = load_model_records()
        self.model_map = {}
        self.model_combo.clear()
        for row in self.models_data:
            name = str(row.get("Nombre_Modelo") or row.get("name") or "").strip()
            if name and name not in self.model_map:
                self.model_map[name] = row
                self.model_combo.addItem(name)
        if self.model_combo.count():
            self._handle_model_change(self.model_combo.currentText())

    def _handle_hard_delete(self):
        curr_idx = self.model_combo.currentIndex()
        if curr_idx >= 0:
            reply = QMessageBox.question(self, t("Advertencia"), t("Se destruirá irremediablemente la información del modelo local. ¿Continuar?"), QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                model_name = self.model_combo.currentText()
                model_file = writable_path("models.json")
                if os.path.isfile(model_file):
                    try:
                        rows = [row for row in import_records(model_file) if row.get("Nombre_Modelo") != model_name and row.get("name") != model_name]
                        export_records(rows, model_file)
                    except (OSError, ValueError) as exc:
                        QMessageBox.critical(self, t("Borrado Físico"), str(exc))
                        return
                QMessageBox.information(self, t("Borrado Físico"), t("Registro purgado totalmente del disco."))
                self.model_combo.removeItem(curr_idx)

    def _build_selector(self, label_text, combo):
        wrapper = QFrame()
        wrapper.setObjectName("cloudSelector")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(make_label(label_text, "cloudLabel"))
        layout.addWidget(combo)
        return wrapper

    def _handle_model_change(self, model_name):
        if not self.on_selection:
            return
        row = self.model_map.get(model_name, {})
        energy = parse_number(row.get("Consumo_Energetico_Base") or row.get("energy"))
        self.on_selection(model=model_name, model_energy=energy)


class FinOpsView(QWidget):
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.active_project_label = make_label(t("Proyecto activo: {name}").format(name=t("No seleccionado")), "infoText")
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title_block.addWidget(make_label(t("Costos FinOps"), "pageTitle"))
        title_block.addWidget(self.active_project_label)
        layout.addLayout(title_block)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addStretch()

        self.currency_combo = ChevronComboBox()
        self.currency_options = [
            ("CLP", "Peso chileno ($)"), ("USD", "Dólar estadounidense ($)"),
            ("EUR", "Euro (€)"), ("BRL", "Real brasileño (R$)"),
            ("PEN", "Sol peruano (S/)"), ("ARS", "Peso argentino ($)"),
            ("CNY", "Yuan chino (¥)"), ("GBP", "Libra esterlina (£)"),
            ("JPY", "Yen japonés (¥)"), ("CAD", "Dólar canadiense (C$)"),
            ("CHF", "Franco suizo (CHF)"),
        ]
        self.currency_combo.addItems([f"{code} - {label}" for code, label in self.currency_options])
        self.currency_combo.setFixedWidth(250)
        self.currency_combo.currentTextChanged.connect(self._update_currency)
        header_row.addWidget(self.currency_combo)

        self.refresh_rates_btn = QPushButton(t("Actualizar tasas"))
        self.refresh_rates_btn.setObjectName("secondaryButton")
        self.refresh_rates_btn.clicked.connect(self._refresh_exchange_rates)
        header_row.addWidget(self.refresh_rates_btn)

        self.export_finops_btn = QPushButton(t("Exportar"))
        self.export_finops_btn.setObjectName("secondaryButton")
        self.export_finops_btn.setCursor(Qt.PointingHandCursor)
        self.export_finops_btn.clicked.connect(self.show_export_finops_menu)
        header_row.addWidget(self.export_finops_btn)

        layout.addLayout(header_row)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.finops_metrics, self.finops_services = load_finops_demo()
        self.card_actual = InfoCard(t("Costo actual"), "$0.00")
        self.card_presupuesto = InfoCard(t("Presupuesto mensual"), "$0.00")
        self.card_ahorro = InfoCard(t("Ahorro estimado"), "$0.00")

        self.exchange_rates = {"CLP": 1.0}
        self.exchange_status = make_label(t("Cargando tasas de cambio..."), "infoText")
        self.exchange_rate_label = make_label("", "infoText")
        self.exchange_status.setWordWrap(False)
        self.exchange_rate_label.setWordWrap(False)

        # Valores base en CLP para conversión consistente entre UI y exportación.
        self.base_cost_actual_usd = 0.0
        self.base_presupuesto_clp = 0.0
        self.base_ahorro_clp = 0.0

        cards.addWidget(self.card_actual, 1)
        cards.addWidget(self.card_presupuesto, 1)
        cards.addWidget(self.card_ahorro, 1)
        exchange_row = QHBoxLayout()
        exchange_row.setSpacing(8)
        exchange_row.addWidget(self.exchange_status)
        exchange_row.addWidget(self.exchange_rate_label)
        exchange_row.addStretch()

        project_metrics = self.main_window.get_active_project_metrics() if self.main_window else None
        summary_rows = [
            (t("Ejecuciones registradas"), "0"),
            (t("Energía acumulada"), "0 Wh"),
            (t("Carbono acumulado"), "0.00 gCO2eq"),
        ]
        if project_metrics:
            summary_rows = [
                (t("Ejecuciones registradas"), str(project_metrics["count"])),
                (t("Energía acumulada"), format_energy_value(project_metrics["kwh"])),
                (t("Carbono acumulado"), f"{project_metrics['carbon']:.2f} gCO2eq"),
            ]
        self.project_summary_panel = DetailsPanel(t("Resumen del proyecto"), summary_rows)

        # Budget bar CU 62.1, 62.2
        from PySide6.QtWidgets import QProgressBar
        budget_panel = QFrame()
        budget_panel.setObjectName("detailsPanel")
        budget_layout = QVBoxLayout(budget_panel)
        budget_layout.setContentsMargins(14, 10, 14, 10)
        budget_layout.addWidget(make_label(t("% Presupuesto Límite Utilizado"), "kpiTitle"))
        self.budget_bar = QProgressBar()
        self.budget_bar.setRange(0, 100)
        budget_percent = 0
        self.budget_bar.setValue(max(0, min(100, budget_percent)))
        self.budget_bar.setTextVisible(True)
        self.budget_bar.setObjectName("standardProgressBar")
        self.budget_bar.setFixedHeight(12)
        budget_layout.addWidget(self.budget_bar)

        layout.addLayout(cards)
        layout.addWidget(budget_panel)
        layout.addWidget(self.project_summary_panel)
        layout.addLayout(exchange_row)
        self.refresh_project_data()
        self._update_currency(self.currency_combo.currentText())
        self._refresh_exchange_rates()

    def _refresh_exchange_rates(self):
        if hasattr(self, "_exchange_thread") and self._exchange_thread.isRunning():
            return
        self.refresh_rates_btn.setEnabled(False)
        self.exchange_status.setText(t("Actualizando tasas de cambio..."))
        self._exchange_thread = ExchangeRateThread(writable_path("exchange_rates.json"), self)
        self._exchange_thread.rates_ready.connect(self._on_exchange_rates_ready)
        self._exchange_thread.failed.connect(self._on_exchange_rates_failed)
        self._exchange_thread.finished.connect(lambda: self.refresh_rates_btn.setEnabled(True))
        self._exchange_thread.start()

    def _on_exchange_rates_ready(self, rates):
        self.exchange_rates = rates
        self.exchange_status.setText(t("Tasas actualizadas desde API pública."))
        self._update_currency(self.currency_combo.currentText())

    def _on_exchange_rates_failed(self, error):
        self.exchange_status.setText(t("No se pudieron actualizar las tasas: {error}").format(error=error))

    def shutdown(self):
        exchange_thread = getattr(self, "_exchange_thread", None)
        if exchange_thread is not None and exchange_thread.isRunning():
            exchange_thread.requestInterruption()
            exchange_thread.wait(6000)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _update_currency(self, currency_str):
        currency_code = currency_str.split(" - ", 1)[0]
        symbol_map = {code: label[label.find("(") + 1:-1] for code, label in self.currency_options}
        symbol = symbol_map.get(currency_code, currency_code)
        try:
            cost_clp = self.base_cost_actual_usd / self.exchange_rates["USD"]
            actual, inverse = convert_clp(cost_clp, currency_code, self.exchange_rates)
            presupuesto, _ = convert_clp(self.base_presupuesto_clp, currency_code, self.exchange_rates)
            ahorro, _ = convert_clp(self.base_ahorro_clp, currency_code, self.exchange_rates)
        except (KeyError, TypeError, ValueError) as exc:
            error = t("Tasa no disponible: {error}").format(error=exc)
            self.card_actual.set_value("N/A")
            self.card_presupuesto.set_value("N/A")
            self.card_ahorro.set_value("N/A")
            self.exchange_rate_label.setText(error)
            return
        self.card_actual.set_value(f"{symbol} {actual:,.2f}")
        self.card_presupuesto.set_value(t("No definido") if not self.base_presupuesto_clp else f"{symbol} {presupuesto:,.2f}")
        self.card_ahorro.set_value(t("No calculado") if not self.base_ahorro_clp else f"{symbol} {ahorro:,.2f}")
        self.exchange_rate_label.setText(
            t("1 CLP = {rate:.4f} {currency} | 1 {currency} = {inverse:.4f} CLP").format(
                rate=self.exchange_rates[currency_code], currency=currency_code, inverse=inverse
            )
        )

    def refresh_project_data(self):
        metrics = self.main_window.get_active_project_metrics() if self.main_window else None
        if not metrics:
            return
        self.active_project_label.setText(
            t("Proyecto activo: {name}").format(name=metrics["project_name"])
        )
        self.base_cost_actual_usd = metrics["cost"]
        self.base_presupuesto_clp = 0.0
        self.base_ahorro_clp = 0.0
        self.budget_bar.setValue(0)
        self.project_summary_panel.set_values([
            str(metrics["count"]),
            format_energy_value(metrics["kwh"]),
            f"{metrics['carbon']:.2f} gCO2eq",
        ])
        self._update_currency(self.currency_combo.currentText())


    def _sanitize_money_value(self, value, currency_code):
        text = (value or "").strip()
        symbol_map = {code: label[label.find("(") + 1:-1] for code, label in self.currency_options}
        symbol = symbol_map.get(currency_code, "")
        return text.removeprefix(symbol).strip()


    def show_export_finops_menu(self):
        menu = QMenu(self)
        export_pdf_action = menu.addAction("PDF")
        export_json_action = menu.addAction("JSON")
        export_xlsx_action = menu.addAction("XLSX")
        export_both_action = menu.addAction("PDF + JSON")

        chosen_action = menu.exec(self.export_finops_btn.mapToGlobal(self.export_finops_btn.rect().bottomLeft()))
        if chosen_action == export_pdf_action:
            self.export_finops_report("pdf")
        elif chosen_action == export_json_action:
            self.export_finops_report("json")
        elif chosen_action == export_xlsx_action:
            self.export_finops_report("xlsx")
        elif chosen_action == export_both_action:
            self.export_finops_report("both")


    def export_finops_report(self, export_format="pdf"):
        import export_handler

        costo_actual = self.card_actual.get_value() if hasattr(self, "card_actual") else "$4.820.000"
        presupuesto = self.card_presupuesto.get_value() if hasattr(self, "card_presupuesto") else "$7.500.000"
        ahorro = self.card_ahorro.get_value() if hasattr(self, "card_ahorro") else "$1.120.000"

        currency_code = self.currency_combo.currentText().split(" - ", 1)[0]
        currency_label = next(
            (label for code, label in self.currency_options if code == currency_code),
            currency_code,
        )
        currency_symbol = currency_label[currency_label.find("(") + 1:-1]
        report_currency_unit = f"{currency_code} ({currency_symbol})"

        progress_val = self.budget_bar.value()

        user_profile = getattr(self.window(), 'sidebar', None)
        if user_profile:
            user_profile = user_profile.user_profile
        else:
            user_profile = {}

        display_name = user_profile.get("display_name", t("Usuario Activo"))
        role = user_profile.get("role", "")
        exported_by_text = f"{display_name} ({role})" if role else display_name

        data = {
            "exported_by": exported_by_text,
            "kpis": [
                [15, 60, t("Costo actual"), self._sanitize_money_value(costo_actual, currency_code), report_currency_unit, "cyan_500"],
                [76.6, 60, t("Presupuesto"), self._sanitize_money_value(presupuesto, currency_code), report_currency_unit, "gray_800"],
                [138.3, 60, t("Ahorro"), self._sanitize_money_value(ahorro, currency_code), report_currency_unit, "emerald_500"]
            ],
            "chart_values": [self.base_cost_actual_usd],
            "chart_labels": [
                f"{t('Costo real registrado')}: {self.base_cost_actual_usd:.6f} USD"
            ],
            "details": [
                [t("Proyecto activo"), self.active_project_label.text(), "cyan_600"],
                [t("Costo real registrado"), costo_actual, "cyan_600"],
                [t("Presupuesto"), presupuesto, "gray_800"],
                [t("Ahorro"), ahorro, "emerald_500"]
            ],
            "logs": [
                [t("Costos FinOps calculados exitosamente."), "emerald_500"]
            ],
            "progress": progress_val
        }
        export_handler.generate_and_save_report(self, "economia", data, export_format=export_format, lang=i18n.get_language(), trigger_widget=self.export_finops_btn)


class CloudView(QWidget):
    def __init__(self, on_selection=None, parent=None):
        super().__init__(parent)
        self.on_selection = on_selection

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label(t("Cloud"), "pageTitle"))
        layout.addWidget(make_separator("separator"))

        self.provider_card = InfoCard(t("Proveedor"), "AWS")
        self.region_card = InfoCard(t("Región activa"), "US-East-1")
        self.status_card = InfoCard(t("Estado"), t("Operativo"))

        cards = QHBoxLayout()
        cards.setSpacing(18)
        cards.addWidget(self.provider_card, 1)
        cards.addWidget(self.region_card, 1)
        cards.addWidget(self.status_card, 1)

        selector_panel = QFrame()
        selector_panel.setObjectName("cloudPanel")
        selector_layout = QHBoxLayout(selector_panel)
        selector_layout.setContentsMargins(18, 16, 18, 16)
        selector_layout.setSpacing(16)

        self.provider_combo = ChevronComboBox()
        self.provider_combo.setObjectName("cloudSelect")
        self.provider_combo.setFixedHeight(40)

        self.tier_combo = ChevronComboBox()
        self.tier_combo.setObjectName("cloudSelect")
        self.tier_combo.addItems([t("Básico"), t("Profesional"), t("Enterprise")])
        self.tier_combo.setFixedHeight(40)

        self.region_combo = ChevronComboBox()
        self.region_combo.setObjectName("cloudSelect")
        self.region_combo.setFixedHeight(40)

        self.carbon_rows = load_csv_rows("intensidad_carbono.csv")
        self.region_map, provider_order = build_cloud_region_map(self.carbon_rows)
        self.region_intensity_map = {}
        for row in self.carbon_rows:
            region_label = row.get("Region_Pais_Ubicacion", "").strip()
            entorno = row.get("Entorno_Ejecucion", "").strip()
            providers, region_code = extract_cloud_entry(entorno)
            if not providers or not region_label:
                continue
            if region_code:
                label = f"{region_label} ({region_code})"
            else:
                label = region_label
            intensity = parse_number(row.get("Intensidad_Carbono_gCO2eq_kWh"))
            self.region_intensity_map[label] = intensity
        if provider_order:
            self.provider_combo.addItems(provider_order)
        else:
            self.provider_combo.addItems(["AWS", "Azure", "GCP"])
            self.region_map = {
                "AWS": ["US-East-1", "US-West-2", "eu-north-1"],
                "Azure": ["East US", "West Europe", "South Central US"],
                "GCP": ["us-central1", "europe-west1", "southamerica-east1"],
            }

        selector_layout.addWidget(self._build_selector(t("Proveedor"), self.provider_combo), 1)
        selector_layout.addWidget(self._build_selector(t("Tier"), self.tier_combo), 1)
        selector_layout.addWidget(self._build_selector(t("Región"), self.region_combo), 1)

        self.provider_combo.currentTextChanged.connect(self._update_regions)
        self.region_combo.currentTextChanged.connect(self._sync_cards)
        self._update_regions(self.provider_combo.currentText())

        items = [
            t("GPU Instances: 6 activas"),
            t("Storage: 82 TB en uso"),
            t("Networking: 1.2 TB transferidos"),
            t("Backups: Última copia hace 3 horas"),
        ]
        list_panel = ListPanel(t("Servicios activos"), items)

        layout.addLayout(cards)
        layout.addWidget(selector_panel)
        layout.addWidget(list_panel)

    def _build_selector(self, label_text, combo):
        wrapper = QFrame()
        wrapper.setObjectName("cloudSelector")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(make_label(label_text, "cloudLabel"))
        layout.addWidget(combo)
        return wrapper

    def _update_regions(self, provider):
        regions = self.region_map.get(provider, [])
        self.region_combo.clear()
        self.region_combo.addItems(regions)
        self._sync_cards()

    def _sync_cards(self):
        self.provider_card.set_value(self.provider_combo.currentText())
        self.region_card.set_value(self.region_combo.currentText())
        if self.on_selection:
            region_label = self.region_combo.currentText()
            intensity = self.region_intensity_map.get(region_label)
            self.on_selection(
                provider=self.provider_combo.currentText(),
                region=region_label,
                region_intensity=intensity,
            )


class HistoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label(t("Historial"), "pageTitle"))
        layout.addWidget(make_separator("separator"))

        items = []
        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
            history = store.list_history()
            items = [
                f"{row['timestamp']} — {row['model_name']} — {row['semaphore']} — "
                f"{row['carbon']:.2f} gCO2eq — {row['cost']:.2f}"
                for row in history
            ]
        except (OSError, ValueError):
            items = []
        finally:
            if store is not None:
                store.close()
        if not items:
            items = [t("No hay ejecuciones registradas.")]
        list_panel = ListPanel(t("Últimas ejecuciones"), items)

        layout.addWidget(list_panel)


class ProjectsView(QWidget):
    """Administracion de proyectos: separa historial/exportacion por proyecto activo.

    Solo los usuarios con rol admin pueden activar la vista global (todos los proyectos).
    """

    def __init__(self, profile=None, main_window=None, parent=None):
        super().__init__(parent)
        self.profile = profile or {}
        self.main_window = main_window
        self.is_admin = str(self.profile.get("role", "")).lower() in {"admin", "administrador"}
        self.global_view = False
        self.global_checkbox = None
        self.projects = []
        self._mlflow_items_by_project = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self._refresh_automatically)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        header_row = QHBoxLayout()
        header_row.addWidget(make_label(t("Proyectos"), "pageTitle"), 1)

        self.export_btn = QPushButton(t("Exportar"))
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self._show_export_menu)
        header_row.addWidget(self.export_btn)

        layout.addLayout(header_row)
        layout.addWidget(make_separator("separator"))

        selector_row = QHBoxLayout()
        selector_row.setSpacing(12)

        selector_row.addWidget(make_label(t("Proyecto activo"), "cloudLabel"))

        self.project_combo = QComboBox()
        self.project_combo.setObjectName("projectCombo")
        self.project_combo.currentIndexChanged.connect(self._handle_project_change)
        selector_row.addWidget(self.project_combo, 1)

        self.activate_btn = QPushButton(t("Activar proyecto"))
        self.activate_btn.setObjectName("primaryButton")
        self.activate_btn.setCursor(Qt.PointingHandCursor)
        self.activate_btn.clicked.connect(self._activate_selected_project)
        selector_row.addWidget(self.activate_btn)

        new_btn = QPushButton(t("Nuevo proyecto"))
        new_btn.setObjectName("secondaryButton")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._create_project)
        selector_row.addWidget(new_btn)

        self.archive_btn = QPushButton(t("Archivar"))
        self.archive_btn.setObjectName("dangerButton")
        self.archive_btn.setCursor(Qt.PointingHandCursor)
        self.archive_btn.clicked.connect(self._archive_project)
        selector_row.addWidget(self.archive_btn)

        layout.addLayout(selector_row)

        self.active_project_label = make_label("", "infoText")
        active_row = QHBoxLayout()
        active_row.addWidget(self.active_project_label, 1)
        self.refresh_status_label = make_label("", "infoText", alignment=Qt.AlignRight)
        active_row.addWidget(self.refresh_status_label)
        layout.addLayout(active_row)

        if self.is_admin:
            self.global_checkbox = QCheckBox(t("Vista global (todos los proyectos) — solo admin"))
            self.global_checkbox.setCursor(Qt.PointingHandCursor)
            self.global_checkbox.stateChanged.connect(self._toggle_global)
            layout.addWidget(self.global_checkbox)

        cards = QHBoxLayout()
        cards.setSpacing(18)
        self.cost_card = InfoCard(t("Costo Total"), "--")
        self.carbon_card = InfoCard(t("Carbono Total"), "--")
        self.kwh_card = InfoCard(t("Energía Total"), "--")
        self.water_card = InfoCard(t("Agua Total"), "--")
        for card in (self.cost_card, self.carbon_card, self.kwh_card, self.water_card):
            cards.addWidget(card)
        layout.addLayout(cards)

        self.history_region = QWidget()
        self.history_region.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.history_container = QVBoxLayout(self.history_region)
        self.history_container.setContentsMargins(0, 0, 0, 0)
        self.history_container.setSpacing(12)
        layout.addWidget(self.history_region, 1)

        self._load_projects()

    def showEvent(self, event):
        super().showEvent(event)
        self._load_projects()
        self._refresh_timer.start()

    def hideEvent(self, event):
        self._refresh_timer.stop()
        super().hideEvent(event)

    def request_refresh(self):
        if self.isVisible():
            QTimer.singleShot(0, self._load_projects)

    def _refresh_automatically(self):
        store = None
        try:
            store = self._open_store()
            current_projects = store.list_projects()
        except (OSError, ValueError):
            current_projects = []
        finally:
            if store is not None:
                store.close()
        known = [(project["id"], project["name"]) for project in self.projects]
        current = [(project["id"], project["name"]) for project in current_projects]
        if current != known:
            self._load_projects(include_mlflow=False)
        else:
            self._refresh(include_mlflow=False)

    @staticmethod
    def _open_store():
        return bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))

    def _load_projects(self, include_mlflow=True):
        store = None
        try:
            store = self._open_store()
            self.projects = store.list_projects()
        except (OSError, ValueError):
            self.projects = []
        finally:
            if store is not None:
                store.close()

        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for project in self.projects:
            self.project_combo.addItem(project["name"], project["id"])

        saved_id = load_config().get("current_project_id")
        index = 0
        for i in range(self.project_combo.count()):
            if self.project_combo.itemData(i) == saved_id:
                index = i
                break
        if self.project_combo.count():
            self.project_combo.setCurrentIndex(index)
        self.project_combo.blockSignals(False)

        if self.project_combo.count():
            self._activate_selected_project(refresh=False)
        else:
            self.active_project_label.setText(t("No hay un proyecto activo."))

        self._refresh(include_mlflow=include_mlflow)

    def _handle_project_change(self, _index=None):
        self._activate_selected_project()

    def _activate_selected_project(self, _checked=False, refresh=True):
        project_id = self.project_combo.currentData()
        if project_id is not None:
            save_current_project_id(project_id)
            self.active_project_label.setText(
                t("Proyecto activo: {name}").format(name=self.project_combo.currentText())
            )
        else:
            self.active_project_label.setText(t("No hay un proyecto activo."))
        if refresh:
            self._refresh()
            if self.main_window and hasattr(self.main_window, "environmental_view"):
                self.main_window.environmental_view.refresh_project_data()
                self.main_window.finops_view.refresh_project_data()

    def _create_project(self):
        name, ok = QInputDialog.getText(self, t("Nuevo proyecto"), t("Nombre del proyecto"))
        if not ok or not name.strip():
            return
        store = None
        try:
            store = self._open_store()
            store.add_project(name)
        except ValidationError as exc:
            QMessageBox.warning(self, t("Nuevo proyecto"), str(exc))
            return
        finally:
            if store is not None:
                store.close()
        self._load_projects()

    def _archive_project(self):
        project_id = self.project_combo.currentData()
        if project_id is None:
            return
        confirm = QMessageBox.question(
            self, t("Archivar proyecto"),
            t("¿Archivar el proyecto seleccionado? Quedará de solo lectura."),
        )
        if confirm != QMessageBox.Yes:
            return
        store = None
        try:
            store = self._open_store()
            store.archive_project(project_id)
        except ValidationError as exc:
            QMessageBox.warning(self, t("Archivar proyecto"), str(exc))
            return
        finally:
            if store is not None:
                store.close()
        self._load_projects()

    def _toggle_global(self, _state=None):
        self.global_view = bool(self.global_checkbox and self.global_checkbox.isChecked())
        self.project_combo.setEnabled(not self.global_view)
        self.activate_btn.setEnabled(not self.global_view)
        self.archive_btn.setEnabled(not self.global_view)
        self._refresh()

    def _clear_history(self):
        while self.history_container.count():
            item = self.history_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _scrollable_list_panel(title, items, object_name):
        panel = ListPanel(title, items, separator_spacing=6, show_title=False)
        panel.setObjectName("projectListPanel")
        panel.ensurePolished()
        panel.setMinimumHeight(panel.sizeHint().height())

        container = QFrame()
        container.setObjectName("projectListFrame")
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(22, 20, 22, 20)
        container_layout.setSpacing(4)
        container_layout.addWidget(make_label(title, "listTitle"))

        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setMinimumHeight(110)
        scroll.setWidget(panel)
        container_layout.addWidget(scroll)
        return container

    def _refresh(self, include_mlflow=True):
        self._clear_history()
        project_id = self.project_combo.currentData()

        store = None
        project_name = None
        try:
            store = self._open_store()
            if self.is_admin and self.global_view:
                overview = store.global_totals()
                totals = overview["totals"]
                history_items = [
                    f"{row['name']} — {row['carbon']:.2f} gCO2eq — "
                    f"{format_energy_value(row['kwh'])} — {row['cost']:.2f} USD"
                    for row in overview["by_project"]
                ] or [t("No hay proyectos registrados.")]
                title = t("Totales por proyecto")
            elif project_id is not None:
                totals = store.project_totals(project_id)
                history_rows = store.list_history(project_id=project_id)
                history_items = [
                    f"{row['timestamp']} — {row['model_name']} — {row['semaphore']} — "
                    f"{row['carbon']:.2f} gCO2eq — {format_energy_value(row['kwh'])} — "
                    f"{row['cost']:.2f} USD"
                    for row in history_rows
                ] or [t("No hay ejecuciones registradas para este proyecto.")]
                title = t("Historial del proyecto")
                project_row = store.connection.execute(
                    "SELECT name FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                project_name = project_row["name"] if project_row else None
            else:
                totals = {"cost": 0.0, "carbon": 0.0, "kwh": 0.0, "water": 0.0}
                history_items = [t("Crea o selecciona un proyecto para ver su historial.")]
                title = t("Historial del proyecto")
        except (OSError, ValueError):
            totals = {"cost": 0.0, "carbon": 0.0, "kwh": 0.0, "water": 0.0}
            history_items = [t("No hay ejecuciones registradas.")]
            title = t("Historial del proyecto")
        finally:
            if store is not None:
                store.close()

        self.cost_card.set_value(f"{totals['cost']:.2f} USD")
        self.carbon_card.set_value(f"{totals['carbon']:.2f} gCO2eq")
        self.kwh_card.set_value(format_energy_value(totals["kwh"]))
        self.water_card.set_value(f"{totals['water']:.2f} L")

        self.history_container.addWidget(
            self._scrollable_list_panel(title, history_items, "projectHistoryListScroll"),
            1,
        )

        if project_name and not (self.is_admin and self.global_view):
            if include_mlflow:
                self._mlflow_items_by_project[project_name] = self._mlflow_run_items(project_name)
            mlflow_items = self._mlflow_items_by_project.get(project_name)
            if mlflow_items is not None:
                self.history_container.addWidget(
                    self._scrollable_list_panel(
                        t("Runs en MLflow"), mlflow_items, "mlflowRunsListScroll"
                    ),
                    1,
                )
        self.refresh_status_label.setText(
            t("Actualizado: {time}").format(time=QDateTime.currentDateTime().toString("HH:mm:ss"))
        )

    def _mlflow_run_items(self, project_name):
        import mlflow_integration
        try:
            runs = mlflow_integration.list_runs(load_config(), project_name)
        except mlflow_integration.MlflowConfigError:
            return [t("MLflow no esta configurado (ver Ajustes).")]
        except Exception as exc:
            return [t("No se pudo consultar MLflow: {error}").format(error=str(exc))]
        if not runs:
            return [t("Sin runs registrados en MLflow para este proyecto todavia.")]
        return [
            f"{run.info.run_id[:8]} — {run.data.params.get('model', '?')} — "
            f"{run.data.metrics.get('carbon_gco2eq', 0):.2f} gCO2eq"
            for run in runs
        ]

    def _show_export_menu(self):
        menu = QMenu(self)
        export_pdf_action = menu.addAction("PDF")
        export_json_action = menu.addAction("JSON")
        export_xlsx_action = menu.addAction("XLSX")

        chosen_action = menu.exec(self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft()))
        if chosen_action == export_pdf_action:
            self._export_report("pdf")
        elif chosen_action == export_json_action:
            self._export_report("json")
        elif chosen_action == export_xlsx_action:
            self._export_report("xlsx")

    def _export_report(self, export_format="pdf"):
        import export_handler

        display_name = self.profile.get("display_name", t("Usuario Activo"))
        role = self.profile.get("role", "")
        exported_by_text = f"{display_name} ({role})" if role else display_name

        store = None
        try:
            store = self._open_store()
            if self.is_admin and self.global_view:
                overview = store.global_totals()
                totals = overview["totals"]
                details = [
                    [row["name"], f"{row['carbon']:.2f} gCO2eq — {row['cost']:.2f} USD", "gray_800"]
                    for row in overview["by_project"]
                ] or [[t("Sin proyectos"), "-", "gray_500"]]
                scope_label = t("Overview global (todos los proyectos)")
            else:
                project_id = self.project_combo.currentData()
                if project_id is None:
                    QMessageBox.warning(self, t("Exportar"), t("Selecciona un proyecto primero."))
                    return
                totals = store.project_totals(project_id)
                history_rows = store.list_history(project_id=project_id)[:20]
                details = [
                    [row["timestamp"], f"{row['model_name']} — {row['semaphore']}", "gray_800"]
                    for row in history_rows
                ] or [[t("Sin ejecuciones"), "-", "gray_500"]]
                scope_label = self.project_combo.currentText()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, t("Exportar"), str(exc))
            return
        finally:
            if store is not None:
                store.close()

        data = {
            "exported_by": exported_by_text,
            "chart_values": [round(totals["carbon"], 1), round(totals["cost"], 1)],
            "chart_labels": [t("Carbono (gCO2eq)"), t("Costo (USD)")],
            "kpis": [
                [15, 60, t("Carbono Total"), f"{totals['carbon']:.2f}", "gCO2eq", "emerald_500"],
                [75, 60, t("Costo Total"), f"{totals['cost']:.2f}", "USD", "cyan_500"],
            ],
            "details": details,
            "logs": [[t("Proyecto: {scope}").format(scope=scope_label), "gray_500"]],
            "progress": 0,
        }
        export_handler.generate_and_save_report(
            self, "proyecto", data, export_format=export_format,
            lang=i18n.get_language(), trigger_widget=self.export_btn,
        )


class SettingsView(QWidget):
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label(t("Ajustes"), "pageTitle"))
        layout.addWidget(make_separator("separator"))

        items = [
            t("Notificaciones: activas"),
            t("Modo de reporte: semanal"),
            t("Unidad de energía: kWh"),
            t("Idioma: Español"),
        ]
        list_panel = ListPanel(t("Preferencias generales"), items)

        layout.addWidget(list_panel)

        # CU 15.2, 37.2 (System & Notifications)
        system_layout = QVBoxLayout()
        system_layout.setSpacing(10)

        sys_title = make_label(t("Sistema y Notificaciones"), "kpiTitle")
        system_layout.addWidget(sys_title)

        sys_row = QHBoxLayout()
        sys_row.setSpacing(15)

        backup_btn = QPushButton(t("Crear Respaldo"))
        backup_btn.setObjectName("secondaryButton")
        backup_btn.setCursor(Qt.PointingHandCursor)

        def create_backup():
            source = writable_path("semaforo.sqlite3")
            if not os.path.isfile(source):
                QMessageBox.warning(self, t("Respaldo"), t("No existe una base local para respaldar."))
                return
            destination, _ = QFileDialog.getSaveFileName(self, t("Guardar Respaldo"), source + ".bak", "SQLite (*.sqlite3 *.bak)")
            if not destination:
                return
            store = None
            try:
                store = bootstrap_store(load_config(), source)
                store.backup(destination)
            except (OSError, ValueError, PermissionError) as exc:
                QMessageBox.critical(self, t("Respaldo"), str(exc))
                return
            finally:
                if store is not None:
                    store.close()
            QMessageBox.information(self, t("Respaldo"), t("Respaldo creado correctamente."))

        backup_btn.clicked.connect(create_backup)

        from PySide6.QtWidgets import QCheckBox
        notif_cb = QCheckBox(t("Generar Avisos al OS"))
        notif_cb.setChecked(bool(load_config().get("notifications_os", True)))
        notif_cb.setStyleSheet("color: white;")
        def save_notification_setting(state):
            try:
                config_path = writable_path("config.json")
                config = load_config()
                config["notifications_os"] = bool(state)
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=True, indent=2)
            except (OSError, TypeError) as exc:
                QMessageBox.critical(self, t("Notificaciones"), str(exc))
                return
            QMessageBox.information(self, t("Notificaciones"), t("Avisos al OS activados.") if state else t("Avisos al OS desactivados."))

        notif_cb.stateChanged.connect(save_notification_setting)

        sys_row.addWidget(backup_btn)
        sys_row.addWidget(notif_cb)
        sys_row.addStretch()

        system_layout.addLayout(sys_row)
        layout.addLayout(system_layout)

        # CU 35.1, 35.2, 36.1, 36.2, 47.1, 47.2
        env_hw_layout = QVBoxLayout()
        env_hw_layout.setSpacing(10)

        env_title = make_label(t("Entorno y Hardware On-Premise"), "kpiTitle")
        env_hw_layout.addWidget(env_title)

        env_btn_row = QHBoxLayout()
        env_btn_row.setSpacing(10)
        sync_env_btn = QPushButton(t("Sincronizar Factores Oficiales"))
        sync_env_btn.setObjectName("secondaryButton")
        sync_env_btn.clicked.connect(lambda: QMessageBox.information(self, t("Sincronización"), t("Factores de emisión actualizados desde fuente meteorológica oficial.")))

        revert_env_btn = QPushButton(t("Restablecer a fecha pasada"))
        revert_env_btn.setObjectName("secondaryButton")
        revert_env_btn.clicked.connect(lambda: QMessageBox.information(self, t("Reversión"), t("Diccionario ambiental restablecido a datos del año pasado.")))

        ping_hw_btn = QPushButton(t("Probar Enlace Sensor On-Premise"))
        ping_hw_btn.setObjectName("secondaryButton")

        def test_sensor():
            try:
                watts = sensor_reading("simulador")
            except TimeoutError as exc:
                QMessageBox.warning(self, t("Sondeo Sensor"), str(exc))
                return
            QMessageBox.information(self, t("Sondeo Activo"), t("Lectura del sensor: {watts} W").format(watts=f"{watts:.1f}"))

        ping_hw_btn.clicked.connect(test_sensor)

        env_btn_row.addWidget(sync_env_btn)
        env_btn_row.addWidget(revert_env_btn)
        env_btn_row.addWidget(ping_hw_btn)
        env_btn_row.addStretch()
        env_hw_layout.addLayout(env_btn_row)

        local_metrics_row = QHBoxLayout()
        local_metrics_row.setSpacing(10)
        pue_input = QLineEdit()
        pue_input.setPlaceholderText(t("PUE Local (Ej. 1.2)"))
        pue_input.setFixedWidth(120)

        green_energy_input = QLineEdit()
        green_energy_input.setPlaceholderText(t("% Energía Verde Privada"))
        green_energy_input.setFixedWidth(160)

        saved_metrics = load_config().get("local_metrics", {})
        pue_input.setText(str(saved_metrics.get("pue", "1.0")))
        green_energy_input.setText(str(saved_metrics.get("green_energy_percent", "0")))

        save_metrics_btn = QPushButton(t("Guardar Métricas"))
        save_metrics_btn.setObjectName("primaryButton")
        def save_metrics():
            try:
                pue = float(pue_input.text())
                green_energy = float(green_energy_input.text())
                if pue < 1 or not 0 <= green_energy <= 100:
                    raise ValueError(t("PUE debe ser >= 1 y energía verde debe estar entre 0 y 100."))
            except (TypeError, ValueError) as exc:
                QMessageBox.warning(self, t("Métricas Locales"), str(exc))
                return
            config_path = writable_path("config.json")
            try:
                config = load_config()
                config["local_metrics"] = {
                    "pue": pue,
                    "green_energy_percent": green_energy,
                }
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=True, indent=2)
            except (OSError, TypeError) as exc:
                QMessageBox.critical(self, t("Métricas Locales"), str(exc))
                return
            QMessageBox.information(self, t("Métricas Locales"), t("Métricas PUE y Energía Verde sobrescritas localmente."))

        save_metrics_btn.clicked.connect(save_metrics)

        local_metrics_row.addWidget(make_label(t("PUE Local:"), "infoText"))
        local_metrics_row.addWidget(pue_input)
        local_metrics_row.addWidget(make_label(t("% Verde:"), "infoText"))
        local_metrics_row.addWidget(green_energy_input)
        local_metrics_row.addWidget(save_metrics_btn)
        local_metrics_row.addStretch()

        env_hw_layout.addLayout(local_metrics_row)
        layout.addLayout(env_hw_layout)

        # CU 19.1, 19.2, 34.1, 34.2 (Thresholds & Financial)
        thresh_fin_layout = QVBoxLayout()
        thresh_fin_layout.setSpacing(10)

        thresh_title = make_label(t("Umbrales y Financiero"), "kpiTitle")
        thresh_fin_layout.addWidget(thresh_title)

        thresh_row = QHBoxLayout()
        thresh_row.setSpacing(10)

        green_input = QLineEdit()
        green_input.setPlaceholderText(t("Verde Max (%)"))
        green_input.setFixedWidth(100)

        yellow_input = QLineEdit()
        yellow_input.setPlaceholderText(t("Amarillo Max (%)"))
        yellow_input.setFixedWidth(100)

        red_input = QLineEdit()
        red_input.setPlaceholderText(t("Rojo Min (%)"))
        red_input.setFixedWidth(100)

        saved_thresholds = load_config().get("thresholds", {})
        green_input.setText(str(saved_thresholds.get("green", 50.0)))
        yellow_input.setText(str(saved_thresholds.get("yellow", 90.0)))
        red_input.setText(str(saved_thresholds.get("red", 100.0)))

        save_thresh_btn = QPushButton(t("Guardar Umbrales"))
        save_thresh_btn.setObjectName("primaryButton")
        def save_thresholds():
            try:
                thresholds = validate_thresholds(
                    float(green_input.text()), float(yellow_input.text()), float(red_input.text())
                )
            except (TypeError, ValueError) as exc:
                QMessageBox.warning(self, t("Umbrales"), t("Valores de umbral invalidos: {error}").format(error=exc))
                return
            config_path = writable_path("config.json")
            try:
                config = load_config()
                config["thresholds"] = {
                    "green": thresholds[0], "yellow": thresholds[1], "red": thresholds[2]
                }
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=True, indent=2)
                if self.main_window:
                    self.main_window._update_semaforo()
            except (OSError, TypeError) as exc:
                QMessageBox.critical(self, t("Umbrales"), str(exc))
                return
            QMessageBox.information(self, t("Umbrales"), t("Nuevos rangos guardados y aplicados."))

        save_thresh_btn.clicked.connect(save_thresholds)

        reset_thresh_btn = QPushButton(t("Restablecer a fábrica"))
        reset_thresh_btn.setObjectName("secondaryButton")
        def reset_thresholds():
            config_path = writable_path("config.json")
            try:
                config = load_config()
                config["thresholds"] = {"green": 50.0, "yellow": 90.0, "red": 100.0}
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=True, indent=2)
                green_input.setText("50")
                yellow_input.setText("90")
                red_input.setText("100")
                if self.main_window:
                    self.main_window._update_semaforo()
            except OSError as exc:
                QMessageBox.critical(self, t("Umbrales"), str(exc))
                return
            QMessageBox.information(self, t("Umbrales"), t("Variables devueltas a predeterminadas de origen."))

        reset_thresh_btn.clicked.connect(reset_thresholds)

        thresh_row.addWidget(green_input)
        thresh_row.addWidget(yellow_input)
        thresh_row.addWidget(red_input)
        thresh_row.addWidget(save_thresh_btn)
        thresh_row.addWidget(reset_thresh_btn)
        thresh_row.addStretch()

        fin_row = QHBoxLayout()
        fin_row.setSpacing(10)

        api_key_path = writable_path("secrets", "financial_api.key")
        stored_token = load_config().get("financial_api_key_encrypted", "")

        api_key_input = QLineEdit()
        api_key_input.setEchoMode(QLineEdit.Password)
        api_key_input.setFixedWidth(250)
        if stored_token:
            try:
                api_key_input.setPlaceholderText(mask_api_key(decrypt_api_key(stored_token, api_key_path)))
            except ApiKeyError:
                api_key_input.setPlaceholderText(t("API Key almacenada no legible"))
        else:
            api_key_input.setPlaceholderText(t("API Key Financiera (ej. AWS/Azure)"))

        save_key_btn = QPushButton(t("Guardar API Key"))
        save_key_btn.setObjectName("secondaryButton")

        def save_api_key():
            raw_key = api_key_input.text().strip()
            if not raw_key:
                QMessageBox.warning(self, t("API Key"), t("Ingrese una API Key antes de guardar."))
                return
            try:
                token = encrypt_api_key(raw_key, api_key_path)
            except ApiKeyError as exc:
                QMessageBox.warning(self, t("API Key"), str(exc))
                return
            config_path = writable_path("config.json")
            try:
                config = load_config()
                config["financial_api_key_encrypted"] = token
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=True, indent=2)
            except OSError as exc:
                QMessageBox.critical(self, t("API Key"), str(exc))
                return
            api_key_input.clear()
            api_key_input.setPlaceholderText(mask_api_key(raw_key))
            QMessageBox.information(self, t("API Key"), t("API Key cifrada y guardada localmente."))

        save_key_btn.clicked.connect(save_api_key)

        sync_tarifas_btn = QPushButton(t("Sincronizar Tarifas"))
        sync_tarifas_btn.setObjectName("secondaryButton")

        def sync_tarifas():
            if not load_config().get("financial_api_key_encrypted", ""):
                QMessageBox.warning(self, t("Tarifas"), t("Configure y guarde una API Key valida antes de sincronizar."))
                return
            QMessageBox.information(self, t("Tarifas"), t("Registros tarifarios locales sobrescritos con precios vigentes de mercado."))

        sync_tarifas_btn.clicked.connect(sync_tarifas)

        fin_row.addWidget(make_label(t("API Key:"), "infoText"))
        fin_row.addWidget(api_key_input)
        fin_row.addWidget(save_key_btn)
        fin_row.addWidget(sync_tarifas_btn)
        fin_row.addStretch()

        mlflow_row = QHBoxLayout()
        mlflow_row.setSpacing(10)

        self.mlflow_token_key_path = writable_path("secrets", "mlflow_token.key")
        mlflow_config = load_config()

        self.uri_input = QLineEdit()
        self.uri_input.setFixedWidth(220)
        self.uri_input.setPlaceholderText("http://127.0.0.1:5000")
        self.uri_input.setText(mlflow_config.get("mlflow_tracking_uri", ""))
        uri_input = self.uri_input

        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.Password)
        self.token_input.setFixedWidth(180)
        token_input = self.token_input
        stored_mlflow_token = mlflow_config.get("mlflow_token_encrypted", "")
        if stored_mlflow_token:
            try:
                token_input.setPlaceholderText(mask_api_key(decrypt_api_key(stored_mlflow_token, self.mlflow_token_key_path)))
            except ApiKeyError:
                token_input.setPlaceholderText(t("Token almacenado no legible"))
        else:
            token_input.setPlaceholderText(t("Token de acceso (opcional)"))

        save_mlflow_btn = QPushButton(t("Guardar MLflow"))
        save_mlflow_btn.setObjectName("secondaryButton")

        def save_mlflow_config():
            uri = uri_input.text().strip()
            if not uri:
                QMessageBox.warning(self, t("MLflow"), t("Ingrese la Tracking URI del servidor MLflow."))
                return
            raw_token = token_input.text().strip()
            config_path = writable_path("config.json")
            try:
                config = load_config()
                config["mlflow_tracking_uri"] = uri
                if raw_token:
                    config["mlflow_token_encrypted"] = encrypt_api_key(raw_token, self.mlflow_token_key_path)
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=True, indent=2)
            except ApiKeyError as exc:
                QMessageBox.warning(self, t("MLflow"), str(exc))
                return
            except OSError as exc:
                QMessageBox.critical(self, t("MLflow"), str(exc))
                return
            if raw_token:
                token_input.clear()
                token_input.setPlaceholderText(mask_api_key(raw_token))
            QMessageBox.information(self, t("MLflow"), t("Configuración de MLflow guardada localmente."))

        save_mlflow_btn.clicked.connect(save_mlflow_config)

        test_mlflow_btn = QPushButton(t("Probar conexión"))
        test_mlflow_btn.setObjectName("secondaryButton")

        def test_mlflow_connection():
            import mlflow_integration
            uri = uri_input.text().strip()
            if not uri:
                QMessageBox.warning(self, t("MLflow"), t("Ingrese la Tracking URI del servidor MLflow."))
                return
            raw_token = token_input.text().strip()
            test_config = dict(load_config())
            test_config["mlflow_tracking_uri"] = uri
            try:
                if raw_token:
                    # Token recien tipeado, todavia no guardado: se prueba tal cual esta en pantalla.
                    test_config["mlflow_token_encrypted"] = encrypt_api_key(raw_token, self.mlflow_token_key_path)
                mlflow_integration.test_connection(test_config)
            except ApiKeyError as exc:
                QMessageBox.warning(self, t("MLflow"), str(exc))
                return
            except Exception as exc:
                QMessageBox.critical(self, t("MLflow"), t("No se pudo conectar al servidor MLflow:\n{error}").format(error=str(exc)))
                return
            QMessageBox.information(self, t("MLflow"), t("Conexión con el servidor MLflow exitosa."))

        test_mlflow_btn.clicked.connect(test_mlflow_connection)

        mlflow_row.addWidget(make_label(t("MLflow Tracking URI:"), "infoText"))
        mlflow_row.addWidget(uri_input)
        mlflow_row.addWidget(token_input)
        mlflow_row.addWidget(save_mlflow_btn)
        mlflow_row.addWidget(test_mlflow_btn)
        mlflow_row.addStretch()


        thresh_fin_layout.addLayout(thresh_row)
        thresh_fin_layout.addLayout(fin_row)
        thresh_fin_layout.addLayout(mlflow_row)
        layout.addLayout(thresh_fin_layout)

    def showEvent(self, event):
        """El autostart de MLflow guarda su URI en segundo plano; si esta vista se
        construyo antes de que terminara, refresca el campo cuando se vuelve a ver."""
        super().showEvent(event)
        if not self.uri_input.text().strip():
            uri = load_config().get("mlflow_tracking_uri", "")
            if uri:
                self.uri_input.setText(uri)

class AccountHeaderCard(QFrame):
    def __init__(self, user_profile, parent=None):
        super().__init__(parent)
        self.setObjectName("accountHeader")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        user_name = user_profile.get("display_name", "Usuario")
        user_role = user_profile.get("role", "")
        username = user_profile.get("username", "")
        photo_path = user_profile.get("profile_photo", "")

        avatar_pixmap = None
        if photo_path:
            avatar_pixmap = make_round_pixmap(resolve_path(photo_path), 54)

        avatar = QLabel()
        if avatar_pixmap:
            avatar.setPixmap(avatar_pixmap)
        else:
            avatar.setText(user_name[:1].upper() if user_name else "?")
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setObjectName("accountAvatarFallback")

        avatar.setFixedSize(54, 54)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        info_layout.addWidget(make_label(user_name, "accountName"))
        info_layout.addWidget(make_label(user_role, "accountRole"))

        if username:
            info_layout.addWidget(make_label(f"{t('Usuario')}: {username}", "accountMeta"))

        layout.addWidget(avatar)
        layout.addLayout(info_layout, 1)


class MenuSection(QFrame):
    def __init__(self, title, actions, parent=None):
        super().__init__(parent)
        self.setObjectName("menuSection")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        layout.addWidget(make_label(title, "menuSectionTitle"))
        layout.addWidget(make_separator("menuSectionLine"))

        for label, object_name, callback in actions:
            button = QPushButton(label)
            button.setObjectName(object_name or "menuButton")
            button.setFixedHeight(38)
            button.setCursor(Qt.PointingHandCursor)
            if callback:
                button.clicked.connect(callback)
            layout.addWidget(button)


class UserMenuView(QWidget):
    def __init__(self, user_profile, on_logout=None, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.user_profile = user_profile or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label(t("Cuenta"), "pageTitle"))
        layout.addWidget(make_separator("separator"))
        layout.addWidget(AccountHeaderCard(user_profile))

        top_row = QHBoxLayout()
        top_row.setSpacing(18)

        top_row.addWidget(
            MenuSection(
                t("Perfil"),
                [
                    (t("Editar perfil"), "menuButton", None),
                    (t("Actualizar foto"), "menuButton", self.update_photo),
                    (t("Datos personales"), "menuButton", None),
                ],
            ),
            1,
        )
        top_row.addWidget(
            MenuSection(
                t("Preferencias"),
                [
                    (t("Notificaciones"), "menuButton", None),
                    (t("Idioma y zona horaria"), "menuButton", None),
                    (t("Accesibilidad"), "menuButton", None),
                ],
            ),
            1,
        )

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(18)
        bottom_row.addWidget(
            MenuSection(
                t("Seguridad"),
                [
                    (t("Cambiar contrasena"), "menuButton", None),
                    (t("Dispositivos vinculados"), "menuButton", None),
                    (t("Verificacion en dos pasos"), "menuButton", None),
                ],
            ),
            1,
        )
        bottom_row.addWidget(
            MenuSection(
                t("Sesion"),
                [
                    (t("Cerrar sesion en otros equipos"), "menuButton", None),
                    (t("Salir de la cuenta"), "logoutButton", on_logout),
                ],
            ),
            1,
        )

        layout.addLayout(top_row)
        layout.addLayout(bottom_row)

    def update_photo(self):
        username = self.user_profile.get("username", "")
        if not username:
            return
        source, _ = QFileDialog.getOpenFileName(
            self, t("Seleccionar foto de perfil"), "", "Imagenes (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not source:
            return
        crop_dialog = PhotoCropDialog(source, self)
        if crop_dialog.exec() != QDialog.Accepted:
            return
        cropped = crop_dialog.cropped_pixmap()
        if cropped is None:
            return
        try:
            profile_photo = save_profile_photo(username, cropped)
        except OSError as exc:
            QMessageBox.critical(self, t("Actualizar foto"), str(exc))
            return

        config = load_config()
        users = config.get("users", [])
        for user in users:
            if normalize_username(user.get("username", "")) == normalize_username(username):
                user["profile_photo"] = profile_photo
                break
        try:
            save_users_to_config(users)
        except OSError as exc:
            QMessageBox.critical(self, t("Actualizar foto"), str(exc))
            return

        self.user_profile["profile_photo"] = profile_photo
        QMessageBox.information(
            self, t("Actualizar foto"), t("Foto de perfil actualizada. Cierra sesión y vuelve a entrar para verla en toda la aplicación.")
        )


class AdminMenuView(QWidget):
    def __init__(self, user_profile, on_logout=None, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.user_profile = user_profile or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label(t("Administracion"), "pageTitle"))
        layout.addWidget(make_separator("separator"))
        layout.addWidget(AccountHeaderCard(user_profile))

        top_row = QHBoxLayout()
        top_row.setSpacing(18)
        top_row.addWidget(
            MenuSection(
                t("Usuarios"),
                [
                    (t("Crear usuario"), "menuButton", self.create_user),
                    (t("Resetear contrasena"), "menuButton", None),
                    (t("Eliminar usuario"), "menuButton", self.delete_user),
                    (t("Editar roles"), "menuButton", None),
                    (t("Ver bloqueos de usuarios"), "menuButton", self.show_user_locks),
                ],
            ),
            1,
        )
        top_row.addWidget(
            MenuSection(
                t("Permisos"),
                [
                    (t("Roles y permisos"), "menuButton", None),
                    (t("Grupos"), "menuButton", None),
                    (t("Accesos temporales"), "menuButton", None),
                ],
            ),
            1,
        )

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(18)
        bottom_row.addWidget(
            MenuSection(
                t("Auditoria"),
                [
                    (t("Registro de Actividad"), "menuButton", None),
                    (t("Alertas"), "menuButton", None),
                    (t("Exportar reporte"), "menuButton", self.export_html_report),
                ],
            ),
            1,
        )
        bottom_row.addWidget(
            MenuSection(
                t("Sistema"),
                [
                    (t("Backup y restauracion"), "menuButton", None),
                    (t("Integraciones"), "menuButton", None),
                    (t("Parametros globales"), "menuButton", None),
                    (t("Salir de la cuenta"), "logoutButton", on_logout),
                ],
            ),
            1,
        )
        bottom_row.addWidget(
            MenuSection(
                t("EXPERIMENTAL"),
                [
                    (t("Limpiar datos de un proyecto"), "dangerButton", self.clear_project),
                    (t("Eliminar un proyecto"), "dangerButton", self.delete_project),
                ],
            ),
            1,
        )

        layout.addLayout(top_row)
        layout.addLayout(bottom_row)

    def _require_admin(self):
        role = self.user_profile.get("role", "")
        if str(role).lower() not in {"admin", "administrador"}:
            QMessageBox.warning(self, t("Usuarios"), t("Solo un administrador puede gestionar usuarios."))
            return False
        return True

    def create_user(self):
        if not self._require_admin():
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(t("Crear usuario"))
        dialog.setMinimumWidth(360)
        form_layout = QVBoxLayout(dialog)

        form = QFormLayout()
        username_input = QLineEdit()
        display_name_input = QLineEdit()
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.Password)
        role_combo = QComboBox()
        role_combo.addItems([t("Usuario"), t("Administrador")])
        form.addRow(t("Usuario"), username_input)
        form.addRow(t("Nombre a mostrar"), display_name_input)
        form.addRow(t("Contraseña"), password_input)
        form.addRow(t("Rol"), role_combo)
        form_layout.addLayout(form)

        photo_row = QHBoxLayout()
        photo_preview = QLabel()
        photo_preview.setFixedSize(56, 56)
        photo_preview.setStyleSheet("background-color: #222; border-radius: 28px;")
        photo_preview.setAlignment(Qt.AlignCenter)
        photo_button = QPushButton(t("Seleccionar foto"))
        photo_button.setObjectName("secondaryButton")
        photo_button.setCursor(Qt.PointingHandCursor)
        selected_photo = {"pixmap": None}

        def choose_photo():
            source, _ = QFileDialog.getOpenFileName(
                dialog, t("Seleccionar foto de perfil"), "", "Imagenes (*.png *.jpg *.jpeg *.bmp *.webp)"
            )
            if not source:
                return
            crop_dialog = PhotoCropDialog(source, dialog)
            if crop_dialog.exec() != QDialog.Accepted:
                return
            cropped = crop_dialog.cropped_pixmap()
            if cropped is None:
                return
            selected_photo["pixmap"] = cropped
            photo_preview.setPixmap(make_round_pixmap(cropped, 56))

        photo_button.clicked.connect(choose_photo)
        photo_row.addWidget(photo_preview)
        photo_row.addWidget(photo_button, 1)
        form_layout.addLayout(photo_row)

        error_label = make_label("", "loginError")
        error_label.setVisible(False)
        form_layout.addWidget(error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form_layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        username = username_input.text().strip()
        display_name = display_name_input.text().strip() or username
        password = password_input.text()
        role = "Administrador" if role_combo.currentIndex() == 1 else "Usuario"

        if not username:
            QMessageBox.warning(self, t("Crear usuario"), t("Ingresa un usuario válido."))
            return

        config = load_config()
        if find_user_profile(config, username):
            QMessageBox.warning(self, t("Crear usuario"), t("Ya existe un usuario con ese nombre."))
            return

        try:
            validate_password(password)
        except ValidationError as exc:
            QMessageBox.warning(self, t("Crear usuario"), str(exc))
            return

        profile_photo = ""
        if selected_photo["pixmap"] is not None:
            try:
                profile_photo = save_profile_photo(username, selected_photo["pixmap"])
            except OSError as exc:
                QMessageBox.critical(self, t("Crear usuario"), str(exc))
                return

        new_user = {
            "username": username,
            "display_name": display_name,
            "role": role,
            "profile_photo": profile_photo,
            "password_hash": hash_password(password),
        }
        users = config.get("users", [])
        users.append(new_user)
        try:
            save_users_to_config(users)
        except OSError as exc:
            QMessageBox.critical(self, t("Crear usuario"), str(exc))
            return

        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
        finally:
            if store is not None:
                store.close()

        QMessageBox.information(self, t("Crear usuario"), t("Usuario creado correctamente."))

    def delete_user(self):
        if not self._require_admin():
            return

        config = load_config()
        users = config.get("users", [])
        current_username = normalize_username(self.user_profile.get("username", ""))
        deletable = [user for user in users if normalize_username(user.get("username", "")) != current_username]

        if not deletable:
            QMessageBox.information(self, t("Eliminar usuario"), t("No hay otros usuarios para eliminar."))
            return

        usernames = [user.get("username", "") for user in deletable]
        selected, accepted = QInputDialog.getItem(
            self, t("Eliminar usuario"), t("Selecciona el usuario a eliminar:"), usernames, 0, False
        )
        if not accepted:
            return

        target = find_user_profile(config, selected)
        remaining_admins = [
            user for user in users
            if str(user.get("role", "")).lower() in {"admin", "administrador"}
            and normalize_username(user.get("username", "")) != normalize_username(selected)
        ]
        if target and str(target.get("role", "")).lower() in {"admin", "administrador"} and not remaining_admins:
            QMessageBox.warning(self, t("Eliminar usuario"), t("No puedes eliminar al único administrador restante."))
            return

        reply = QMessageBox.question(
            self, t("Eliminar usuario"),
            t("¿Seguro que deseas eliminar al usuario {username}? Esta acción no se puede deshacer.").format(username=selected),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        remaining_users = [user for user in users if normalize_username(user.get("username", "")) != normalize_username(selected)]
        try:
            save_users_to_config(remaining_users)
        except OSError as exc:
            QMessageBox.critical(self, t("Eliminar usuario"), str(exc))
            return

        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
            store.delete_user(selected)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, t("Eliminar usuario"), str(exc))
        finally:
            if store is not None:
                store.close()

        QMessageBox.information(self, t("Eliminar usuario"), t("Usuario eliminado correctamente."))

    def _select_project_for_destructive_action(self, title):
        if not self._require_admin():
            return None
        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
            projects = store.list_projects()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, title, str(exc))
            return None
        finally:
            if store is not None:
                store.close()
        if not projects:
            QMessageBox.information(self, title, t("No hay proyectos disponibles."))
            return None
        names = [project["name"] for project in projects]
        selected_name, accepted = QInputDialog.getItem(
            self, title, t("Selecciona el proyecto:"), names, 0, False
        )
        if not accepted:
            return None
        return next((project for project in projects if project["name"] == selected_name), None)

    def clear_project(self):
        title = t("Limpiar datos de un proyecto")
        project = self._select_project_for_destructive_action(title)
        if project is None:
            return
        reply = QMessageBox.question(
            self,
            title,
            t("¿Limpiar todos los modelos y ejecuciones de {name}? El proyecto se conservará. Esta acción no se puede deshacer.").format(
                name=project["name"]
            ),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
            store.clear_project(project["id"])
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, title, str(exc))
            return
        finally:
            if store is not None:
                store.close()
        QMessageBox.information(self, title, t("Datos del proyecto eliminados correctamente."))
        if self.main_window:
            self.main_window.refresh_projects_view()

    def delete_project(self):
        title = t("Eliminar un proyecto")
        project = self._select_project_for_destructive_action(title)
        if project is None:
            return
        reply = QMessageBox.question(
            self,
            title,
            t("¿Eliminar permanentemente el proyecto {name}, sus modelos y sus ejecuciones? Esta acción no se puede deshacer.").format(
                name=project["name"]
            ),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
            store.delete_project(project["id"])
            remaining_projects = store.list_projects()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, title, str(exc))
            return
        finally:
            if store is not None:
                store.close()
        if load_config().get("current_project_id") == project["id"]:
            replacement_id = remaining_projects[0]["id"] if remaining_projects else None
            save_current_project_id(replacement_id)
        QMessageBox.information(self, title, t("Proyecto eliminado correctamente."))
        if self.main_window:
            self.main_window.refresh_projects_view()

    def show_user_locks(self):
        role = self.user_profile.get("role", "")
        if str(role).lower() not in {"admin", "administrador"}:
            QMessageBox.warning(self, t("Bloqueos de usuarios"), t("Solo un administrador puede consultar bloqueos."))
            return
        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
            users = store.list_user_status()
            if not users:
                QMessageBox.information(self, t("Bloqueos de usuarios"), t("No hay usuarios registrados."))
                return
            lines = [
                t("{username} | Rol: {role} | Intentos: {attempts} | Estado: {status}").format(
                    username=row["username"], role=row["role"], attempts=row["failed_attempts"],
                    status=t("Bloqueada") if row["is_locked"] else t("Activa")
                )
                for row in users
            ]
            locked_users = [row["username"] for row in users if row["is_locked"]]
            if not locked_users:
                QMessageBox.information(
                    self, t("Bloqueos de usuarios"),
                    "\n".join(lines) + "\n\n" + t("No hay cuentas bloqueadas.")
                )
                return
            selected, accepted = QInputDialog.getItem(
                self, t("Desbloquear usuario"), "\n".join(lines),
                locked_users, 0, False
            )
            if not accepted:
                return
            store.unlock_user(selected, role)
        except (OSError, ValueError, PermissionError) as exc:
            QMessageBox.warning(self, t("Bloqueos de usuarios"), str(exc))
            return
        finally:
            if store is not None:
                store.close()
        QMessageBox.information(self, t("Bloqueos de usuarios"), t("Usuario desbloqueado correctamente."))

    def export_html_report(self):
        score = "N/A"
        gs = "N/A"
        details_dict = {}
        if hasattr(self, 'main_window') and self.main_window:
            if hasattr(self.main_window, 'current_score') and self.main_window.current_score is not None:
                score = f"{self.main_window.current_score:.2f}"
                current_green_score = getattr(self.main_window, "current_green_score", None)
                if current_green_score is not None:
                    gs = f"{current_green_score:.1f}"

            if hasattr(self.main_window, 'selection_state'):
                details_dict = self.main_window.selection_state.copy()

        import export_handler
        data = {
            "kpis": [
                [15, 60, t("Impact Score"), score, "", "cyan_500"],
                [75, 60, t("Green Score"), gs, "/100", "emerald_500"]
            ],
            "details": [
                [t("Hardware (TDP)"), details_dict.get("hardware", "N/A"), "emerald_600"],
                [t("Proveedor Cloud"), details_dict.get("provider", "N/A"), "gray_800"],
                [t("Región Eléctrica"), details_dict.get("region", "N/A"), "gray_800"],
                [t("Energía del Modelo"), details_dict.get("model_energy", "N/A"), "cyan_600"]
            ]
        }
        export_handler.generate_and_save_report(self, "eco", data, lang=i18n.get_language())


class PatternPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("patternPanel")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b0b0b"))
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(QColor(255, 255, 255, 28))
        pen.setWidth(1)
        painter.setPen(pen)

        size = 160
        half = size / 2
        width = self.width()
        height = self.height()

        for y in range(-size, height + size, size):
            for x in range(-size, width + size, size):
                diamond = QPolygonF(
                    [
                        QPointF(x, y - half),
                        QPointF(x + half, y),
                        QPointF(x, y + half),
                        QPointF(x - half, y),
                    ]
                )
                painter.drawPolygon(diamond)


class LoginUserCard(QFrame):
    def __init__(self, user_profile, parent=None):
        super().__init__(parent)
        self.setObjectName("loginUserCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        avatar = QLabel()
        photo_path = user_profile.get("profile_photo", "")
        avatar_pixmap = None
        if photo_path:
            avatar_pixmap = make_round_pixmap(resolve_path(photo_path), 34)
        if avatar_pixmap:
            avatar.setPixmap(avatar_pixmap)
        else:
            avatar.setText(user_profile.get("display_name", "?")[:1].upper())
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setObjectName("loginAvatarFallback")

        avatar.setFixedSize(34, 34)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.addWidget(make_label(user_profile.get("display_name", ""), "loginUserName"))
        text_layout.addWidget(make_label(user_profile.get("role", ""), "loginUserRole"))

        layout.addWidget(avatar)
        layout.addLayout(text_layout)
        layout.addStretch()


class ImageCropWidget(QLabel):
    """Draggable/zoomable square viewport used to crop a profile photo."""

    VIEW_SIZE = 320

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.VIEW_SIZE, self.VIEW_SIZE)
        self.setCursor(Qt.OpenHandCursor)
        self.original_pixmap = pixmap
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self._base_scale = 1.0
        self._drag_start = None
        self._recompute_base_scale()

    def _recompute_base_scale(self):
        width = self.original_pixmap.width()
        height = self.original_pixmap.height()
        if width <= 0 or height <= 0:
            self._base_scale = 1.0
            return
        self._base_scale = max(self.VIEW_SIZE / width, self.VIEW_SIZE / height)
        self._clamp_offset()

    def _scaled_size(self):
        scale = self._base_scale * self.zoom
        return self.original_pixmap.width() * scale, self.original_pixmap.height() * scale

    def _clamp_offset(self):
        scaled_w, scaled_h = self._scaled_size()
        min_x = min(0.0, self.VIEW_SIZE - scaled_w)
        min_y = min(0.0, self.VIEW_SIZE - scaled_h)
        x = min(0.0, max(min_x, self.offset.x()))
        y = min(0.0, max(min_y, self.offset.y()))
        self.offset = QPointF(x, y)

    def set_zoom_percent(self, percent):
        self.zoom = max(1.0, percent / 100.0)
        self._clamp_offset()
        self.update()

    def mousePressEvent(self, event):
        self._drag_start = event.position()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        delta = event.position() - self._drag_start
        self._drag_start = event.position()
        self.offset = QPointF(self.offset.x() + delta.x(), self.offset.y() + delta.y())
        self._clamp_offset()
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.setCursor(Qt.OpenHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#141414"))
        scaled_w, scaled_h = self._scaled_size()
        scaled = self.original_pixmap.scaled(
            int(scaled_w), int(scaled_h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        painter.drawPixmap(int(self.offset.x()), int(self.offset.y()), scaled)
        pen = QPen(QColor("#66bb22"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(0, 0, self.VIEW_SIZE - 1, self.VIEW_SIZE - 1)
        painter.end()

    def result_pixmap(self, output_size=PROFILE_PHOTO_SIZE):
        scaled_w, scaled_h = self._scaled_size()
        scaled = self.original_pixmap.scaled(
            int(scaled_w), int(scaled_h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        canvas = QPixmap(self.VIEW_SIZE, self.VIEW_SIZE)
        canvas.fill(Qt.black)
        painter = QPainter(canvas)
        painter.drawPixmap(int(self.offset.x()), int(self.offset.y()), scaled)
        painter.end()
        return canvas.scaled(output_size, output_size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class PhotoCropDialog(QDialog):
    """CU: recorte uniforme de foto de perfil a 400x400 PNG."""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Ajustar foto de perfil"))

        pixmap = QPixmap(image_path)
        self.is_valid = not pixmap.isNull()

        layout = QVBoxLayout(self)
        layout.addWidget(
            make_label(t("Arrastra la imagen para encuadrarla y usa el zoom para ajustarla."), "infoText")
        )

        if self.is_valid:
            self.crop_widget = ImageCropWidget(pixmap)
            layout.addWidget(self.crop_widget, 0, Qt.AlignHCenter)

            zoom_row = QHBoxLayout()
            zoom_row.addWidget(make_label(t("Zoom"), "infoText"))
            self.zoom_slider = QSlider(Qt.Horizontal)
            self.zoom_slider.setRange(100, 300)
            self.zoom_slider.setValue(100)
            self.zoom_slider.valueChanged.connect(self.crop_widget.set_zoom_percent)
            zoom_row.addWidget(self.zoom_slider, 1)
            layout.addLayout(zoom_row)
        else:
            self.crop_widget = None
            layout.addWidget(make_label(t("No se pudo abrir la imagen seleccionada."), "loginError"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def cropped_pixmap(self):
        if not self.crop_widget:
            return None
        return self.crop_widget.result_pixmap(PROFILE_PHOTO_SIZE)


class SecurityQuestionsDialog(QDialog):
    """CU 55.x: recuperacion de acceso de administrador via preguntas de seguridad."""

    def __init__(self, security_questions, parent=None):
        super().__init__(parent)
        self.security_questions = security_questions
        self.answer_inputs = []

        self.setWindowTitle(t("Recuperar acceso"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.addWidget(
            make_label(
                t("Responde tus preguntas de seguridad para desbloquear la cuenta de administrador."),
                "infoText",
            )
        )

        form = QFormLayout()
        for entry in self.security_questions:
            answer_input = QLineEdit()
            answer_input.setObjectName("loginInput")
            form.addRow(t(entry.get("question", "")), answer_input)
            self.answer_inputs.append(answer_input)
        layout.addLayout(form)

        self.error_label = make_label("", "loginError")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._handle_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _handle_accept(self):
        for entry, answer_input in zip(self.security_questions, self.answer_inputs):
            if not verify_security_answer(answer_input.text(), entry.get("answer_hash", "")):
                self.error_label.setText(t("Una o más respuestas son incorrectas."))
                self.error_label.setVisible(True)
                return
        self.accept()


class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.failed_attempts = 0 # CU 55.2

        self.config = load_config()
        self.setWindowTitle(t("Semáforo IA - Login"))
        self.resize(1100, 640)

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        left_panel = PatternPanel()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(40, 40, 40, 40)
        left_layout.setSpacing(18)

        brand_icon = QLabel()
        brand_icon.setPixmap(make_leaf_pixmap(64))
        brand_icon.setFixedSize(64, 64)

        brand_title = make_label(t("SEMÁFORO\nIA"), "loginBrand", alignment=Qt.AlignCenter)

        left_layout.addStretch()
        left_layout.addWidget(brand_icon, 0, Qt.AlignHCenter)
        left_layout.addWidget(brand_title, 0, Qt.AlignHCenter)
        left_layout.addStretch()

        right_panel = QFrame()
        right_panel.setObjectName("loginPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(48, 48, 48, 48)
        right_layout.setSpacing(16)

        right_layout.addWidget(make_label(t("Login"), "loginCaption"))
        right_layout.addWidget(make_label(t("Bienvenido de Vuelta"), "loginTitle"))
        right_layout.addSpacing(8)

        right_layout.addWidget(make_label(t("Usuario"), "loginLabel"))
        self.username_input = QLineEdit()
        self.username_input.setObjectName("loginInput")
        self.username_input.setPlaceholderText(t("Ingrese un usuario"))
        self.username_input.setFixedHeight(40)

        right_layout.addWidget(self.username_input)

        right_layout.addWidget(make_label(t("Contraseña"), "loginLabel"))
        self.password_input = QLineEdit()
        self.password_input.setObjectName("loginInput")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("••••••••")
        self.password_input.setFixedHeight(40)

        right_layout.addWidget(self.password_input)

        server_ip = self.config.get("server_ip", "127.0.0.1")
        server_port = self.config.get("server_port", 6767)
        self.server_url = f"{server_ip}:{server_port}"

        right_layout.addWidget(make_label(t("Conexión"), "loginLabel"))
        self.connection_combo = QComboBox()
        self.connection_combo.setObjectName("filterCombo")
        self.connection_combo.addItems([t("Local"), t("Servidor")])
        self.connection_combo.setFixedHeight(40)
        right_layout.addWidget(self.connection_combo)

        self.ip_label = make_label(t("URL Servidor"), "loginLabel")
        self.server_ip_input = QLineEdit()
        self.server_ip_input.setObjectName("loginInput")
        self.server_ip_input.setText(self.server_url)
        self.server_ip_input.setFixedHeight(40)

        right_layout.addWidget(self.ip_label)
        right_layout.addWidget(self.server_ip_input)

        self.ip_label.setVisible(False)
        self.server_ip_input.setVisible(False)

        def on_connection_changed(idx):
            is_server = (self.connection_combo.currentText() == t("Servidor"))
            self.ip_label.setVisible(is_server)
            self.server_ip_input.setVisible(is_server)

        self.connection_combo.currentIndexChanged.connect(on_connection_changed)

        self.error_label = make_label("", "loginError")
        self.error_label.setVisible(False)
        right_layout.addWidget(self.error_label)

        self.login_button = QPushButton(t("Continuar"))
        self.login_button.setObjectName("loginButton")
        self.login_button.setCursor(Qt.PointingHandCursor)
        self.login_button.setFixedWidth(140)
        self.login_button.clicked.connect(self.handle_login)

        right_layout.addWidget(self.login_button, 0, Qt.AlignLeft)

        self.recover_button = QPushButton(t("Recuperar acceso con preguntas de seguridad"))
        self.recover_button.setObjectName("secondaryButton")
        self.recover_button.setCursor(Qt.PointingHandCursor)
        self.recover_button.clicked.connect(self.handle_recover_access)
        self.recover_button.setVisible(False)
        right_layout.addWidget(self.recover_button, 0, Qt.AlignLeft)
        self._locked_admin_username = None

        right_layout.addSpacing(10)

        users_label = make_label(t("Usuarios disponibles"), "loginHint")
        right_layout.addWidget(users_label)

        user_cards = QVBoxLayout()
        user_cards.setSpacing(8)
        for profile in self.config.get("users", []):
            user_cards.addWidget(LoginUserCard(profile))
        right_layout.addLayout(user_cards)

        right_layout.addStretch()

        root_layout.addWidget(left_panel, 3)
        root_layout.addWidget(right_panel, 2)

        self.username_input.returnPressed.connect(self.handle_login)
        self.password_input.returnPressed.connect(self.handle_login)

    def handle_login(self):
        self.recover_button.setVisible(False)
        self._locked_admin_username = None

        if self.failed_attempts >= 5:
            self._set_error(t("Acceso denegado: Demasiados intentos fallidos. Contacte a un administrador."))
            return

        username = self.username_input.text().strip()
        if not username:
            self._set_error(t("Ingresa un usuario válido."))
            return

        password = self.password_input.text()

        mode = self.connection_combo.currentText()
        if mode == t("Local"):
            profile = find_user_profile(self.config, username)
            if not profile:
                self.failed_attempts += 1
                if self.failed_attempts >= 5:
                    self.login_button.setEnabled(False)
                    self._set_error(t("Acceso denegado: Demasiados intentos fallidos. Contacte a un administrador."))
                else:
                    self._set_error(t("Usuario no encontrado."))
                return

            auth_store = bootstrap_store(self.config, writable_path("semaforo.sqlite3"))
            authenticated = auth_store.authenticate(username, password)
            is_locked = auth_store.is_user_locked(username)
            auth_store.close()
            if not authenticated:
                self.failed_attempts += 1
                if is_locked:
                    self.login_button.setEnabled(False)
                    is_admin = str(profile.get("role", "")).lower() in {"admin", "administrador"}
                    if is_admin and profile.get("security_questions"):
                        self._locked_admin_username = profile.get("username")
                        self.recover_button.setVisible(True)
                        self._set_error(t("Usuario bloqueado. Puedes recuperar el acceso respondiendo tus preguntas de seguridad."))
                    else:
                        self._set_error(t("Usuario bloqueado"))
                    return
                if self.failed_attempts >= 5:
                    self.login_button.setEnabled(False)
                    self._set_error(t("Acceso denegado: Demasiados intentos fallidos. Contacte a un administrador."))
                else:
                    self._set_error(t("Contraseña incorrecta."))
                return
        else:
            # Server Mode
            import urllib.request
            import urllib.error
            import json

            self.server_url = self.server_ip_input.text().strip()
            req = urllib.request.Request(
                f"http://{self.server_url}/login",
                data=json.dumps({"username": username, "password": password}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    profile = res_data.get("user")
                    profile["server_token"] = res_data.get("token")
            except urllib.error.HTTPError as e:
                self.failed_attempts += 1
                try:
                    error_msg = json.loads(e.read().decode("utf-8")).get("error", t("Error de autenticación."))
                    error_msg = t(error_msg)
                except Exception:
                    error_msg = t("Error de autenticación.")

                if self.failed_attempts >= 5:
                    self.login_button.setEnabled(False)
                    self._set_error(t("Acceso denegado: Demasiados intentos fallidos. Contacte a un administrador."))
                else:
                    self._set_error(error_msg)
                return
            except urllib.error.URLError:
                self._set_error(t("No se pudo conectar al servidor."))
                return

        profile["connection_mode"] = mode
        if mode != "Local":
            profile["server_url"] = self.server_url

        self.error_label.setVisible(False)
        self.dashboard = DashboardWindow(profile)
        self.dashboard.show()
        self.close()

    def _set_error(self, message):
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def handle_recover_access(self):
        username = self._locked_admin_username
        profile = find_user_profile(self.config, username) if username else None
        security_questions = profile.get("security_questions") if profile else None
        if not profile or not security_questions:
            self._set_error(t("No hay preguntas de seguridad configuradas para este usuario."))
            return

        dialog = SecurityQuestionsDialog(security_questions, self)
        if dialog.exec() != QDialog.Accepted:
            return

        auth_store = bootstrap_store(self.config, writable_path("semaforo.sqlite3"))
        try:
            auth_store.unlock_user_via_security_questions(username)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, t("Recuperar acceso"), str(exc))
            return
        finally:
            auth_store.close()

        self.failed_attempts = 0
        self.login_button.setEnabled(True)
        self.recover_button.setVisible(False)
        self._locked_admin_username = None
        self.error_label.setVisible(False)
        QMessageBox.information(self, t("Recuperar acceso"), t("Cuenta desbloqueada correctamente. Ya puedes iniciar sesión con tu contraseña."))


class CatalogRow(QFrame):
    def __init__(self, component, comp_type, vcpus, ram, tdp, on_assign=None, payload=None, parent=None):
        super().__init__(parent)
        self.setObjectName("catalogRow")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoFillBackground(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)

        layout.addWidget(make_label(component, "catalogCell"), 3)
        layout.addWidget(make_label(comp_type, "catalogCell", alignment=Qt.AlignCenter), 1)
        layout.addWidget(make_label(vcpus, "catalogCell", alignment=Qt.AlignCenter), 1)
        layout.addWidget(make_label(ram, "catalogCell", alignment=Qt.AlignCenter), 1)
        layout.addWidget(make_label(tdp, "catalogCell", alignment=Qt.AlignCenter), 1)

        assign_button = QPushButton(t("Asignar"))
        assign_button.setObjectName("assignButton")
        assign_button.setFixedHeight(32)
        assign_button.setCursor(Qt.PointingHandCursor)
        if on_assign:
            assign_button.clicked.connect(lambda checked=False: on_assign(payload))
        layout.addWidget(assign_button, 1, alignment=Qt.AlignRight)

    def enterEvent(self, event):
        self.setProperty("hovered", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hovered", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)


class HardwareLookupThread(QThread):
    """Runs hardware detection off the UI thread so switching tabs stays responsive."""

    finished_with_info = Signal(dict)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile or {}

    def run(self):
        mode = self.profile.get("connection_mode", "Local")
        info = {}
        if mode == "Local":
            info = get_hardware_info()
        else:
            import urllib.request
            import urllib.error
            import json

            server_url = self.profile.get("server_url", "127.0.0.1:6767")
            token = self.profile.get("server_token")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                request = urllib.request.Request(f"http://{server_url}/hardware", headers=headers)
                with urllib.request.urlopen(request, timeout=5) as response:
                    info = json.loads(response.read().decode("utf-8"))
            except Exception:
                info = {}
        self.finished_with_info.emit(info)


class HardwareCatalogView(QWidget):
    COMPONENT_TYPES = ("GPU", "CPU", "RAM")

    def __init__(self, on_assign=None, parent=None, profile=None):
        super().__init__(parent)
        self.on_assign = on_assign
        self.profile = profile or {}

        self._hardware_loaded = False
        self.detected_info = {}
        self.selected_by_type = {component_type: None for component_type in self.COMPONENT_TYPES}
        self.hardware_rows = load_csv_rows("hardware.csv")
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._apply_hardware_filters)

        # Column layout per component type: (extra_headers, extractor(row) -> (col1, col2))
        self.column_specs = {
            "GPU": (["TFLOPS", "VRAM"], lambda row: (row.get("FP16_FP32_TFLOPS", "--") or "--", row.get("VRAM_GB", "--") or "--")),
            "CPU": ([t("Núcleos/Hilos"), t("Frecuencia")], lambda row: (row.get("Nucleos_Hilos", "--") or "--", row.get("Frecuencia_MHz", "--") or "--")),
            "RAM": ([t("Capacidad"), t("Frecuencia")], lambda row: (row.get("Capacidad_GB", "--") or "--", row.get("Frecuencia_MHz", "--") or "--")),
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        title = make_label(t("Catálogo de Hardware"), "pageTitle")

        placeholder = t("Detectando...")
        hardware_rows = [
            (t("CPU"), placeholder),
            (t("GPU"), placeholder),
            (t("RAM"), placeholder),
            (t("Sistema"), placeholder),
        ]
        self.hardware_panel = DetailsPanel(t("Hardware detectado"), hardware_rows)
        self.hardware_panel.setObjectName("hardwarePanel")

        catalog_panel = QFrame()
        catalog_panel.setObjectName("catalogPanel")
        panel_layout = QVBoxLayout(catalog_panel)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(12)

        search_row = QHBoxLayout()
        search_row.setSpacing(16)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText(t("Buscar componente..."))
        self.search_input.setFixedHeight(42)

        self.filter_combo = ChevronComboBox()
        self.filter_combo.setObjectName("filterCombo")
        self.filter_combo.addItems([t("TDP máx: todos"), t("TDP máx: 125W"), t("TDP máx: 225W"), t("TDP máx: 400W")])
        self.filter_combo.setFixedHeight(42)
        self.filter_combo.setMinimumWidth(220)

        self.autoselect_btn = QPushButton(t("Autoseleccionar detectado"))
        self.autoselect_btn.setObjectName("secondaryButton")
        self.autoselect_btn.clicked.connect(self._auto_select_detected)

        self.rightsize_btn = QPushButton(t("Sugerir hardware eficiente"))
        self.rightsize_btn.setObjectName("secondaryButton")
        self.rightsize_btn.setEnabled(False)
        self.rightsize_btn.clicked.connect(self._suggest_rightsize)

        search_row.addWidget(self.search_input, 3)
        search_row.addWidget(self.filter_combo, 1)
        search_row.addWidget(self.autoselect_btn)
        search_row.addWidget(self.rightsize_btn)

        self.hardware_tabs = QTabWidget()
        self.hardware_tabs.setObjectName("hardwareTabs")
        self.rows_layout_by_type = {}
        for component_type in self.COMPONENT_TYPES:
            tab = self._build_component_tab(component_type)
            self.hardware_tabs.addTab(tab, t(component_type))
        self.hardware_tabs.currentChanged.connect(self._on_tab_changed)

        self.selection_summary = make_label(self._format_selection_summary(), "infoText")
        self.selection_summary.setObjectName("hardwareSelectionSummary")

        panel_layout.addLayout(search_row)
        panel_layout.addWidget(self.selection_summary)
        panel_layout.addWidget(self.hardware_tabs)

        layout.addWidget(title)
        layout.addWidget(make_separator("separator"))
        layout.addWidget(self.hardware_panel)
        layout.addWidget(catalog_panel)

        self.rightsize_result = make_label("", "infoText")
        layout.addWidget(self.rightsize_result)

        self.search_input.textChanged.connect(self._schedule_hardware_filter)
        self.filter_combo.currentTextChanged.connect(self._schedule_hardware_filter)
        self._apply_hardware_filters()

    def _build_component_tab(self, component_type):
        extra_headers, _ = self.column_specs[component_type]

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 12, 0, 0)
        tab_layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("catalogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 10, 18, 10)
        header_layout.setSpacing(10)

        header_layout.addWidget(make_label(t("Componente"), "catalogHeaderLabel"), 3)
        header_layout.addWidget(make_label(t("Tipo"), "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label(extra_headers[0], "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label(extra_headers[1], "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label("TDP", "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label("", "catalogHeaderLabel"), 1)

        rows_container = QWidget()
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(0)
        self.rows_layout_by_type[component_type] = rows_layout

        rows_scroll = QScrollArea()
        rows_scroll.setObjectName("catalogScroll")
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setFrameShape(QFrame.NoFrame)
        rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rows_scroll.setWidget(rows_container)

        tab_layout.addWidget(header)
        tab_layout.addWidget(rows_scroll)
        return tab

    def _current_component_type(self):
        index = self.hardware_tabs.currentIndex()
        if 0 <= index < len(self.COMPONENT_TYPES):
            return self.COMPONENT_TYPES[index]
        return "GPU"

    def _on_tab_changed(self, index):
        self._apply_hardware_filters()
        component_type = self._current_component_type()
        selected = self.selected_by_type.get(component_type)
        tdp_value = parse_number(selected.get("TDP_Max_Watts", "")) if selected else None
        self.rightsize_btn.setEnabled(tdp_value is not None)

    def _rows_of_type(self, component_type):
        return [row for row in (self.hardware_rows or []) if (row.get("Tipo_Componente") or "GPU").strip().upper() == component_type]

    def _schedule_hardware_filter(self):
        self._filter_timer.stop()
        self._filter_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._hardware_loaded:
            self._hardware_loaded = True
            QTimer.singleShot(50, self._load_hardware)

    def _load_hardware(self):
        self._hw_thread = HardwareLookupThread(self.profile, self)
        self._hw_thread.finished_with_info.connect(self._on_hardware_loaded)
        self._hw_thread.start()

    def _on_hardware_loaded(self, info):
        self.detected_info = info or {}
        values = [
            info.get("cpu", t("No detectado")),
            info.get("gpu", t("No detectado")),
            info.get("ram", t("No detectado")),
            info.get("os", t("No detectado")),
        ]
        self.hardware_panel.set_values(values)

    def _apply_hardware_filters(self):
        component_type = self._current_component_type()
        rows = self._rows_of_type(component_type)
        query = self.search_input.text().strip().lower()
        max_tdp = self._parse_tdp_filter(self.filter_combo.currentText())

        filtered = []
        for row in rows:
            component = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip()
            category = row.get("Categoria", "").strip()
            architecture = row.get("Arquitectura_Anio", "").strip()
            haystack = f"{component} {category} {architecture}".strip().lower()
            if query and query not in haystack:
                continue
            tdp_value = parse_number(row.get("TDP_Max_Watts", ""))
            if max_tdp is not None and tdp_value is not None and tdp_value > max_tdp:
                continue
            filtered.append(row)

        self._render_hardware_rows(filtered, component_type)

    def _render_hardware_rows(self, rows, component_type):
        rows_layout = self.rows_layout_by_type.get(component_type)
        if rows_layout is None:
            return
        _, extractor = self.column_specs[component_type]
        self._clear_layout(rows_layout)
        if not rows:
            rows_layout.addWidget(CatalogRow(t("Sin resultados"), "--", "--", "--", "--"))
            return

        for row in rows:
            component = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip()
            comp_type = row.get("Categoria", "--") or "--"
            col1, col2 = extractor(row)
            tdp = row.get("TDP_Max_Watts", "--") or "--"
            if tdp != "--" and not str(tdp).strip().lower().endswith("w"):
                tdp = f"{tdp}W"
            if not component:
                component = t("Hardware")
            rows_layout.addWidget(
                CatalogRow(
                    component,
                    comp_type,
                    col1,
                    col2,
                    tdp,
                    on_assign=self._handle_assign,
                    payload=row,
                )
            )

    def _parse_tdp_filter(self, text):
        if not text:
            return None
        if "todos" in text.lower() or "all" in text.lower():
            return None
        return parse_number(text)

    def _format_selection_summary(self):
        labels = {"GPU": t("GPU"), "CPU": t("CPU"), "RAM": t("RAM")}
        parts = []
        for component_type in self.COMPONENT_TYPES:
            row = self.selected_by_type.get(component_type)
            if row:
                name = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip() or t("Hardware")
            else:
                name = "--"
            parts.append(f"{labels[component_type]}: {name}")
        return t("Seleccionado: {summary}").format(summary="   |   ".join(parts))

    def _aggregate_selection(self):
        parts = []
        total_tdp = 0.0
        any_tdp = False
        for component_type in self.COMPONENT_TYPES:
            row = self.selected_by_type.get(component_type)
            if not row:
                continue
            name = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip()
            if name:
                parts.append(f"{component_type}: {name}")
            tdp_value = parse_number(row.get("TDP_Max_Watts", ""))
            if tdp_value is not None:
                total_tdp += tdp_value
                any_tdp = True
        return " | ".join(parts), (total_tdp if any_tdp else None)

    def _handle_assign(self, row):
        if not row:
            return
        component_type = (row.get("Tipo_Componente") or self._current_component_type()).strip().upper()
        if component_type not in self.selected_by_type:
            component_type = "GPU"
        self.selected_by_type[component_type] = row
        self.selection_summary.setText(self._format_selection_summary())

        name = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip()
        tdp_value = parse_number(row.get("TDP_Max_Watts", ""))
        self.rightsize_btn.setEnabled(tdp_value is not None)
        self.rightsize_result.setText(t("Hardware seleccionado: {name}").format(name=name))

        if not self.on_assign:
            return
        combined_name, combined_tdp = self._aggregate_selection()
        self.on_assign(hardware=combined_name, hardware_tdp=combined_tdp)

    _HW_TRADEMARK_PATTERN = re.compile(r"\((?:r|tm|c)\)", re.IGNORECASE)
    _HW_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
    _HW_MATCH_THRESHOLD = 0.55

    @classmethod
    def _normalize_hw_text(cls, text):
        """Strip (R)/(TM)/punctuation noise so detected strings compare cleanly with catalog names."""
        normalized = str(text or "").lower()
        normalized = cls._HW_TRADEMARK_PATTERN.sub(" ", normalized)
        normalized = cls._HW_NON_ALNUM_PATTERN.sub(" ", normalized)
        return " ".join(normalized.split())

    @classmethod
    def _hw_match_score(cls, model_text, detected_text):
        model_norm = cls._normalize_hw_text(model_text)
        detected_norm = cls._normalize_hw_text(detected_text)
        if not model_norm or not detected_norm:
            return 0.0
        model_tokens = set(model_norm.split())
        detected_tokens = set(detected_norm.split())
        token_overlap = len(model_tokens & detected_tokens) / len(model_tokens)
        fuzzy_ratio = SequenceMatcher(None, model_norm, detected_norm).ratio()
        return max(token_overlap, fuzzy_ratio)

    def _find_matching_row(self, component_type, detected_value):
        rows = self._rows_of_type(component_type)
        needle = (detected_value or "").strip()
        if not needle:
            return None
        if component_type == "RAM":
            detected_capacity = parse_number(needle)
            best, best_diff = None, None
            for row in rows:
                capacity = parse_number(row.get("Capacidad_GB", ""))
                if capacity is None or detected_capacity is None:
                    continue
                diff = abs(capacity - detected_capacity)
                if best_diff is None or diff < best_diff:
                    best, best_diff = row, diff
            return best
        best_row, best_score = None, 0.0
        for row in rows:
            score = self._hw_match_score(row.get("Modelo"), needle)
            if score > best_score:
                best_row, best_score = row, score
        return best_row if best_score >= self._HW_MATCH_THRESHOLD else None

    def _auto_select_detected(self):
        key_map = {"GPU": "gpu", "CPU": "cpu", "RAM": "ram"}
        selected_types = []
        unmatched_values = []
        for component_type in self.COMPONENT_TYPES:
            detected_value = (self.detected_info or {}).get(key_map[component_type], "")
            if not detected_value or detected_value == t("No detectado"):
                continue
            match = self._find_matching_row(component_type, detected_value)
            if match:
                self._handle_assign(match)
                selected_types.append(component_type)
            else:
                unmatched_values.append(str(detected_value))

        self._on_tab_changed(self.hardware_tabs.currentIndex())
        if selected_types:
            message = self._format_selection_summary()
            if unmatched_values:
                message += "\n" + t("No se encontró una coincidencia en el catálogo para: {valor}").format(
                    valor=", ".join(unmatched_values)
                )
            self.rightsize_result.setText(message)
        elif unmatched_values:
            self.rightsize_result.setText(
                t("No se encontró una coincidencia en el catálogo para: {valor}").format(
                    valor=", ".join(unmatched_values)
                )
            )
        else:
            self.rightsize_result.setText(t("No hay hardware local detectado todavía para {tipo}.").format(tipo="GPU / CPU / RAM"))

    def _suggest_rightsize(self):
        component_type = self._current_component_type()
        selected = self.selected_by_type.get(component_type) or {}
        current_tdp = parse_number(selected.get("TDP_Max_Watts", ""))
        current_tier = classify_cpu_tier(selected.get("Modelo", "")) if component_type == "CPU" else None
        candidates = []
        for row in self._rows_of_type(component_type):
            tdp = parse_number(row.get("TDP_Max_Watts", ""))
            if tdp is None:
                continue
            candidate = {"name": f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip(), "tdp_watts": tdp}
            if component_type == "CPU":
                candidate["performance_score"] = classify_cpu_tier(row.get("Modelo", ""))
            candidates.append(candidate)
        try:
            recommendation = rightsizing(current_tdp, candidates, current_performance=current_tier)
        except (TypeError, ValueError) as exc:
            self.rightsize_result.setText(t("No se pudo calcular la recomendación: {error}").format(error=exc))
            return
        if not recommendation:
            self.rightsize_result.setText(t("No existe una alternativa con ahorro superior al 10%.") )
            return
        candidate = recommendation["candidate"]
        self.rightsize_result.setText(
            t("Alternativa: {name} ({tdp:.0f} W), ahorro estimado {saving:.1f}%.").format(
                name=candidate["name"], tdp=candidate["tdp_watts"], saving=recommendation["saving_percent"]
            )
        )

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()


class PlaceholderView(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(make_label(title, "pageTitle"))
        layout.addWidget(make_separator("separator"))
        layout.addWidget(make_label(t("Vista en construcción"), "placeholderText"))


class MenuTriggerWidget(QWidget):
    def __init__(self, menu, parent=None):
        super().__init__(parent)
        self.menu = menu
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

    def mousePressEvent(self, event):
        if self.menu:
            self.menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        super().mousePressEvent(event)


class Sidebar(QFrame):
    def __init__(self, user_profile, on_logout=None, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("sidebar")
        self.expanded_width = 240
        self.collapsed_width = 76
        self.setFixedWidth(self.expanded_width)
        self.user_profile = user_profile
        self.on_logout = on_logout
        self.is_collapsed = False
        self.nav_buttons = []

        self.anim_group = QParallelAnimationGroup()
        self.anim_min = QPropertyAnimation(self, b"minimumWidth")
        self.anim_max = QPropertyAnimation(self, b"maximumWidth")
        self.anim_group.addAnimation(self.anim_min)
        self.anim_group.addAnimation(self.anim_max)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 18, 22)
        layout.setSpacing(18)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)

        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("hamburgerButton")
        self.toggle_button.setIcon(QIcon(make_hamburger_icon(18)))
        self.toggle_button.setIconSize(QSize(18, 18))
        self.toggle_button.setFixedSize(32, 32)
        self.toggle_button.setCursor(Qt.PointingHandCursor)
        self.toggle_button.clicked.connect(self._toggle_sidebar)

        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(make_leaf_pixmap(26))
        self.brand_icon.setFixedSize(QSize(26, 26))

        self.brand_title = make_label(t("SEMÁFORO IA"), "brandTitle")

        brand_row.addWidget(self.toggle_button)
        brand_row.addWidget(self.brand_icon)
        brand_row.addWidget(self.brand_title)
        brand_row.addStretch()

        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(6)

        layout.addLayout(brand_row)
        layout.addLayout(self.nav_layout)
        layout.addStretch()
        layout.addWidget(self._build_user_card())

    def add_nav_button(self, text, icon_pixmap):
        button = QPushButton(text)
        button.setObjectName("navButton")
        button.setIcon(QIcon(icon_pixmap))
        button.setIconSize(QSize(18, 18))
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)

        self.button_group.addButton(button)
        self.nav_layout.addWidget(button)
        label_key = i18n.key_for(text)
        self.nav_buttons.append((button, label_key))
        self._apply_nav_button_state(button, label_key)
        return button

    def _build_user_card(self):
        card = QFrame()
        card.setObjectName("userCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        user_name = self.user_profile.get("display_name", "Usuario")
        user_role = self.user_profile.get("role", "")
        photo_path = self.user_profile.get("profile_photo", "")

        avatar_pixmap = None
        avatar_pixmap_compact = None
        if photo_path:
            resolved = resolve_path(photo_path)
            avatar_pixmap = make_round_pixmap(resolved, 42)
            avatar_pixmap_compact = make_round_pixmap(resolved, 18)

        avatar_expanded = QLabel()
        avatar_compact = QLabel()
        if avatar_pixmap:
            avatar_expanded.setObjectName("userAvatar")
            avatar_expanded.setPixmap(avatar_pixmap)
            if avatar_pixmap_compact:
                avatar_compact.setObjectName("userAvatar")
                avatar_compact.setPixmap(avatar_pixmap_compact)
            else:
                avatar_compact.setObjectName("userInitial")
                avatar_compact.setText(user_name[:1].upper() if user_name else "?")
                avatar_compact.setAlignment(Qt.AlignCenter)
        else:
            initial = user_name[:1].upper() if user_name else "?"
            avatar_expanded.setText(initial)
            avatar_expanded.setObjectName("userInitial")
            avatar_expanded.setAlignment(Qt.AlignCenter)
            avatar_compact.setText(initial)
            avatar_compact.setObjectName("userInitial")
            avatar_compact.setAlignment(Qt.AlignCenter)

        avatar_expanded.setFixedSize(42, 42)
        avatar_compact.setFixedSize(18, 18)

        self.user_menu = self._build_account_menu()
        self.user_info = MenuTriggerWidget(self.user_menu)
        self.user_info.setObjectName("userInfo")
        self.user_info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info_layout = QVBoxLayout(self.user_info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)
        name_label = make_label(user_name, "userName")
        role_label = make_label(user_role, "userRole")
        chevron = QLabel("v")
        chevron.setObjectName("userChevron")
        chevron.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        chevron.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        chevron.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        role_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)
        name_row.addWidget(name_label, 1)
        name_row.addWidget(chevron, 0, Qt.AlignRight)

        info_layout.addLayout(name_row)
        info_layout.addWidget(role_label)

        self.user_compact_trigger = MenuTriggerWidget(self.user_menu)
        self.user_compact_trigger.setObjectName("userCompactTrigger")
        self.user_compact_trigger.setFixedSize(32, 32)
        compact_trigger_layout = QVBoxLayout(self.user_compact_trigger)
        compact_trigger_layout.setContentsMargins(0, 0, 0, 0)
        compact_trigger_layout.setSpacing(0)
        compact_trigger_layout.setAlignment(Qt.AlignCenter)
        avatar_compact.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        compact_trigger_layout.addWidget(avatar_compact, 0, Qt.AlignCenter)

        # Language Toggle Button
        self.user_card_expanded = QWidget()
        self.user_card_expanded.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        expanded_layout = QHBoxLayout(self.user_card_expanded)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        expanded_layout.setSpacing(12)
        expanded_layout.addWidget(avatar_expanded)
        expanded_layout.addWidget(self.user_info, 1)

        self.user_card_compact = QWidget()
        self.user_card_compact.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.user_card_compact.setFixedHeight(42)
        compact_layout = QVBoxLayout(self.user_card_compact)
        compact_layout.setContentsMargins(0, 0, 0, 0)
        compact_layout.setSpacing(0)
        compact_layout.setAlignment(Qt.AlignCenter)
        compact_layout.addWidget(self.user_compact_trigger, 0, Qt.AlignCenter)

        self.user_card_compact.setVisible(False)

        card_layout.addWidget(self.user_card_expanded)
        card_layout.addWidget(self.user_card_compact)

        return card

    def _build_account_menu(self):
        menu = QMenu(self)
        menu.setObjectName("accountMenu")

        def add_header(text):
            action = menu.addAction(t(text))
            action.setEnabled(False)
            return action

        def add_action(text, handler=None):
            action = menu.addAction(t(text))
            if handler:
                action.triggered.connect(handler)
            return action

        add_header("Perfil")
        add_action("Editar perfil")
        add_action("Actualizar foto")
        add_action("Datos personales")
        menu.addSeparator()

        add_header("Preferencias")
        add_action("Notificaciones")

        self.lang_action = menu.addAction(t("Idioma y zona horaria"))

        add_action("Accesibilidad")
        menu.addSeparator()

        add_header("Seguridad")
        add_action("Cambiar contrasena")
        add_action("Dispositivos vinculados")
        add_action("Verificacion en dos pasos")

        role = str(self.user_profile.get("role", "")).lower()
        if "admin" in role:
            menu.addSeparator()
            add_header("Usuarios")
            add_action("Crear usuario")
            add_action("Resetear contrasena")
            add_action("Desactivar usuario")
            add_action("Editar roles")
            menu.addSeparator()
            add_header("Permisos")
            add_action("Roles y permisos")
            add_action("Grupos")
            add_action("Accesos temporales")
            menu.addSeparator()
            add_header("Sistema")
            add_action("Backup y restauracion")
            add_action("Integraciones")
            add_action("Parametros globales")

        menu.addSeparator()
        add_header("Sesion")
        add_action("Cerrar sesion en otros equipos")
        add_action("Salir de la cuenta", self.on_logout)

        return menu

    def _toggle_sidebar(self):
        self.is_collapsed = not self.is_collapsed
        self._apply_sidebar_state()

    def _apply_sidebar_state(self):
        target_width = self.collapsed_width if self.is_collapsed else self.expanded_width

        self.anim_group.stop()
        self.anim_min.setStartValue(self.width())
        self.anim_min.setEndValue(target_width)
        self.anim_min.setDuration(260)
        self.anim_min.setEasingCurve(QEasingCurve.InOutCubic)

        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(target_width)
        self.anim_max.setDuration(260)
        self.anim_max.setEasingCurve(QEasingCurve.InOutCubic)

        self.anim_group.start()

        self.brand_icon.setVisible(not self.is_collapsed)
        self.brand_title.setVisible(not self.is_collapsed)
        self.user_card_expanded.setVisible(not self.is_collapsed)
        self.user_card_compact.setVisible(self.is_collapsed)

        if self.is_collapsed:
            self.user_compact_trigger.setToolTip(t("Cuenta"))
            self.user_info.setToolTip("")
        else:
            self.user_compact_trigger.setToolTip("")
            self.user_info.setToolTip(t("Cuenta"))

        for button, label in self.nav_buttons:
            self._apply_nav_button_state(button, label)

    def _apply_nav_button_state(self, button, label):
        translated_label = t(label)
        if self.is_collapsed:
            button.setText("")
            button.setToolTip(translated_label)
        else:
            button.setText(translated_label)
            button.setToolTip("")

        button.setProperty("collapsed", self.is_collapsed)
        button.style().unpolish(button)
        button.style().polish(button)


class DashboardWindow(QMainWindow):
    def __init__(self, user_profile=None):
        super().__init__()

        self.setWindowTitle(t("Semáforo IA"))
        self.setWindowIcon(QIcon(make_leaf_pixmap(64)))
        self.resize(1200, 720)

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        config = load_config()
        if user_profile is None:
            config = load_config()
            user_profile = get_default_user(config)

        sidebar = Sidebar(user_profile, self._handle_logout)
        self.sidebar = sidebar
        self.stack = QStackedWidget()
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        self.fade_effect = QGraphicsOpacityEffect(self.stack)
        self.stack.setGraphicsEffect(self.fade_effect)
        self.fade_anim = QPropertyAnimation(self.fade_effect, b"opacity")
        self.fade_anim.setDuration(350)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade_anim.finished.connect(lambda: self.fade_effect.setEnabled(False))

        content_frame = QFrame()
        content_frame.setObjectName("contentFrame")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.addWidget(self.stack)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(content_frame, 1)

        self.selection_state = {
            "provider": "",
            "region": "",
            "region_intensity": None,
            "model": "",
            "model_energy": None,
            "hardware": "",
            "hardware_tdp": None,
        }
        self.current_score = None
        self.current_green_score = None
        self.current_semaphore_level = None
        self.current_lang = i18n.load_saved_language()

        self.home_view = HomeView(main_window=self)
        self.models_view = ModelsView(on_selection=self._handle_model_selection)
        self.hardware_view = HardwareCatalogView(on_assign=self._handle_hardware_assign, profile=user_profile)
        self.cloud_view = CloudView(on_selection=self._handle_cloud_selection)
        self.projects_view = ProjectsView(profile=user_profile, main_window=self)
        self.environmental_view = EnvironmentalPerformanceView(main_window=self)
        self.finops_view = FinOpsView(main_window=self)

        sidebar.lang_action.triggered.connect(self._toggle_language)
        self.header_title = self.home_view.findChild(QLabel, "pageTitle")

        self._add_nav_item(sidebar, t("Inicio"), make_home_icon(), self.home_view)
        self._add_nav_item(sidebar, t("Modelos"), make_grid_icon(), self.models_view)
        self._add_nav_item(
            sidebar,
            t("Proyectos"),
            make_text_icon("P", 18, "#66bb22"),
            self.projects_view,
        )
        self._add_nav_item(
            sidebar,
            t("Impacto Ambiental"),
            make_leaf_pixmap(18, "#66bb22"),
            self.environmental_view,
        )
        self._add_nav_item(
            sidebar,
            t("Costos FinOps"),
            make_text_icon("$", 18, "#66bb22"),
            self.finops_view,
        )
        self._add_nav_item(
            sidebar,
            t("Comparativas"),
            make_bars_icon(),
            CarbonDetailView(on_apply_recommendation=self._apply_recommendation),
        )
        self._add_nav_item(sidebar, t("Hardware"), make_chip_icon(), self.hardware_view)
        self._add_nav_item(sidebar, t("Cloud"), make_cloud_icon(), self.cloud_view)
        self._add_nav_item(sidebar, t("Historial"), make_clock_icon(), HistoryView())
        self._add_nav_item(sidebar, t("Ajustes"), make_gear_icon(), SettingsView(main_window=self))

        self._add_nav_item(
            sidebar,
            t("Administracion"),
            make_gear_icon(),
            AdminMenuView(user_profile, on_logout=self._handle_logout, main_window=self),
        )

        sidebar.button_group.buttons()[0].setChecked(True)
        self.stack.setCurrentIndex(0)

    def refresh_projects_view(self):
        self.projects_view.request_refresh()
        self.environmental_view.refresh_project_data()
        self.finops_view.refresh_project_data()

    def get_active_project_metrics(self):
        project_id = load_config().get("current_project_id")
        if project_id is None:
            return None
        store = None
        try:
            store = bootstrap_store(load_config(), writable_path("semaforo.sqlite3"))
            project = store.connection.execute(
                "SELECT name FROM projects WHERE id = ? AND is_active = 1", (project_id,)
            ).fetchone()
            if not project:
                return None
            row = store.connection.execute(
                """SELECT COUNT(*) AS count, COALESCE(SUM(e.cost), 0) AS cost,
                          COALESCE(SUM(e.carbon), 0) AS carbon, COALESCE(SUM(e.kwh), 0) AS kwh,
                          COALESCE(SUM(e.duration_ms), 0) AS duration_ms,
                          MAX(e.timestamp) AS latest_timestamp
                     FROM executions e JOIN models m ON m.id = e.model_id
                    WHERE m.project_id = ? AND m.is_active = 1""",
                (project_id,),
            ).fetchone()
            return {"project_name": project["name"], **dict(row)}
        except (OSError, ValueError):
            return None
        finally:
            if store is not None:
                store.close()

    def _add_nav_item(self, sidebar, label, icon, widget):
        button = sidebar.add_nav_button(label, icon)
        index = self.stack.addWidget(widget)
        def on_click(checked=False, idx=index):
            if self.stack.currentIndex() != idx:
                self.fade_effect.setEnabled(True)
                self.fade_anim.stop()
                self.fade_anim.setStartValue(self.fade_effect.opacity())
                self.fade_anim.setEndValue(1.0)
                self.fade_effect.setOpacity(0.0)
                self.stack.setCurrentIndex(idx)
                self.fade_anim.start()
        button.clicked.connect(on_click)
        return button

    def _handle_logout(self):
        self.login_window = LoginWindow()
        self.login_window.show()
        self.close()

    def closeEvent(self, event):
        for view in self.findChildren(FinOpsView):
            view.shutdown()
        super().closeEvent(event)

    def _handle_cloud_selection(self, provider=None, region=None, region_intensity=None):
        if provider is not None:
            self.selection_state["provider"] = provider
        if region is not None:
            self.selection_state["region"] = region
        self.selection_state["region_intensity"] = region_intensity
        self._update_semaforo()

    def _handle_model_selection(self, model=None, model_energy=None):
        if model is not None:
            self.selection_state["model"] = model
        self.selection_state["model_energy"] = model_energy
        self._update_semaforo()

    def _handle_hardware_assign(self, hardware=None, hardware_tdp=None):
        if hardware is not None:
            self.selection_state["hardware"] = hardware
        self.selection_state["hardware_tdp"] = hardware_tdp
        self._update_semaforo()

    def _apply_recommendation(self):
        current_tdp = self.selection_state.get("hardware_tdp")
        if current_tdp is None:
            QMessageBox.warning(self, t("Recomendación"), t("Selecciona primero un hardware válido."))
            return
        candidates = []
        for row in self.hardware_view.hardware_rows:
            tdp = parse_number(row.get("TDP_Max_Watts"))
            if tdp is not None:
                name = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip()
                candidates.append({"name": name, "tdp_watts": tdp})
        try:
            recommendation = rightsizing(current_tdp, candidates)
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, t("Recomendación"), str(exc))
            return
        if not recommendation:
            QMessageBox.information(self, t("Recomendación"), t("No existe una alternativa con ahorro superior al 10%."))
            return
        candidate = recommendation["candidate"]
        self._handle_hardware_assign(candidate["name"], candidate["tdp_watts"])
        QMessageBox.information(
            self,
            t("Recomendación Aplicada"),
            t("Hardware actualizado: {name}. Ahorro estimado: {saving:.1f}%.").format(
                name=candidate["name"], saving=recommendation["saving_percent"]
            ),
        )

    def _toggle_language(self):
        """Cicla entre todos los idiomas definidos en locales/translations.json."""
        self.set_language(i18n.next_language(self.current_lang))

    def set_language(self, lang_code):
        """Aplica `lang_code` a toda la aplicacion (ventanas, dialogos y reportes)."""
        if lang_code not in i18n.available_languages():
            return
        i18n.set_language(lang_code)
        i18n.save_language(lang_code)
        self.current_lang = lang_code

        from PySide6.QtWidgets import (
            QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
            QRadioButton, QGroupBox, QToolButton,
        )
        from PySide6.QtGui import QAction

        text_widget_classes = (
            QLabel, QPushButton, QCheckBox, QRadioButton, QToolButton,
        )
        for widget_cls in text_widget_classes:
            for widget in self.findChildren(widget_cls):
                current_text = widget.text()
                translated = i18n.t(current_text, lang_code)
                if translated != current_text:
                    widget.setText(translated)
                tooltip = widget.toolTip()
                if tooltip:
                    translated_tip = i18n.t(tooltip, lang_code)
                    if translated_tip != tooltip:
                        widget.setToolTip(translated_tip)

        for widget in self.findChildren(QGroupBox):
            current_title = widget.title()
            translated = i18n.t(current_title, lang_code)
            if translated != current_title:
                widget.setTitle(translated)

        # Also translate default descriptions in StatusCards
        if hasattr(self, 'home_view'):
            for card in self.home_view.status_cards.values():
                card.default_description = i18n.t(card.default_description, lang_code)
                # If not currently selected (i.e. showing default description), update it visually
                if not card.property("selected"):
                    card.update_description(card.default_description)

        for widget in self.findChildren(QLineEdit):
            current_text = widget.placeholderText()
            if current_text:
                translated = i18n.t(current_text, lang_code)
                if translated != current_text:
                    widget.setPlaceholderText(translated)
            tooltip = widget.toolTip()
            if tooltip:
                translated_tip = i18n.t(tooltip, lang_code)
                if translated_tip != tooltip:
                    widget.setToolTip(translated_tip)

        for widget in self.findChildren(QComboBox):
            for i in range(widget.count()):
                current_text = widget.itemText(i)
                translated = i18n.t(current_text, lang_code)
                if translated != current_text:
                    widget.setItemText(i, translated)

        # Translate Menu Actions (incluye menus de cuenta y export)
        for action in self.findChildren(QAction):
            current_text = action.text()
            translated = i18n.t(current_text, lang_code)
            if translated != current_text:
                action.setText(translated)

        # Force re-render of active card with correct language
        if hasattr(self, 'home_view') and hasattr(self, 'current_score'):
            for key, card in self.home_view.status_cards.items():
                if card.property("selected"):
                    self.home_view.set_semaforo_level(key, self.current_score, self.current_green_score)

        self._update_semaforo()

    def _update_semaforo(self):
        if not self.home_view:
            return

        provider = self.selection_state.get("provider")
        region = self.selection_state.get("region")
        model = self.selection_state.get("model")
        hardware = self.selection_state.get("hardware")
        intensity = self.selection_state.get("region_intensity")
        tdp = self.selection_state.get("hardware_tdp")
        model_energy = self.selection_state.get("model_energy")

        if not (provider and region and model and hardware):
            self.home_view.set_semaforo_level(None, None)
            self.current_score = None
            self.current_green_score = None
            self.current_semaphore_level = None
            return
        if intensity is None or tdp is None:
            self.home_view.set_semaforo_level(None, None)
            self.current_score = None
            self.current_green_score = None
            self.current_semaphore_level = None
            return

        try:
            # La seleccion actual aporta TDP y CIF; una ejecucion inicial se modela a una hora.
            score = calculate_carbon(tdp, 1.0, 1.0, intensity)
            config = load_config()
            thresholds_config = config.get("thresholds", {})
            thresholds = validate_thresholds(
                thresholds_config.get("green", 50),
                thresholds_config.get("yellow", 90),
                thresholds_config.get("red", 100),
            )
            impact_percent = score / 10.0
            green_score_value, _ = green_score(0, 1, score, 1000)
            level = semaphore_level(impact_percent, *thresholds)
        except (TypeError, ValueError):
            self.home_view.set_semaforo_level(None, None)
            self.current_score = None
            self.current_green_score = None
            self.current_semaphore_level = None
            return
        self.current_score = score
        self.current_green_score = green_score_value
        self.current_semaphore_level = level
        status_level = {"Verde": "bajo", "Amarillo": "moderado", "Rojo": "alto"}[level]
        self.home_view.set_semaforo_level(status_level, score, green_score_value)


def apply_stylesheet(app):
    app.setStyleSheet(
        "QWidget {"
        "  background-color: #0b0b0b;"
        "  color: #f4f4f4;"
        "  font-family: 'Segoe UI';"
        "}"
        "QLabel {"
        "  background: transparent;"
        "}"
        "QLineEdit {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 10px;"
        "  padding: 8px 12px;"
        "  font-size: 13px;"
        "}"
        "QLineEdit:focus {"
        "  border: 1px solid #ffffff;"
        "}"
        "QFrame#sidebar {"
        "  background-color: #0f0f0f;"
        "  border-right: 1px solid #1e1e1e;"
        "}"
        "QPushButton#hamburgerButton {"
        "  background-color: #111111;"
        "  border: 1px solid #2a2a2a;"
        "  border-radius: 8px;"
        "}"
        "QPushButton#hamburgerButton:hover {"
        "  background-color: #1a1a1a;"
        "  border: 1px solid #f0f0f0;"
        "}"
        "QLabel#brandTitle {"
        "  font-size: 18px;"
        "  font-weight: 700;"
        "  letter-spacing: 0.6px;"
        "}"
        "QPushButton#navButton {"
        "  background: transparent;"
        "  border: none;"
        "  color: #e6e6e6;"
        "  padding: 10px 12px;"
        "  border-radius: 12px;"
        "  text-align: left;"
        "}"
        "QPushButton#navButton[collapsed=\"true\"] {"
        "  padding: 10px 0px;"
        "  text-align: center;"
        "}"
        "QPushButton#navButton:hover {"
        "  background-color: #171717;"
        "}"
        "QPushButton#navButton:checked {"
        "  background-color: #2a3a17;"
        "  border: 1px solid #3a5220;"
        "  color: #ffffff;"
        "}"
        "QFrame#userCard {"
        "  background-color: #101010;"
        "  border: 1px solid #242424;"
        "  border-radius: 16px;"
        "}"
        "QFrame#accountHeader {"
        "  background-color: #111111;"
        "  border: 1px solid #242424;"
        "  border-radius: 16px;"
        "}"
        "QLabel#accountAvatarFallback {"
        "  background-color: #151515;"
        "  border: 1px solid #2a2a2a;"
        "  border-radius: 27px;"
        "  font-weight: 700;"
        "}"
        "QLabel#accountName {"
        "  font-size: 15px;"
        "  font-weight: 700;"
        "}"
        "QLabel#accountRole {"
        "  font-size: 12px;"
        "  color: #b0b0b0;"
        "}"
        "QLabel#accountMeta {"
        "  font-size: 12px;"
        "  color: #8f8f8f;"
        "}"
        "QLabel#userInitial {"
        "  background-color: #151515;"
        "  border: 1px solid #2a2a2a;"
        "  border-radius: 21px;"
        "  font-weight: 600;"
        "}"
        "QLabel#userAvatar {"
        "  border: 1px solid #2a2a2a;"
        "  border-radius: 21px;"
        "  background: #101010;"
        "  background-color: #101010;"
        "}"
        "QLabel#userName {"
        "  font-size: 13px;"
        "  font-weight: 600;"
        "}"
        "QLabel#userRole {"
        "  font-size: 11px;"
        "  color: #9a9a9a;"
        "}"
        "QWidget#userInfo, QWidget#userCompactTrigger {"
        "  background: #101010;"
        "  background-color: #101010;"
        "  border: none;"
        "  border-radius: 0px;"
        "}"
        "QFrame#userCard QLabel {"
        "  background: transparent;"
        "  background-color: transparent;"
        "}"
        "QLabel#userChevron {"
        "  color: #8a8a8a;"
        "  font-size: 12px;"
        "}"
        "QLabel#comboChevron {"
        "  color: #d9d9d9;"
        "  font-size: 12px;"
        "}"
        "QLabel#userName, QLabel#userRole {"
        "  background: transparent;"
        "}"
        "QFrame#contentFrame {"
        "  background-color: #0b0b0b;"
        "}"
        "QFrame#loginPanel {"
        "  background-color: #0d0d0d;"
        "  border-left: 1px solid #1d1d1d;"
        "}"
        "QLabel#loginBrand {"
        "  font-size: 52px;"
        "  font-weight: 700;"
        "  letter-spacing: 2px;"
        "  font-family: 'Georgia';"
        "}"
        "QLabel#loginCaption {"
        "  font-size: 13px;"
        "  color: #cfcfcf;"
        "}"
        "QLabel#loginTitle {"
        "  font-size: 22px;"
        "  font-weight: 700;"
        "}"
        "QLabel#loginLabel {"
        "  font-size: 13px;"
        "  color: #d8d8d8;"
        "}"
        "QLabel#loginHint {"
        "  font-size: 12px;"
        "  color: #9a9a9a;"
        "}"
        "QLabel#loginError {"
        "  font-size: 12px;"
        "  color: #ff6b6b;"
        "}"
        "QLineEdit#loginInput {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 10px;"
        "  padding: 8px 12px;"
        "  font-size: 13px;"
        "}"
        "QPushButton#loginButton {"
        "  background-color: #0f0f0f;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 12px;"
        "  padding: 8px 16px;"
        "  font-weight: 600;"
        "}"
        "QPushButton#loginButton:hover {"
        "  background-color: #1a1a1a;"
        "}"
        "QFrame#loginUserCard {"
        "  background-color: #111111;"
        "  border: 1px solid #222222;"
        "  border-radius: 12px;"
        "}"
        "QLabel#loginUserName {"
        "  font-size: 12px;"
        "  font-weight: 600;"
        "}"
        "QLabel#loginUserRole {"
        "  font-size: 11px;"
        "  color: #9a9a9a;"
        "}"
        "QLabel#loginAvatarFallback {"
        "  background-color: #151515;"
        "  border: 1px solid #2a2a2a;"
        "  border-radius: 17px;"
        "}"
        "QFrame#metricCard, QFrame#summaryPanel, QFrame#summaryCard {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 18px;"
        "}"
        "QFrame#summaryPanel {"
        "  background-color: #111111;"
        "}"
        "QFrame#metricCard:hover, QFrame#summaryCard:hover {"
        "  background-color: #171717;"
        "  border: 1px solid #ffffff;"
        "}"
        "QFrame#kpiCard, QFrame#activityPanel, QFrame#catalogPanel {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 18px;"
        "}"
        "QFrame#performanceCard, QFrame#detailsPanel, QFrame#hardwarePanel, QFrame#statusCard, QFrame#infoBar, QFrame#infoCard, QFrame#listPanel, QFrame#cloudPanel {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 18px;"
        "}"
        "QFrame#cloudSelector {"
        "  background-color: transparent;"
        "}"
        "QFrame#activityPanel {"
        "  background-color: #121212;"
        "}"
        "QFrame#infoBar {"
        "  background-color: #101010;"
        "}"
        "QFrame#infoBar[compact=\"true\"] {"
        "  background-color: #0f0f0f;"
        "  border-radius: 12px;"
        "}"
        "QFrame#infoBar[compact=\"true\"] QLabel#infoTitle {"
        "  font-size: 11px;"
        "}"
        "QFrame#infoBar[compact=\"true\"] QLabel#infoText {"
        "  font-size: 10px;"
        "}"
        "QFrame#detailModal {"
        "  background-color: #111111;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 28px;"
        "}"
        "QFrame#statusNote {"
        "  background-color: #0f0f0f;"
        "  border: 1px solid #2a2a2a;"
        "  border-radius: 12px;"
        "}"
        "QFrame#statusCard[selected=\"true\"] {"
        "  border: 2px solid #f2f2f2;"
        "}"
        "QFrame#statusCard[level=\"alto\"][selected=\"true\"] {"
        "  border: 2px solid #b60f0f;"
        "}"
        "QFrame#statusCard[level=\"moderado\"][selected=\"true\"] {"
        "  border: 2px solid #c4a600;"
        "}"
        "QFrame#statusCard[level=\"bajo\"][selected=\"true\"] {"
        "  border: 2px solid #4eb541;"
        "}"
        "QFrame#catalogHeader {"
        "  background-color: #1b1b1b;"
        "  border: 1px solid #2c2c2c;"
        "  border-radius: 12px;"
        "}"
        "QProgressBar#standardProgressBar {"
        "  border: none;"
        "  background: #2a2a2a;"
        "  border-radius: 6px;"
        "  text-align: center;"
        "}"
        "QProgressBar#standardProgressBar::chunk {"
        "  background: #4eb541;"
        "  border-radius: 6px;"
        "}"
        "QScrollArea#catalogScroll {"
        "  background: transparent;"
        "  border: none;"
        "}"
        "QScrollArea#catalogScroll QWidget {"
        "  background: transparent;"
        "}"
        "QFrame#projectListFrame {"
        "  background: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 18px;"
        "}"
        "QScrollArea#projectHistoryListScroll, QScrollArea#mlflowRunsListScroll {"
        "  background: transparent;"
        "  border: none;"
        "}"
        "QScrollArea#projectHistoryListScroll QWidget, QScrollArea#mlflowRunsListScroll QWidget, QFrame#projectListPanel {"
        "  background: transparent;"
        "  border: none;"
        "  border-radius: 0px;"
        "}"
        "QFrame#projectListPanel QFrame#listLine {"
        "  background-color: #454545;"
        "}"
        "QScrollArea#projectHistoryListScroll QScrollBar:vertical, QScrollArea#mlflowRunsListScroll QScrollBar:vertical {"
        "  background: transparent;"
        "  width: 14px;"
        "  margin: 6px 3px 6px 0;"
        "}"
        "QScrollArea#projectHistoryListScroll QScrollBar::handle:vertical, QScrollArea#mlflowRunsListScroll QScrollBar::handle:vertical {"
        "  background: #4a4a4a;"
        "  border-radius: 4px;"
        "  margin: 0 1px;"
        "  min-height: 28px;"
        "}"
        "QScrollArea#projectHistoryListScroll QScrollBar::handle:vertical:hover, QScrollArea#mlflowRunsListScroll QScrollBar::handle:vertical:hover {"
        "  background: #777777;"
        "}"
        "QScrollArea#projectHistoryListScroll QScrollBar::add-line:vertical, QScrollArea#projectHistoryListScroll QScrollBar::sub-line:vertical, QScrollArea#mlflowRunsListScroll QScrollBar::add-line:vertical, QScrollArea#mlflowRunsListScroll QScrollBar::sub-line:vertical {"
        "  height: 0px;"
        "}"
        "QScrollArea#projectHistoryListScroll QScrollBar::add-page:vertical, QScrollArea#projectHistoryListScroll QScrollBar::sub-page:vertical, QScrollArea#mlflowRunsListScroll QScrollBar::add-page:vertical, QScrollArea#mlflowRunsListScroll QScrollBar::sub-page:vertical {"
        "  background: transparent;"
        "}"
        "QMenu#accountMenu {"
        "  background-color: #111111;"
        "  border: 1px solid #2a2a2a;"
        "}"
        "QMenu#accountMenu::item {"
        "  padding: 6px 16px;"
        "}"
        "QMenu#accountMenu::item:selected {"
        "  background-color: #1a1a1a;"
        "}"
        "QMenu#accountMenu::separator {"
        "  height: 1px;"
        "  background: #2a2a2a;"
        "  margin: 4px 10px;"
        "}"
        "QMenu#accountMenu::item:disabled {"
        "  color: #7a7a7a;"
        "  background: transparent;"
        "}"
        "QFrame#menuSection {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 18px;"
        "}"
        "QLabel#menuSectionTitle {"
        "  font-size: 14px;"
        "  font-weight: 600;"
        "}"
        "QFrame#menuSectionLine {"
        "  background-color: #2a2a2a;"
        "}"
        "QPushButton#menuButton {"
        "  background-color: #111111;"
        "  border: 1px solid #3a3a3a;"
        "  border-radius: 10px;"
        "  padding: 6px 12px;"
        "  text-align: left;"
        "}"
        "QPushButton#menuButton:hover {"
        "  background-color: #1a1a1a;"
        "  border: 1px solid #f0f0f0;"
        "}"
        "QPushButton#logoutButton {"
        "  background-color: #1a0f0f;"
        "  border: 1px solid #7a1a1a;"
        "  border-radius: 10px;"
        "  padding: 6px 12px;"
        "  color: #ffb3b3;"
        "  text-align: left;"
        "  font-weight: 600;"
        "}"
        "QPushButton#logoutButton:hover {"
        "  background-color: #2a1010;"
        "  border: 1px solid #ff7070;"
        "}"
        "QFrame#catalogRow {"
        "  background-color: transparent;"
        "  border-bottom: 1px solid #2c2c2c;"
        "  border-radius: 10px;"
        "}"
        "QFrame#catalogRow:hover {"
        "  background-color: #171717;"
        "  border: 1px solid #3a3a3a;"
        "  border-bottom: 1px solid #3a3a3a;"
        "}"
        "QFrame#statusCard {"
        "  background-color: #141414;"
        "  border: 1px solid #2b2b2b;"
        "  border-radius: 22px;"
        "}"
        "QFrame#statusCard:hover {"
        "  border: 1px solid #5a5a5a;"
        "  background-color: #181818;"
        "}"
        "QLabel#pageTitle {"
        "  font-size: 26px;"
        "  font-weight: 700;"
        "}"
        "QLabel#performanceTitle {"
        "  font-size: 13px;"
        "  color: #d6d6d6;"
        "}"
        "QLabel#performanceValue {"
        "  font-size: 28px;"
        "  font-weight: 700;"
        "}"
        "QLabel#detailsTitle {"
        "  font-size: 15px;"
        "  font-weight: 600;"
        "}"
        "QLabel#detailLabel {"
        "  font-size: 13px;"
        "  color: #cfcfcf;"
        "}"
        "QLabel#detailValue {"
        "  font-size: 13px;"
        "  font-weight: 600;"
        "}"
        "QLabel#statusTitle {"
        "  font-size: 14px;"
        "  font-weight: 600;"
        "}"
        "QLabel#statusNoteText {"
        "  font-size: 12px;"
        "  color: #d6d6d6;"
        "}"
        "QLabel#infoTitle {"
        "  font-size: 14px;"
        "  font-weight: 600;"
        "}"
        "QLabel#infoText {"
        "  font-size: 12px;"
        "  color: #d6d6d6;"
        "}"
        "QLabel#modalTitle {"
        "  font-size: 18px;"
        "  font-weight: 700;"
        "}"
        "QLabel#modalBody {"
        "  font-size: 13px;"
        "  color: #d6d6d6;"
        "}"
        "QLabel#modalBullet {"
        "  font-size: 13px;"
        "  color: #e6e6e6;"
        "}"
        "QLabel#infoCardTitle {"
        "  font-size: 12px;"
        "  color: #bfbfbf;"
        "  background: transparent;"
        "}"
        "QLabel#infoCardValue {"
        "  font-size: 18px;"
        "  font-weight: 700;"
        "  background: transparent;"
        "}"
        "QLabel#cloudLabel {"
        "  font-size: 12px;"
        "  color: #cfcfcf;"
        "  background: transparent;"
        "}"
        "QLabel#listTitle {"
        "  font-size: 15px;"
        "  font-weight: 600;"
        "}"
        "QLabel#listItem {"
        "  font-size: 13px;"
        "  color: #e0e0e0;"
        "}"
        "QLabel#placeholderText {"
        "  color: #8f8f8f;"
        "  font-size: 14px;"
        "}"
        "QLabel#titleLabel {"
        "  font-size: 26px;"
        "  font-weight: 700;"
        "}"
        "QLabel#sectionTitle {"
        "  font-size: 18px;"
        "  font-weight: 600;"
        "}"
        "QLabel#kpiTitle {"
        "  font-size: 14px;"
        "  color: #d0d0d0;"
        "}"
        "QLabel#kpiValue {"
        "  font-size: 28px;"
        "  font-weight: 700;"
        "}"
        "QLabel#activityTitle {"
        "  font-size: 20px;"
        "  font-weight: 700;"
        "}"
        "QLabel#activityItem {"
        "  font-size: 13px;"
        "  color: #d6d6d6;"
        "}"
        "QLabel#catalogHeaderLabel {"
        "  font-size: 13px;"
        "  font-weight: 600;"
        "  color: #f1f1f1;"
        "}"
        "QLabel#catalogCell {"
        "  font-size: 13px;"
        "  color: #ededed;"
        "}"
        "QLabel#metricTitle {"
        "  font-size: 13px;"
        "  color: #cfcfcf;"
        "  text-transform: uppercase;"
        "  letter-spacing: 0.6px;"
        "}"
        "QLabel#metricValue {"
        "  font-size: 18px;"
        "  font-weight: 600;"
        "}"
        "QLabel#metricPercent {"
        "  font-size: 16px;"
        "  font-weight: 600;"
        "  color: #f7f7f7;"
        "}"
        "QLabel#summaryLabel {"
        "  font-size: 13px;"
        "  color: #c2c2c2;"
        "}"
        "QLabel#summaryValue {"
        "  font-size: 20px;"
        "  font-weight: 700;"
        "}"
        "QFrame#separator, QFrame#contentLine, QFrame#detailLine, QFrame#listLine, QFrame#statusDivider {"
        "  background-color: #2a2a2a;"
        "}"
        "QLineEdit#searchInput {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 10px;"
        "  padding: 8px 14px;"
        "  font-size: 13px;"
        "}"
        "QLineEdit#searchInput::placeholder {"
        "  color: #7f7f7f;"
        "}"
        "QComboBox#filterCombo, QComboBox#cloudSelect {"
        "  background-color: #141414;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 10px;"
        "  padding: 6px 30px 6px 12px;"
        "  font-size: 13px;"
        "}"
        "QComboBox#filterCombo::drop-down, QComboBox#cloudSelect::drop-down {"
        "  border: none;"
        "  width: 24px;"
        "  subcontrol-origin: padding;"
        "  subcontrol-position: top right;"
        "}"
        "QComboBox#filterCombo::down-arrow, QComboBox#cloudSelect::down-arrow {"
        "  image: none;"
        "  width: 0px;"
        "  height: 0px;"
        "}"
        "QPushButton#assignButton {"
        "  background-color: #111111;"
        "  border: 1px solid #5a5a5a;"
        "  border-radius: 10px;"
        "  padding: 4px 14px;"
        "  color: #f1f1f1;"
        "}"
        "QPushButton#assignButton:hover {"
        "  background-color: #1a1a1a;"
        "  border: 1px solid #f0f0f0;"
        "}"
        "QPushButton#primaryButton {"
        "  background-color: #111111;"
        "  border: 1px solid #f2f2f2;"
        "  border-radius: 12px;"
        "  padding: 8px 20px;"
        "  font-weight: 600;"
        "}"
        "QPushButton#primaryButton:hover {"
        "  background-color: #1a1a1a;"
        "}"
        "QPushButton#secondaryButton {"
        "  background-color: transparent;"
        "  border: 1px solid #5a5a5a;"
        "  border-radius: 12px;"
        "  padding: 8px 20px;"
        "  font-weight: 600;"
        "  color: #d8d8d8;"
        "}"
        "QPushButton#secondaryButton:hover {"
        "  background-color: #171717;"
        "  border: 1px solid #a0a0a0;"
        "  color: #ffffff;"
        "}"
        "QPushButton#assignButton:hover {"
        "  background-color: #1a1a1a;"
        "  border: 1px solid #d8d8d8;"
        "  color: #ffffff;"
        "}"
        "QFrame#catalogRow:hover QLabel#catalogCell {"
        "  color: #ffffff;"
        "}"
        "QPushButton#dangerButton {"
        "  background-color: transparent;"
        "  border: 1px solid #b60f0f;"
        "  border-radius: 12px;"
        "  padding: 8px 20px;"
        "  font-weight: 600;"
        "  color: #ff6b6b;"
        "}"
        "QPushButton#dangerButton:hover {"
        "  background-color: #3a1010;"
        "  border: 1px solid #ff4d4d;"
        "  color: #ffffff;"
        "}"
    )


def _bootstrap_mlflow_autostart():
    """Arranca (o detecta) un MLflow Tracking Server local en un hilo aparte, sin bloquear la UI.

    Si ya hay un servidor real accesible (local o el configurado por el usuario), no hace
    nada mas que confirmarlo; si no hay ninguno, levanta uno local y guarda su URI real en
    config.json apenas responde, para que el resto de la app lo use sin configuracion manual.
    """
    def save_uri(uri):
        config_path = writable_path("config.json")
        try:
            config = load_config()
            if config.get("mlflow_tracking_uri") != uri:
                config["mlflow_tracking_uri"] = uri
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, ensure_ascii=True, indent=2)
        except OSError:
            pass

    def worker():
        import mlflow_integration
        try:
            mlflow_integration.start_local_server_if_needed(load_config(), save_config_callback=save_uri)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _shutdown_mlflow_autostart():
    import mlflow_integration
    mlflow_integration.stop_local_server()


def _bootstrap_ollama_autostart():
    """Detecta o arranca un servidor Ollama local (si el binario esta instalado), sin bloquear la UI."""
    def worker():
        import ollama_integration
        try:
            ollama_integration.start_local_server_if_needed()
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _shutdown_ollama_autostart():
    import ollama_integration
    ollama_integration.stop_local_server()


def main():
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    instance_lock = QLockFile(os.path.join(QDir.tempPath(), "SemaforoIA.lock"))
    instance_lock.setStaleLockTime(5000)
    if not instance_lock.tryLock(100):
        QMessageBox.information(None, t("Semáforo IA"), t("Semáforo IA ya está abierto."))
        return
    app.setFont(QFont("Segoe UI", 10))
    apply_stylesheet(app)

    i18n.load_saved_language()
    _bootstrap_mlflow_autostart()
    _bootstrap_ollama_autostart()
    app.aboutToQuit.connect(_shutdown_mlflow_autostart)
    app.aboutToQuit.connect(_shutdown_ollama_autostart)

    window = LoginWindow()
    window.show()

    exit_code = app.exec()
    instance_lock.unlock()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

import csv
import json
import math
import os
import sys
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
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
    QApplication,
    QButtonGroup,
    QComboBox,
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QMessageBox,
)

from hardware_info import get_hardware_info


def make_label(text, object_name=None, alignment=Qt.AlignLeft):
    label = QLabel(text)
    if object_name:
        label.setObjectName(object_name)
    label.setAlignment(alignment | Qt.AlignVCenter)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return label


def load_config():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.json")
    data = {
        "default_user": "nacha",
        "users": [
            {
                "username": "nacha",
                "display_name": "Nacha",
                "role": "Administrador",
                "profile_photo": "img/nacha.png",
                "password": "lolman12",
            },
            {
                "username": "maxine",
                "display_name": "Maxine",
                "role": "Usuario",
                "profile_photo": "img/maxine.jpg",
                "password": "123456",
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

    users = []
    raw_users = config.get("users")
    if isinstance(raw_users, list):
        for entry in raw_users:
            if not isinstance(entry, dict):
                continue
            username = entry.get("username", "").strip()
            if not username:
                continue
            users.append(
                {
                    "username": username,
                    "display_name": entry.get("display_name", username).strip() or username,
                    "role": entry.get("role", "Usuario").strip() or "Usuario",
                    "profile_photo": entry.get("profile_photo", "").strip(),
                    "password": entry.get("password", ""),
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

    default_user = str(config.get("default_user", "")).strip()
    if default_user:
        data["default_user"] = default_user

    return data


def load_csv_rows(filename):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base_dir, "data", filename)
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


def get_default_user(config):
    default_user = config.get("default_user", "")
    profile = find_user_profile(config, default_user)
    if profile:
        return profile
    users = config.get("users", [])
    return users[0] if users else {"display_name": "Usuario", "role": "", "profile_photo": ""}


def resolve_path(relative_path):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_dir, relative_path))




def make_round_pixmap(image_path, size):
    pixmap = QPixmap(image_path)
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
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(14)

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
        progress.setFixedHeight(12)
        progress.setStyleSheet(
            "QProgressBar {"
            "  border: none;"
            "  background: #2a2a2a;"
            "  border-radius: 6px;"
            "}"
            "QProgressBar::chunk {"
            f"  background-color: {progress_color};"
            "  border-radius: 6px;"
            "}"
        )

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
        value_label.setWordWrap(True)
        layout.addWidget(value_label)


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
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

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
            layout.setContentsMargins(18, 14, 18, 14)
            layout.setSpacing(14)

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
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        layout.addWidget(make_label(title, "infoCardTitle"))
        self.value_label = make_label(value, "infoCardValue")
        layout.addWidget(self.value_label)

    def set_value(self, value):
        self.value_label.setText(value)


class ListPanel(QFrame):
    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self.setObjectName("listPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        layout.addWidget(make_label(title, "listTitle"))
        layout.addSpacing(4)

        for index, item in enumerate(items):
            item_label = make_label(item, "listItem")
            item_label.setWordWrap(True)
            layout.addWidget(item_label)
            if index < len(items) - 1:
                layout.addWidget(make_separator("listLine"))


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
        title="Registro de Actividad",
        title_alignment=Qt.AlignLeft,
        object_name="activityPanel",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

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


class HomeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        header_icon = QLabel()
        header_icon.setPixmap(make_leaf_pixmap(22))
        header_icon.setFixedSize(QSize(22, 22))

        header_title = make_label("SEMÁFORO IA", "pageTitle")

        header_layout.addWidget(header_icon)
        header_layout.addWidget(header_title, 1)

        layout.addLayout(header_layout)
        layout.addWidget(make_separator("separator"))

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(18)

        self.status_cards = {
            "alto": StatusCard(
                "#b60f0f",
                make_warning_icon(22),
                "Huella de Carbono Alta",
                "Tu nivel de Huella de Carbono es alto. Se recomienda revisar el consumo energético y la configuración de hardware.",
                level="alto",
                large=True,
            ),
            "moderado": StatusCard(
                "#c4a600",
                make_exclamation_icon(22),
                "Huella de Carbono Moderada",
                "Tu nivel de Huella de Carbono es estándar. Se mantiene estable, pero existen oportunidades de mejora.",
                level="moderado",
                large=True,
            ),
            "bajo": StatusCard(
                "#4eb541",
                make_thumb_icon(22),
                "Huella de Carbono Baja",
                "Tu nivel de Huella de Carbono es bajo y se mantiene con muy poco uso adicional.",
                level="bajo",
                large=True,
            ),
        }

        for key in ("alto", "moderado", "bajo"):
            cards_layout.addWidget(self.status_cards[key], 1)

        info_bar = InfoBar(
            "¿Cómo se calcula?",
            "Se estima con energía, hardware, tiempo de proceso y región/proveedor.",
            compact=True,
        )
        info_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        info_bar.setMaximumHeight(68)

        layout.addLayout(cards_layout, 1)
        layout.addWidget(info_bar)

    def set_semaforo_level(self, level, score=None):
        for key, card in self.status_cards.items():
            card.set_selected(level == key)
            if level == key and score is not None:
                # Dynamic green score and tips
                green_score = max(0.0, 100.0 - (score / 5.0))

                # Check language dynamically
                lang = getattr(self.window(), "current_lang", "es")

                if lang == "es":
                    base_desc = "Tu nivel de Huella de Carbono es bajo."
                    if level == "alto": base_desc = "Nivel ALTO."
                    elif level == "moderado": base_desc = "Nivel MODERADO."

                    tip = ""
                    if green_score < 50: tip = "\n💡 Consejo para mejorar tu Green Score: Mueve tus cargas a una región con menor intensidad o usa hardware con menor TDP."
                    elif green_score < 80: tip = "\n💡 Consejo: Optimiza la duración de tus procesos para acercarte a un Green Score de 100."
                    else: tip = "\n✨ ¡Excelente Green Score! Tu configuración es altamente eficiente."

                    full_text = f"Impacto de Carbono: {score:.1f} | Green Score: {green_score:.1f}/100.\n{base_desc}{tip}"
                else:
                    base_desc = "Your Carbon Footprint is low."
                    if level == "alto": base_desc = "HIGH Level."
                    elif level == "moderado": base_desc = "MODERATE Level."

                    tip = ""
                    if green_score < 50: tip = "\n💡 Tip to improve Green Score: Move workloads to a lower-intensity region or use lower TDP hardware."
                    elif green_score < 80: tip = "\n💡 Tip: Optimize process duration to get closer to a 100 Green Score."
                    else: tip = "\n✨ Excellent Green Score! Highly efficient config."

                    full_text = f"Carbon Impact: {score:.1f} | Green Score: {green_score:.1f}/100.\n{base_desc}{tip}"

                card.update_description(full_text)


class EnvironmentalPerformanceView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(22)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        header_icon = QLabel()
        header_icon.setPixmap(make_leaf_pixmap(20))
        header_icon.setFixedSize(QSize(20, 20))

        header_title = make_label("Panel de Rendimiento Ambiental", "pageTitle")

        header_layout.addWidget(header_icon)
        header_layout.addWidget(header_title, 1)

        emissions_layout = QHBoxLayout()
        emissions_layout.setSpacing(18)
        emissions_layout.addWidget(PerformanceCard("Emisiones entrenamiento", "98 gCO2eq"), 1)
        emissions_layout.addWidget(PerformanceCard("Emisiones ejecución", "44 gCO2eq"), 1)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(18)
        metrics_layout.addWidget(PerformanceCard("Consumo Energético", "3.8 kWh"), 1)
        metrics_layout.addWidget(PerformanceCard("Tiempo de Procesamiento", "00:47:00 mins"), 1)

        details_rows = [
            ("Hardware", "NVIDIA A100"),
            ("Proveedor Nube", "AWS US-East-1"),
            ("Factor de Emisión", "0.386 kg/kWh"),
            ("Región", "Norteamérica"),
            ("Última ejecución", "Hace 2 minutos"),
            ("Estado del cálculo", "Finalizado"),
        ]
        details_panel = DetailsPanel("Detalles del Cálculo", details_rows)

        activity_items = [
            "Cálculo Ambiental finalizado correctamente.",
            "Métricas gCO2eq y kWh actualizadas en interfaz.",
            "Variables aún no inicializadas -- mostrando aviso de cálculo en curso",
            "Sesión iniciada. Hardware detectado.",
            "Excepción 1: datos no disponibles al iniciar.",
        ]
        activity_panel = ActivityPanel(activity_items, title_alignment=Qt.AlignLeft)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(18)
        bottom_row.addWidget(details_panel, 1)
        bottom_row.addWidget(activity_panel, 1)

        main_layout.addLayout(header_layout)
        main_layout.addWidget(make_separator("separator"))
        main_layout.addLayout(emissions_layout)
        main_layout.addLayout(metrics_layout)
        main_layout.addLayout(bottom_row)


class CarbonDetailView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label("Comparativas", "pageTitle"))
        layout.addWidget(make_separator("separator"))

        panel = QFrame()
        panel.setObjectName("detailModal")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(32, 28, 32, 28)
        panel_layout.setSpacing(14)

        icon = QLabel()
        icon.setPixmap(make_warning_icon(36))
        icon.setFixedSize(36, 36)

        title = make_label("Huella de Carbono Moderada", "modalTitle", alignment=Qt.AlignCenter)
        body = make_label(
            "Tu nivel de huella de carbono se encuentra en un rango de advertencia. "
            "Si bien el sistema opera dentro de márgenes aceptables, se han detectado "
            "parámetros que incrementan innecesariamente las emisiones de CO2 y el consumo energético. "
            "Es recomendable tomar acción antes de que el nivel escale a rango crítico.",
            "modalBody",
        )
        body.setWordWrap(True)

        bullet_1 = QLabel(
            "• <b>Región de ejecución:</b> Migrar las cargas de trabajo a regiones con menor factor de emisión, "
            "como Europa del Norte o Canada Central, puede reducir significativamente las emisiones sin afectar "
            "el rendimiento."
        )
        bullet_2 = QLabel(
            "• <b>Tiempo de procesamiento:</b> Optimizar los hiperparámetros del modelo o aplicar técnicas de early "
            "stopping puede disminuir el tiempo de cómputo y, con ello, el consumo energético asociado."
        )
        bullet_3 = QLabel(
            "• <b>Hardware:</b> Considerar el uso de aceleradores más eficientes energéticamente o ajustar la asignación "
            "de recursos para evitar capacidad ociosa durante la ejecución."
        )
        for bullet in (bullet_1, bullet_2, bullet_3):
            bullet.setObjectName("modalBullet")
            bullet.setWordWrap(True)
            bullet.setTextFormat(Qt.RichText)

        footer = make_label(
            "Implementar al menos una de estas medidas debería ser suficiente para retornar al rango verde en la próxima evaluación.",
            "modalBody",
        )
        footer.setWordWrap(True)

        button = QPushButton("Continuar")
        button.setObjectName("primaryButton")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedWidth(160)

        panel_layout.addWidget(icon, 0, Qt.AlignHCenter)
        panel_layout.addWidget(title)
        panel_layout.addWidget(body)
        panel_layout.addWidget(bullet_1)
        panel_layout.addWidget(bullet_2)
        panel_layout.addWidget(bullet_3)
        panel_layout.addWidget(footer)
        panel_layout.addWidget(button, 0, Qt.AlignHCenter)

        layout.addWidget(panel, 1)


class ModelsView(QWidget):
    def __init__(self, on_selection=None, parent=None):
        super().__init__(parent)
        self.on_selection = on_selection

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label("Modelos", "pageTitle"))
        layout.addWidget(make_separator("separator"))

        self.models_data = load_csv_rows("modelos_ia.csv")

        cards = QHBoxLayout()
        cards.setSpacing(18)
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
            cards.addWidget(InfoCard("Modelos disponibles", str(model_total)), 1)
            cards.addWidget(InfoCard("Dominios", str(domain_total)), 1)
            cards.addWidget(InfoCard("Empresas", str(maker_total)), 1)
        else:
            cards.addWidget(InfoCard("Modelos activos", "14"), 1)
            cards.addWidget(InfoCard("Latencia media", "128 ms"), 1)
            cards.addWidget(InfoCard("Precisión promedio", "92%"), 1)

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
        list_panel = ListPanel("Modelos recientes", items)

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

        selector_layout.addWidget(self._build_selector("Modelo", self.model_combo), 1)

        self.model_combo.currentTextChanged.connect(self._handle_model_change)
        if self.model_combo.count():
            self._handle_model_change(self.model_combo.currentText())

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

    def _handle_model_change(self, model_name):
        if not self.on_selection:
            return
        row = self.model_map.get(model_name, {})
        energy = parse_number(row.get("Consumo_Energetico_Base"))
        self.on_selection(model=model_name, model_energy=energy)


class FinOpsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label("Costos FinOps", "pageTitle"))
        layout.addWidget(make_separator("separator"))

        cards = QHBoxLayout()
        cards.setSpacing(18)
        cards.addWidget(InfoCard("Costo actual", "$4.820.000"), 1)
        cards.addWidget(InfoCard("Presupuesto mensual", "$7.500.000"), 1)
        cards.addWidget(InfoCard("Ahorro estimado", "$1.120.000"), 1)

        items = [
            "GPU compute — 48% del gasto",
            "Storage + snapshots — 22% del gasto",
            "Networking — 14% del gasto",
            "Servicios administrados — 16% del gasto",
        ]
        list_panel = ListPanel("Desglose por servicio", items)

        layout.addLayout(cards)
        layout.addWidget(list_panel)


class CloudView(QWidget):
    def __init__(self, on_selection=None, parent=None):
        super().__init__(parent)
        self.on_selection = on_selection

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label("Cloud", "pageTitle"))
        layout.addWidget(make_separator("separator"))

        self.provider_card = InfoCard("Proveedor", "AWS")
        self.region_card = InfoCard("Región activa", "US-East-1")
        self.status_card = InfoCard("Estado", "Operativo")

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
        self.tier_combo.addItems(["Básico", "Profesional", "Enterprise"])
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

        selector_layout.addWidget(self._build_selector("Proveedor", self.provider_combo), 1)
        selector_layout.addWidget(self._build_selector("Tier", self.tier_combo), 1)
        selector_layout.addWidget(self._build_selector("Región", self.region_combo), 1)

        self.provider_combo.currentTextChanged.connect(self._update_regions)
        self.region_combo.currentTextChanged.connect(self._sync_cards)
        self._update_regions(self.provider_combo.currentText())

        items = [
            "GPU Instances: 6 activas",
            "Storage: 82 TB en uso",
            "Networking: 1.2 TB transferidos",
            "Backups: Última copia hace 3 horas",
        ]
        list_panel = ListPanel("Servicios activos", items)

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

        layout.addWidget(make_label("Historial", "pageTitle"))
        layout.addWidget(make_separator("separator"))

        items = [
            "Hace 3 min — Evaluación ambiental completada (GPU A100)",
            "Hace 1 h — Reporte de costos generado (FinOps)",
            "Hace 4 h — Validación de modelo Llama 3 70B",
            "Ayer — Rebalanceo de cargas a Europa del Norte",
        ]
        list_panel = ListPanel("Últimas ejecuciones", items)

        layout.addWidget(list_panel)


class SettingsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label("Ajustes", "pageTitle"))
        layout.addWidget(make_separator("separator"))

        items = [
            "Notificaciones: activas",
            "Modo de reporte: semanal",
            "Unidad de energía: kWh",
            "Idioma: Español",
        ]
        list_panel = ListPanel("Preferencias generales", items)

        layout.addWidget(list_panel)


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
            info_layout.addWidget(make_label(f"Usuario: {username}", "accountMeta"))

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label("Cuenta", "pageTitle"))
        layout.addWidget(make_separator("separator"))
        layout.addWidget(AccountHeaderCard(user_profile))

        top_row = QHBoxLayout()
        top_row.setSpacing(18)

        top_row.addWidget(
            MenuSection(
                "Perfil",
                [
                    ("Editar perfil", "menuButton", None),
                    ("Actualizar foto", "menuButton", None),
                    ("Datos personales", "menuButton", None),
                ],
            ),
            1,
        )
        top_row.addWidget(
            MenuSection(
                "Preferencias",
                [
                    ("Notificaciones", "menuButton", None),
                    ("Idioma y zona horaria", "menuButton", None),
                    ("Accesibilidad", "menuButton", None),
                ],
            ),
            1,
        )

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(18)
        bottom_row.addWidget(
            MenuSection(
                "Seguridad",
                [
                    ("Cambiar contrasena", "menuButton", None),
                    ("Dispositivos vinculados", "menuButton", None),
                    ("Verificacion en dos pasos", "menuButton", None),
                ],
            ),
            1,
        )
        bottom_row.addWidget(
            MenuSection(
                "Sesion",
                [
                    ("Cerrar sesion en otros equipos", "menuButton", None),
                    ("Salir de la cuenta", "logoutButton", on_logout),
                ],
            ),
            1,
        )

        layout.addLayout(top_row)
        layout.addLayout(bottom_row)


class AdminMenuView(QWidget):
    def __init__(self, user_profile, on_logout=None, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(make_label("Administracion", "pageTitle"))
        layout.addWidget(make_separator("separator"))
        layout.addWidget(AccountHeaderCard(user_profile))

        top_row = QHBoxLayout()
        top_row.setSpacing(18)
        top_row.addWidget(
            MenuSection(
                "Usuarios",
                [
                    ("Crear usuario", "menuButton", None),
                    ("Resetear contrasena", "menuButton", None),
                    ("Desactivar usuario", "menuButton", None),
                    ("Editar roles", "menuButton", None),
                ],
            ),
            1,
        )
        top_row.addWidget(
            MenuSection(
                "Permisos",
                [
                    ("Roles y permisos", "menuButton", None),
                    ("Grupos", "menuButton", None),
                    ("Accesos temporales", "menuButton", None),
                ],
            ),
            1,
        )

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(18)
        bottom_row.addWidget(
            MenuSection(
                "Auditoria",
                [
                    ("Registro de actividad", "menuButton", None),
                    ("Alertas", "menuButton", None),
                    ("Exportar reporte", "menuButton", self.export_html_report),
                ],
            ),
            1,
        )
        bottom_row.addWidget(
            MenuSection(
                "Sistema",
                [
                    ("Backup y restauracion", "menuButton", None),
                    ("Integraciones", "menuButton", None),
                    ("Parametros globales", "menuButton", None),
                    ("Salir de la cuenta", "logoutButton", on_logout),
                ],
            ),
            1,
        )

        layout.addLayout(top_row)
        layout.addLayout(bottom_row)

    def export_html_report(self):
        score = "N/A"
        gs = "N/A"
        if hasattr(self, 'main_window') and self.main_window and hasattr(self.main_window, 'current_score') and self.main_window.current_score is not None:
            score = f"{self.main_window.current_score:.2f}"
            gs = f"{max(0.0, 100.0 - (self.main_window.current_score / 5.0)):.1f}"

        import export_handler
        export_handler.generate_and_save_report(self, score, gs)


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


class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.setWindowTitle("Semáforo IA - Login")
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

        brand_title = make_label("SEMÁFORO\nIA", "loginBrand", alignment=Qt.AlignCenter)

        left_layout.addStretch()
        left_layout.addWidget(brand_icon, 0, Qt.AlignHCenter)
        left_layout.addWidget(brand_title, 0, Qt.AlignHCenter)
        left_layout.addStretch()

        right_panel = QFrame()
        right_panel.setObjectName("loginPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(48, 48, 48, 48)
        right_layout.setSpacing(16)

        right_layout.addWidget(make_label("Login", "loginCaption"))
        right_layout.addWidget(make_label("Bienvenido de Vuelta", "loginTitle"))
        right_layout.addSpacing(8)

        right_layout.addWidget(make_label("Usuario", "loginLabel"))
        self.username_input = QLineEdit()
        self.username_input.setObjectName("loginInput")
        self.username_input.setPlaceholderText("Ingrese un usuario")
        self.username_input.setFixedHeight(40)

        right_layout.addWidget(self.username_input)

        right_layout.addWidget(make_label("Contraseña", "loginLabel"))
        self.password_input = QLineEdit()
        self.password_input.setObjectName("loginInput")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("••••••••")
        self.password_input.setFixedHeight(40)

        right_layout.addWidget(self.password_input)

        self.error_label = make_label("", "loginError")
        self.error_label.setVisible(False)
        right_layout.addWidget(self.error_label)

        login_button = QPushButton("Continuar")
        login_button.setObjectName("loginButton")
        login_button.setCursor(Qt.PointingHandCursor)
        login_button.setFixedWidth(140)
        login_button.clicked.connect(self.handle_login)

        right_layout.addWidget(login_button, 0, Qt.AlignLeft)
        right_layout.addSpacing(10)

        users_label = make_label("Usuarios disponibles", "loginHint")
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
        username = self.username_input.text().strip()
        if not username:
            self._set_error("Ingresa un usuario válido.")
            return

        profile = find_user_profile(self.config, username)
        if not profile:
            self._set_error("Usuario no encontrado. Usa nacha o maxine.")
            return

        password = self.password_input.text()
        expected = str(profile.get("password", ""))
        if expected and password != expected:
            self._set_error("Contraseña incorrecta.")
            return

        self.error_label.setVisible(False)
        self.dashboard = DashboardWindow(profile)
        self.dashboard.show()
        self.close()

    def _set_error(self, message):
        self.error_label.setText(message)
        self.error_label.setVisible(True)


class CatalogRow(QFrame):
    def __init__(self, component, comp_type, vcpus, ram, tdp, on_assign=None, payload=None, parent=None):
        super().__init__(parent)
        self.setObjectName("catalogRow")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)

        layout.addWidget(make_label(component, "catalogCell"), 3)
        layout.addWidget(make_label(comp_type, "catalogCell", alignment=Qt.AlignCenter), 1)
        layout.addWidget(make_label(vcpus, "catalogCell", alignment=Qt.AlignCenter), 1)
        layout.addWidget(make_label(ram, "catalogCell", alignment=Qt.AlignCenter), 1)
        layout.addWidget(make_label(tdp, "catalogCell", alignment=Qt.AlignCenter), 1)

        assign_button = QPushButton("Asignar")
        assign_button.setObjectName("assignButton")
        assign_button.setFixedHeight(32)
        assign_button.setCursor(Qt.PointingHandCursor)
        if on_assign:
            assign_button.clicked.connect(lambda checked=False: on_assign(payload))
        layout.addWidget(assign_button, 1, alignment=Qt.AlignRight)


class HardwareCatalogView(QWidget):
    def __init__(self, on_assign=None, parent=None):
        super().__init__(parent)
        self.on_assign = on_assign

        self._hardware_loaded = False
        self.hardware_rows = load_csv_rows("hardware.csv")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        title = make_label("Catálogo de Hardware", "pageTitle")

        placeholder = "Detectando..."
        hardware_rows = [
            ("CPU", placeholder),
            ("GPU", placeholder),
            ("RAM", placeholder),
            ("Sistema", placeholder),
        ]
        self.hardware_panel = DetailsPanel("Hardware detectado", hardware_rows)
        self.hardware_panel.setObjectName("hardwarePanel")

        catalog_panel = QFrame()
        catalog_panel.setObjectName("catalogPanel")
        panel_layout = QVBoxLayout(catalog_panel)
        panel_layout.setContentsMargins(20, 20, 20, 20)
        panel_layout.setSpacing(16)

        search_row = QHBoxLayout()
        search_row.setSpacing(16)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Buscar componente...")
        self.search_input.setFixedHeight(42)

        self.filter_combo = ChevronComboBox()
        self.filter_combo.setObjectName("filterCombo")
        self.filter_combo.addItems(["TDP máx: todos", "TDP máx: 125W", "TDP máx: 225W", "TDP máx: 400W"])
        self.filter_combo.setFixedHeight(42)
        self.filter_combo.setMinimumWidth(220)

        search_row.addWidget(self.search_input, 3)
        search_row.addWidget(self.filter_combo, 1)

        header = QFrame()
        header.setObjectName("catalogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 10, 18, 10)
        header_layout.setSpacing(10)

        header_layout.addWidget(make_label("Componente", "catalogHeaderLabel"), 3)
        header_layout.addWidget(make_label("Tipo", "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label("TFLOPS", "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label("VRAM", "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label("TDP", "catalogHeaderLabel", alignment=Qt.AlignCenter), 1)
        header_layout.addWidget(make_label("", "catalogHeaderLabel"), 1)

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)

        self.rows_scroll = QScrollArea()
        self.rows_scroll.setObjectName("catalogScroll")
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QFrame.NoFrame)
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rows_scroll.setWidget(self.rows_container)

        panel_layout.addLayout(search_row)
        panel_layout.addWidget(header)
        panel_layout.addWidget(self.rows_scroll)

        layout.addWidget(title)
        layout.addWidget(make_separator("separator"))
        layout.addWidget(self.hardware_panel)
        layout.addWidget(catalog_panel)

        self.search_input.textChanged.connect(self._apply_hardware_filters)
        self.filter_combo.currentTextChanged.connect(self._apply_hardware_filters)
        self._apply_hardware_filters()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._hardware_loaded:
            self._hardware_loaded = True
            QTimer.singleShot(50, self._load_hardware)

    def _load_hardware(self):
        info = get_hardware_info()
        values = [
            info.get("cpu", "No detectado"),
            info.get("gpu", "No detectado"),
            info.get("ram", "No detectado"),
            info.get("os", "No detectado"),
        ]
        self.hardware_panel.set_values(values)

    def _apply_hardware_filters(self):
        rows = list(self.hardware_rows or [])
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

        self._render_hardware_rows(filtered)

    def _render_hardware_rows(self, rows):
        self._clear_layout(self.rows_layout)
        if not rows:
            self.rows_layout.addWidget(CatalogRow("Sin resultados", "--", "--", "--", "--"))
            return

        for row in rows:
            component = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip()
            comp_type = row.get("Categoria", "--") or "--"
            tflops = row.get("FP16_FP32_TFLOPS", "--") or "--"
            vram = row.get("VRAM_GB", "--") or "--"
            tdp = row.get("TDP_Max_Watts", "--") or "--"
            if tdp != "--" and not str(tdp).strip().lower().endswith("w"):
                tdp = f"{tdp}W"
            if not component:
                component = "Hardware"
            self.rows_layout.addWidget(
                CatalogRow(
                    component,
                    comp_type,
                    tflops,
                    vram,
                    tdp,
                    on_assign=self._handle_assign,
                    payload=row,
                )
            )

    def _parse_tdp_filter(self, text):
        if not text:
            return None
        if "todos" in text.lower():
            return None
        return parse_number(text)

    def _handle_assign(self, row):
        if not self.on_assign or not row:
            return
        name = f"{row.get('Fabricante', '').strip()} {row.get('Modelo', '').strip()}".strip()
        tdp_value = parse_number(row.get("TDP_Max_Watts", ""))
        self.on_assign(hardware=name, hardware_tdp=tdp_value)

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
        layout.addWidget(make_label("Vista en construcción", "placeholderText"))


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

        self.brand_title = make_label("SEMÁFORO IA", "brandTitle")

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
        self.nav_buttons.append((button, text))
        self._apply_nav_button_state(button, text)
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
        if photo_path:
            resolved = resolve_path(photo_path)
            avatar_pixmap = make_round_pixmap(resolved, 42)

        avatar_expanded = QLabel()
        avatar_compact = QLabel()
        if avatar_pixmap:
            avatar_expanded.setObjectName("userAvatar")
            avatar_expanded.setPixmap(avatar_pixmap)
            avatar_compact.setObjectName("userAvatar")
            avatar_compact.setPixmap(avatar_pixmap)
        else:
            initial = user_name[:1].upper() if user_name else "?"
            avatar_expanded.setText(initial)
            avatar_expanded.setObjectName("userInitial")
            avatar_expanded.setAlignment(Qt.AlignCenter)
            avatar_compact.setText(initial)
            avatar_compact.setObjectName("userInitial")
            avatar_compact.setAlignment(Qt.AlignCenter)

        avatar_expanded.setFixedSize(42, 42)
        avatar_compact.setFixedSize(42, 42)

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
        compact_trigger_layout = QVBoxLayout(self.user_compact_trigger)
        compact_trigger_layout.setContentsMargins(0, 0, 0, 0)
        compact_trigger_layout.setSpacing(0)
        avatar_compact.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        compact_trigger_layout.addWidget(avatar_compact, 0, Qt.AlignHCenter)

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
        compact_layout = QVBoxLayout(self.user_card_compact)
        compact_layout.setContentsMargins(0, 0, 0, 0)
        compact_layout.setSpacing(6)
        compact_layout.addWidget(self.user_compact_trigger, 0, Qt.AlignHCenter)

        self.user_card_compact.setVisible(False)

        card_layout.addWidget(self.user_card_expanded)
        card_layout.addWidget(self.user_card_compact)

        return card

    def _build_account_menu(self):
        menu = QMenu()
        menu.setObjectName("accountMenu")

        def add_header(text):
            action = menu.addAction(text)
            action.setEnabled(False)
            return action

        def add_action(text, handler=None):
            action = menu.addAction(text)
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

        self.lang_action = menu.addAction("Idioma y zona horaria")

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
        width = self.collapsed_width if self.is_collapsed else self.expanded_width
        self.setFixedWidth(width)
        self.brand_icon.setVisible(not self.is_collapsed)
        self.brand_title.setVisible(not self.is_collapsed)
        self.user_card_expanded.setVisible(not self.is_collapsed)
        self.user_card_compact.setVisible(self.is_collapsed)

        if self.is_collapsed:
            self.user_compact_trigger.setToolTip("Cuenta")
            self.user_info.setToolTip("")
        else:
            self.user_compact_trigger.setToolTip("")
            self.user_info.setToolTip("Cuenta")

        for button, label in self.nav_buttons:
            self._apply_nav_button_state(button, label)

    def _apply_nav_button_state(self, button, label):
        if self.is_collapsed:
            button.setText("")
            button.setToolTip(label)
        else:
            button.setText(label)
            button.setToolTip("")

        button.setProperty("collapsed", self.is_collapsed)
        button.style().unpolish(button)
        button.style().polish(button)


class DashboardWindow(QMainWindow):
    def __init__(self, user_profile=None):
        super().__init__()

        self.setWindowTitle("Semáforo IA")
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
        self.stack = QStackedWidget()

        content_frame = QFrame()
        content_frame.setObjectName("contentFrame")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(28, 24, 28, 24)
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
        self.current_lang = "es"

        self.translations = {
            "Inicio": "Home",
            "Modelos": "Models",
            "Impacto Ambiental": "Environmental Impact",
            "Costos FinOps": "FinOps Costs",
            "Comparativas": "Comparisons",
            "Hardware": "Hardware",
            "Cloud": "Cloud",
            "Historial": "History",
            "Ajustes": "Settings",
            "Administracion": "Administration",
            "SEMÁFORO IA": "AI TRAFFIC LIGHT",
            "Huella de Carbono Alta": "High Carbon Footprint",
            "Huella de Carbono Moderada": "Moderate Carbon Footprint",
            "Huella de Carbono Baja": "Low Carbon Footprint",
            "Panel de Rendimiento Ambiental": "Environmental Performance Panel",
            "Emisiones (gCO2eq)": "Emissions (gCO2eq)",
            "Consumo (kWh)": "Consumption (kWh)",
            "Detalle de Componentes": "Component Details",
            "Presupuesto": "Budget",
            "Costo Actual": "Current Cost",
            "Ahorro": "Savings",
            "Catálogo de Hardware": "Hardware Catalog",
            "Asignar Componente": "Assign Component",
            "Configuración de Región Cloud": "Cloud Region Configuration",
            "Proveedor": "Provider",
            "Región": "Region",
            "TDP / Eficiencia": "TDP / Efficiency",
            "Exportar reporte": "Export Report",
            "Usuarios": "Users",
            "Sistema": "System",
            "Soporte y documentación": "Support & Docs",
            "Sesion": "Session",
            "Alertas": "Alerts",
            "Auditoria": "Audit",
            "Idioma y zona horaria": "Language & Timezone"
        }
        self.reverse_translations = {v: k for k, v in self.translations.items()}

        self.home_view = HomeView()
        self.models_view = ModelsView(on_selection=self._handle_model_selection)
        self.hardware_view = HardwareCatalogView(on_assign=self._handle_hardware_assign)
        self.cloud_view = CloudView(on_selection=self._handle_cloud_selection)

        sidebar.lang_action.triggered.connect(self._toggle_language)
        self.header_title = self.home_view.findChild(QLabel, "pageTitle")

        self._add_nav_item(sidebar, "Inicio", make_home_icon(), self.home_view)
        self._add_nav_item(sidebar, "Modelos", make_grid_icon(), self.models_view)
        self._add_nav_item(
            sidebar,
            "Impacto Ambiental",
            make_leaf_pixmap(18, "#66bb22"),
            EnvironmentalPerformanceView(),
        )
        self._add_nav_item(
            sidebar,
            "Costos FinOps",
            make_text_icon("$", 18, "#66bb22"),
            FinOpsView(),
        )
        self._add_nav_item(sidebar, "Comparativas", make_bars_icon(), CarbonDetailView())
        self._add_nav_item(sidebar, "Hardware", make_chip_icon(), self.hardware_view)
        self._add_nav_item(sidebar, "Cloud", make_cloud_icon(), self.cloud_view)
        self._add_nav_item(sidebar, "Historial", make_clock_icon(), HistoryView())
        self._add_nav_item(sidebar, "Ajustes", make_gear_icon(), SettingsView())

        self._add_nav_item(
            sidebar,
            "Administracion",
            make_gear_icon(),
            AdminMenuView(user_profile, on_logout=self._handle_logout, main_window=self),
        )

        sidebar.button_group.buttons()[0].setChecked(True)
        self.stack.setCurrentIndex(0)

    def _add_nav_item(self, sidebar, label, icon, widget):
        button = sidebar.add_nav_button(label, icon)
        index = self.stack.addWidget(widget)
        button.clicked.connect(lambda checked=False, idx=index: self.stack.setCurrentIndex(idx))
        return button

    def _handle_logout(self):
        self.login_window = LoginWindow()
        self.login_window.show()
        self.close()

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

    def _toggle_language(self):
        self.current_lang = "en" if self.current_lang == "es" else "es"

        from PySide6.QtWidgets import QLabel, QPushButton

        for widget in self.findChildren(QLabel) + self.findChildren(QPushButton):
            if hasattr(widget, "text"):
                current_text = widget.text()
                if self.current_lang == "en" and current_text in self.translations:
                    widget.setText(self.translations[current_text])
                elif self.current_lang == "es" and current_text in self.reverse_translations:
                    widget.setText(self.reverse_translations[current_text])

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
            return
        if intensity is None or tdp is None:
            self.home_view.set_semaforo_level(None, None)
            self.current_score = None
            return

        model_factor = 1.0
        if model_energy is not None:
            model_factor += math.log10(model_energy + 1.0)

        score = intensity * (tdp / 1000.0) * model_factor
        self.current_score = score
        if score >= 350:
            level = "alto"
        elif score >= 150:
            level = "moderado"
        else:
            level = "bajo"
        self.home_view.set_semaforo_level(level, score)


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
        "QScrollArea#catalogScroll {"
        "  background: transparent;"
        "  border: none;"
        "}"
        "QScrollArea#catalogScroll QWidget {"
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
    )


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    apply_stylesheet(app)

    window = LoginWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

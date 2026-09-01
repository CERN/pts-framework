# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap


def _load_package_pixmap(resource_parts: tuple[str, ...]) -> QPixmap | None:
    try:
        resource = files("pypts")
        for part in resource_parts:
            resource = resource / part
        with resource.open("rb") as handle:
            pixmap = QPixmap()
            if pixmap.loadFromData(handle.read()):
                return pixmap
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        return None
    return None


def _load_filesystem_pixmap(candidates: list[Path]) -> QPixmap | None:
    for candidate in candidates:
        if candidate.is_file():
            pixmap = QPixmap(str(candidate))
            if not pixmap.isNull():
                return pixmap
    return None


def load_cern_logo_pixmap() -> QPixmap | None:
    pixmap = _load_package_pixmap(("images", "CERN_Logo.png"))
    if pixmap is not None:
        return pixmap

    repo_root = Path(__file__).resolve().parents[3]
    return _load_filesystem_pixmap(
        [
            repo_root / "src" / "pypts" / "images" / "CERN_Logo.png",
            repo_root / "images" / "CERN_Logo.png",
        ]
    )


def load_app_logo_pixmap() -> QPixmap | None:
    for name in ("logo.png", "YamVIEW.png", "YamVIEW_cookie.png"):
        pixmap = _load_package_pixmap(("images", name))
        if pixmap is not None:
            return pixmap

    repo_root = Path(__file__).resolve().parents[3]
    return _load_filesystem_pixmap(
        [
            repo_root / "src" / "pypts" / "images" / "logo.png",
            repo_root / "src" / "pypts" / "images" / "YamVIEW.png",
            repo_root / "src" / "pypts" / "images" / "YamVIEW_cookie.png",
        ]
    )


def make_placeholder_pixmap(width: int, height: int, text: str = "pypts") -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#eef3fb"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    border_pen = QPen(QColor("#c7d4ea"))
    border_pen.setWidth(2)
    painter.setPen(border_pen)
    painter.drawRoundedRect(8, 8, max(width - 16, 1), max(height - 16, 1), 12, 12)

    painter.setPen(QColor("#5f7898"))
    font = painter.font()
    font.setPointSize(max(12, min(width, height) // 10))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()

    return pixmap

# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from pypts.hmi.gui.palette import (
    PLACEHOLDER_BORDER,
    PLACEHOLDER_FILL,
    PLACEHOLDER_TEXT,
)


def _load_package_pixmap(resource_parts: tuple[str, ...]) -> QPixmap | None:
    try:
        resource = files("pypts.hmi.gui")
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


def tint_pixmap(pixmap: QPixmap, color: str) -> QPixmap:
    """
    The same artwork in one flat colour, keeping its shape.

    `SourceIn` paints the colour only where the image is already opaque, so the
    logo's transparent background stays transparent and its outline keeps every
    edge. The CERN logo is a single-colour line drawing, so flattening it loses
    nothing - on a dark theme it is the difference between a visible mark and a
    navy smudge on charcoal.
    """
    tinted = QPixmap(pixmap.size())
    tinted.fill(Qt.GlobalColor.transparent)

    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    return tinted


def load_cern_logo_pixmap(tint: str | None = None) -> QPixmap | None:
    """
    The CERN logo, optionally recoloured.

    Args:
        tint: a colour to flatten the artwork to - `Palette.logo_tint`, which is
            None in the light theme, where the file is already the right blue.
    """
    pixmap = _load_package_pixmap(("images", "CERN_Logo.png"))
    if pixmap is None:
        # parents[2] = pypts/, parents[1] = hmi/, parents[0] = gui/
        gui_dir = Path(__file__).resolve().parent
        pixmap = _load_filesystem_pixmap([gui_dir / "images" / "CERN_Logo.png"])

    if pixmap is None or tint is None:
        return pixmap
    return tint_pixmap(pixmap, tint)


def load_app_logo_pixmap() -> QPixmap | None:
    for name in ("logo.png", "YamVIEW.png", "YamVIEW_cookie.png"):
        pixmap = _load_package_pixmap(("images", name))
        if pixmap is not None:
            return pixmap

    gui_dir = Path(__file__).resolve().parent
    return _load_filesystem_pixmap(
        [
            gui_dir / "images" / "logo.png",
            gui_dir / "images" / "YamVIEW.png",
            gui_dir / "images" / "YamVIEW_cookie.png",
        ]
    )


def make_placeholder_pixmap(width: int, height: int, text: str = "pypts") -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(PLACEHOLDER_FILL))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    border_pen = QPen(QColor(PLACEHOLDER_BORDER))
    border_pen.setWidth(2)
    painter.setPen(border_pen)
    painter.drawRoundedRect(8, 8, max(width - 16, 1), max(height - 16, 1), 12, 12)

    painter.setPen(QColor(PLACEHOLDER_TEXT))
    font = painter.font()
    font.setPointSize(max(12, min(width, height) // 10))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()

    return pixmap

"""
Genera assets/iliad.ico, usato dai collegamenti di Windows.

    python -m install.make_icon
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parent.parent / "assets" / "iliad.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setBrush(QColor("#7AA2F7"))
    qp.setPen(Qt.NoPen)
    m = max(1, size // 16)
    qp.drawEllipse(m, m, size - 2 * m, size - 2 * m)
    qp.setPen(QColor("#FFFFFF"))
    f = QFont("Segoe UI")
    f.setPointSizeF(size * 0.44)
    f.setWeight(QFont.Bold)
    qp.setFont(f)
    qp.drawText(pm.rect(), Qt.AlignCenter, "i")
    qp.end()
    return pm


def png_bytes(pm: QPixmap) -> bytes:
    # il QByteArray deve sopravvivere al QBuffer, altrimenti Qt va in crash
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def main() -> int:
    app = QApplication(sys.argv)          # serve per disegnare, resta vivo fin qui
    OUT.parent.mkdir(parents=True, exist_ok=True)

    blobs = [png_bytes(draw(s)) for s in SIZES]

    # ICO con PNG incorporati: accettato da Windows Vista in poi
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, data = b"", b""
    for size, blob in zip(SIZES, blobs):
        dim = 0 if size >= 256 else size   # 0 significa 256 nel formato ICO
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(blob), offset)
        data += blob
        offset += len(blob)

    OUT.write_bytes(header + entries + data)
    print(f"{OUT} ({OUT.stat().st_size} byte, {len(SIZES)} risoluzioni)")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

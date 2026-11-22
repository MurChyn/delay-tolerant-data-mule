#!/usr/bin/env python3
"""Generate the mule wiring diagram as PNG and SVG with matplotlib."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))

FIG, AX = plt.subplots(figsize=(12, 7))
AX.set_xlim(0, 12)
AX.set_ylim(0, 7)
AX.axis("off")
FIG.patch.set_facecolor("#0c121c")
AX.set_facecolor("#0c121c")


def box(x, y, w, h, title, lines, edge="#41a6e8"):
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle="round,pad=0.06,rounding_size=0.12",
                       linewidth=2, edgecolor=edge, facecolor="#162030")
    AX.add_patch(p)
    AX.text(x + w / 2, y + h - 0.28, title, color="#f1c40f",
            fontsize=12, fontweight="bold", ha="center", va="center")
    for i, line in enumerate(lines):
        AX.text(x + w / 2, y + h - 0.72 - i * 0.34, line,
                color="#c8d2de", fontsize=9, ha="center", va="center")


def wire(p1, p2, label="", color="#2ecc71"):
    AX.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-", linewidth=1.8,
                                 color=color, shrinkA=0, shrinkB=0))
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        AX.text(mx, my + 0.10, label, color="#95a5a6", fontsize=8,
                ha="center", va="bottom",
                bbox=dict(facecolor="#0c121c", edgecolor="none", pad=0.6))


box(4.4, 2.3, 3.2, 2.4, "ESP32 MULE",
    ["Soft-AP  CH6", "UDP :5005", "SPI flash / LittleFS", "4096 x 128 B records"],
    edge="#f1c40f")
box(0.4, 4.5, 2.6, 1.5, "DS3231 RTC",
    ["SDA -> GPIO21", "SCL -> GPIO22", "VCC 3V3 / GND"])
box(0.4, 1.4, 2.6, 1.5, "NEO-6M GPS",
    ["TX -> GPIO16", "RX -> GPIO17", "VCC 5V / GND"])
box(9.0, 4.5, 2.6, 1.5, "SSD1306 OLED",
    ["SDA GPIO21", "SCL GPIO22", "I2C 0x3C"])
box(9.0, 2.4, 2.6, 1.5, "microSD (opt.)",
    ["CS GPIO5", "MOSI 23 / MISO 19", "SCK GPIO18"])
box(4.5, 0.25, 3.0, 1.2, "POWER",
    ["18650 -> TP4056", "AMS1117-3.3 -> 3V3"], edge="#e67e22")
box(0.5, 0.25, 2.3, 1.0, "STATUS LED",
    ["GPIO2 -> 330R -> GND"], edge="#e74c3c")

wire((3.0, 5.2), (4.4, 4.2), "I2C")
wire((3.0, 2.1), (4.4, 3.1), "UART")
wire((7.6, 5.2), (9.0, 5.2), "I2C")
wire((7.6, 3.3), (9.0, 3.2), "SPI")
wire((6.0, 2.3), (6.0, 1.45), "3V3")
wire((4.4, 2.8), (2.8, 0.75), "GPIO2")
wire((11.65, 1.2), (11.0, 0.9), "GPS fix", color="#f39c12")

AX.text(6.0, 6.7, "DELAY-TOLERANT DATA MULE — WIRING SCHEMATIC",
        color="#ecf0f1", fontsize=16, fontweight="bold", ha="center")
AX.text(6.0, 6.3, "ESP32 DevKit V1 · fixed channel 6 · 192.168.4.1",
        color="#95a5a6", fontsize=10, ha="center")

FIG.tight_layout()
FIG.savefig(os.path.join(HERE, "wiring_diagram.png"), dpi=180,
            facecolor=FIG.get_facecolor())
FIG.savefig(os.path.join(HERE, "wiring_diagram.svg"), facecolor=FIG.get_facecolor())
print("wrote wiring_diagram.png and wiring_diagram.svg")

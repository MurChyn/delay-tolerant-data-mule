#!/usr/bin/env python3
"""Generate the project overview infographic and a stylised hardware layout.

These are deliberately rendered diagrams, not photographs. The project had no
physical hardware available; see docs/02_hardware.md and docs/06_analysis.md.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
BG = "#0c121c"
FG = "#ecf0f1"
MUTED = "#95a5a6"
ACCENT = "#2ecc71"
HIGH = "#e74c3c"
LOW = "#3498db"
GOLD = "#f1c40f"


def new_fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.axis("off")
    return fig, ax


def label(ax, x, y, s, size=11, color=FG, weight="normal", ha="center"):
    ax.text(x, y, s, color=color, fontsize=size, fontweight=weight, ha=ha, va="center")


# ---------------------------------------------------------------------------
# System overview
# ---------------------------------------------------------------------------
fig, ax = new_fig(12, 7)
label(ax, 6, 6.65, "DELAY-TOLERANT DATA MULE", 20, GOLD, "bold")
label(ax, 6, 6.28, "Mobile Wi-Fi node · store–carry–forward · priority-aware buffering",
      11, MUTED)

# road
ax.add_patch(Rectangle((0.4, 1.05), 11.2, 2.6, facecolor="#1b2433", edgecolor="#2c3e50"))
for x in [1.0, 3.0, 5.0, 7.0, 9.0, 11.0]:
    ax.add_patch(Rectangle((x, 2.31), 1.0, 0.08, facecolor="#7f8c8d"))

# sensors
for i, (sx, sy) in enumerate([(1.6, 4.35), (4.3, 4.35), (7.2, 4.35), (10.2, 4.35)]):
    ax.add_patch(FancyBboxPatch((sx - 0.42, sy - 0.3), 0.84, 0.6,
                                boxstyle="round,pad=0.04,rounding_size=0.1",
                                facecolor="#162030", edgecolor=LOW, linewidth=2))
    ax.plot([sx, sx], [sy + 0.3, sy + 0.85], color=MUTED, lw=1.5)
    ax.add_patch(Circle((sx, sy + 0.9), 0.09, facecolor=LOW))
    label(ax, sx, sy, f"S{i+1}", 11, FG, "bold")

# car
cx = 5.6
ax.add_patch(FancyBboxPatch((cx - 0.75, 1.9), 1.5, 0.75,
                            boxstyle="round,pad=0.05,rounding_size=0.18",
                            facecolor=GOLD, edgecolor="#f39c12", linewidth=2))
ax.add_patch(FancyBboxPatch((cx - 0.42, 2.55), 0.84, 0.42,
                            boxstyle="round,pad=0.02,rounding_size=0.12",
                            facecolor=GOLD, edgecolor="#f39c12"))
for wx in (cx - 0.5, cx + 0.5):
    ax.add_patch(Circle((wx, 1.92), 0.19, facecolor="#1c1c1c", edgecolor="#555"))

# wifi arcs
for sx in (4.3, 7.2):
    ax.add_patch(FancyArrowPatch((cx, 3.05), (sx, 4.15),
                                 connectionstyle="arc3,rad=-0.35",
                                 arrowstyle="-|>", mutation_scale=12,
                                 linestyle="dashed", linewidth=2, color=ACCENT))
    label(ax, (cx + sx) / 2, 3.85, "2–5 s", 9, ACCENT, "bold")

# pipeline boxes
stages = [
    (0.7, "SENSOR QUEUE", ["SP-EDF", "128 pkt"], LOW),
    (3.6, "LINK", ["UDP / CRC", "32 kbit/s"], ACCENT),
    (6.5, "MULE FLASH", ["PADS + guard", "4096 slots"], GOLD),
    (9.4, "BASE STATION", ["unload", "analysis"], HIGH),
]
for x, title, lines, col in stages:
    ax.add_patch(FancyBboxPatch((x, 0.15), 2.0, 0.72,
                                boxstyle="round,pad=0.05,rounding_size=0.1",
                                facecolor="#162030", edgecolor=col, linewidth=2))
    label(ax, x + 1.0, 0.70, title, 10, col, "bold")
    label(ax, x + 1.0, 0.38, " · ".join(lines), 8, MUTED)
for x in (2.75, 5.65, 8.55):
    ax.add_patch(FancyArrowPatch((x, 0.51), (x + 0.7, 0.51),
                                 arrowstyle="-|>", mutation_scale=12,
                                 linewidth=2, color=FG))

fig.tight_layout()
fig.savefig(os.path.join(HERE, "system_overview.png"), dpi=180, facecolor=BG)
plt.close(fig)


# ---------------------------------------------------------------------------
# Stylised hardware layout
# ---------------------------------------------------------------------------
fig, ax = new_fig(12, 7)
label(ax, 6, 6.6, "MULE HARDWARE LAYOUT (SCHEMATIC RENDER)", 18, GOLD, "bold")
label(ax, 6, 6.22, "Not a photograph — no physical hardware was available", 10, MUTED)

# board
ax.add_patch(FancyBboxPatch((1.0, 0.8), 10.0, 4.9,
                            boxstyle="round,pad=0.08,rounding_size=0.2",
                            facecolor="#123a2a", edgecolor="#27ae60", linewidth=3))
label(ax, 1.6, 5.25, "ESP32 DevKit V1", 13, FG, "bold", ha="left")

modules = [
    (2.0, 3.5, 2.0, 1.1, "DS3231 RTC", "I2C · GPIO21/22", LOW),
    (4.5, 3.5, 2.2, 1.1, "ESP32", "soft-AP · UDP:5005", GOLD),
    (7.2, 3.5, 2.0, 1.1, "microSD", "SPI · 5/18/19/23", ACCENT),
    (9.6, 3.5, 1.1, 1.1, "GPS", "UART 16/17", HIGH),
    (4.0, 1.4, 2.0, 1.0, "AMS1117", "3V3 regulator", "#e67e22"),
    (6.5, 1.4, 2.0, 1.0, "18650", "TP4056 charger", "#e67e22"),
]
for x, y, w, h, title, sub, col in modules:
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.04,rounding_size=0.08",
                                facecolor="#162030", edgecolor=col, linewidth=2))
    label(ax, x + w / 2, y + h * 0.65, title, 11, FG, "bold")
    label(ax, x + w / 2, y + h * 0.30, sub, 8, MUTED)

for x1, x2 in [(4.0, 4.5), (6.7, 7.2), (9.2, 9.6)]:
    ax.add_patch(FancyArrowPatch((x1, 4.05), (x2, 4.05),
                                 arrowstyle="-|>", mutation_scale=10,
                                 linewidth=1.8, color=FG))

label(ax, 6, 0.35, "Status LED on GPIO2 · fixed AP channel 6 · LittleFS store /mule_store.bin",
      9, MUTED)

fig.tight_layout()
fig.savefig(os.path.join(HERE, "hardware_setup.png"), dpi=180, facecolor=BG)
plt.close(fig)

print("wrote system_overview.png and hardware_setup.png")

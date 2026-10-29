from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).with_name("diagrama_flujo.png")

INK = "#1f2933"
STEP = "#e8eef5"
GATE = "#fde9c8"
STOP = "#f8d7d7"
OK = "#d9efdc"

fig, ax = plt.subplots(figsize=(15, 7.2))
ax.set_xlim(0, 15)
ax.set_ylim(0, 7.2)
ax.axis("off")


def box(x, y, w, h, text, fill, bold=False):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=1.2, edgecolor=INK, facecolor=fill,
        )
    )
    ax.text(
        x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9.5,
        color=INK, fontweight="bold" if bold else "normal", wrap=True,
    )


def arrow(x1, y1, x2, y2, color=INK, style="-|>", dashed=False):
    ax.annotate(
        "", xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle=style, color=color, lw=1.4, linestyle="--" if dashed else "-"),
    )


w, h = 2.7, 1.1
top_y, bot_y = 5.2, 2.7

top = [
    ("Fuentes\nmovilidad mensual (hoja Peten)\nmigración (hoja Datos)", STEP, False),
    ("1. Lectura\ny huella digital\nde las fuentes", STEP, False),
    ("2. Controles de calidad\n(6 controles)\nVALIDACIÓN DE DATOS", GATE, True),
    ("3. Preparación\nserie mensual por subdestino\nmigración de visitantes", STEP, False),
]
bottom = [
    ("4. Ajuste\nfactor de reparto\npor subdestino", STEP, False),
    ("5. Evaluación temporal\nMAE frente a referencias\nEVALUACIÓN", GATE, True),
    ("6. Regla de aceptación\nAUTORIZACIÓN\nDE PUBLICACIÓN", GATE, True),
    ("7. Estimación y\npublicación de la\nversión aprobada", OK, False),
]

xs_top = [0.5 + i * 3.6 for i in range(4)]
xs_bot = [0.5 + i * 3.6 for i in range(4)]

for x, (t, f, b) in zip(xs_top, top):
    box(x, top_y, w, h, t, f, b)
for x, (t, f, b) in zip(xs_bot, bottom):
    box(x, bot_y, w, h, t, f, b)

for i in range(3):
    arrow(xs_top[i] + w, top_y + h / 2, xs_top[i + 1], top_y + h / 2)
    arrow(xs_bot[i] + w, bot_y + h / 2, xs_bot[i + 1], bot_y + h / 2)

# prepare (top right) -> fit (bottom left)
ax.plot([xs_top[3] + w / 2, xs_top[3] + w / 2], [top_y, 4.45], color=INK, lw=1.4)
ax.plot([xs_top[3] + w / 2, xs_bot[0] + w / 2], [4.45, 4.45], color=INK, lw=1.4)
arrow(xs_bot[0] + w / 2, 4.45, xs_bot[0] + w / 2, bot_y + h)

# dashboard
box(11.0, 0.5, 3.5, 1.0, "Tablero\nlee solo approved/current\n(estimación vs. observado)", OK)
arrow(xs_bot[3] + w / 2, bot_y, xs_bot[3] + w / 2, 1.5)

# stop branches
box(0.5, 0.5, 4.7, 1.0, "Si falla un control crítico, la evaluación o la regla:\nse conserva la última versión aprobada", STOP)
ax.text(
    xs_top[2] + w / 2, top_y - 0.18, "si falla un control crítico: el flujo se detiene",
    ha="center", va="top", fontsize=8.5, color="#b03a2e", style="italic",
)
ax.annotate(
    "", xy=(2.85, 1.5), xytext=(xs_bot[1] + w / 2, bot_y),
    arrowprops=dict(arrowstyle="-|>", color="#b03a2e", lw=1.2, linestyle="--"),
)
ax.annotate(
    "", xy=(3.6, 1.5), xytext=(xs_bot[2] + w / 2, bot_y),
    arrowprops=dict(arrowstyle="-|>", color="#b03a2e", lw=1.2, linestyle="--"),
)

# tracking bar
box(5.6, 0.5, 4.8, 1.0, "MLflow Tracking y registro por ejecución\n(parámetros, métricas, controles, archivos)", STEP)

ax.text(7.5, 6.85, "Flujo del pipeline: de las fuentes a la consulta de las estimaciones",
        ha="center", fontsize=13, fontweight="bold", color=INK)
ax.text(7.5, 6.5, "Compuertas (naranja): validación de datos, evaluación y autorización de publicación",
        ha="center", fontsize=10, color=INK)

fig.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
print(OUT)

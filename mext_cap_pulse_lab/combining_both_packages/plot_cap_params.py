#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# ===================== CONTROL =====================
<<<<<<< HEAD
RUN_NAME         = "t2"
=======
RUN_NAME         = "Langzeittest_Cap2"
>>>>>>> e8e37277a7d005bfa2a4fc5eccd2c3ce8bd42a14

# Optionen
SMOOTH_OVERLAY   = True     # Glättung (Moving Average) als Overlay zeichnen
SMOOTH_WINDOW    = 5        # Fenstergröße (ungerade Zahl empfohlen)
MARK_OUTLIERS    = True     # Ausreißer (IQR) markieren
SAVE_PNG         = False     # PNGs automatisch speichern
SHOW_TREND       = True     # Lineare Trendlinie + Text (fallend/steigend)
# ===================================================

BASE_DIR = Path(__file__).resolve().parent
RUN_DIR = BASE_DIR / "Runs" / RUN_NAME
PARAMS_CSV_PATH = RUN_DIR / f"{RUN_NAME}.params.csv"

# ---- CSV laden ----
df = pd.read_csv(
    PARAMS_CSV_PATH,
    comment="#",
    header=None,
    names=["pulse_id","t_mid_s","esr_ohm","cap_F","E_J","P_peak_W","P_avg_W","i_col","source"],
)

# Einheiten umrechnen
df["pulse_id"] = pd.to_numeric(df["pulse_id"], errors="coerce")
df["esr_mOhm"] = pd.to_numeric(df["esr_ohm"], errors="coerce") * 1e3   # Ω → mΩ
df["cap_uF"]   = pd.to_numeric(df["cap_F"],   errors="coerce") * 1e6   # F → µF

df = df.dropna(subset=["pulse_id","esr_mOhm","cap_uF"]).sort_values("pulse_id").reset_index(drop=True)

def moving_average(y: pd.Series, window: int) -> pd.Series:
    if not SMOOTH_OVERLAY or window is None or window < 2 or len(y) < 3:
        return None
    return y.rolling(window=window, center=True, min_periods=max(1, window//2)).mean()

def iqr_outliers(y: pd.Series) -> np.ndarray:
    if not MARK_OUTLIERS or len(y) < 4:
        return np.array([], dtype=int)
    q1, q3 = y.quantile(0.25), y.quantile(0.75)
    iqr = q3 - q1
    low, high = q1 - 1.5*iqr, q3 + 1.5*iqr
    return np.where((y < low) | (y > high))[0]

def fit_trend(x: np.ndarray, y: np.ndarray):
    if not SHOW_TREND or len(x) < 2:
        return None
    # lineare Regression (LS)
    coeffs = np.polyfit(x, y, 1)  # y = m*x + b
    m, b = coeffs[0], coeffs[1]
    # R^2
    y_hat = m*x + b
    ss_res = np.sum((y - y_hat)**2)
    ss_tot = np.sum((y - np.mean(y))**2) if len(y) > 1 else 0.0
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else np.nan
    return m, b, r2

def plot_series(ax, x, y, ylabel, title, smooth_name):
    # Originalpunkte
    ax.plot(x, y, marker="o", linestyle="-", label="Messwerte")

    # Ausreißer
    idx_out = iqr_outliers(pd.Series(y))
    if idx_out.size > 0:
        ax.scatter(x[idx_out], y[idx_out], marker="x", s=70, label="Ausreißer (IQR)")

    # Glättung
    y_smooth = moving_average(pd.Series(y), SMOOTH_WINDOW)
    if y_smooth is not None:
        ax.plot(x, y_smooth.values, linestyle="--", label=f"Glättung (MA, w={SMOOTH_WINDOW})")

    # Trendlinie + Text
    tr = fit_trend(x, y)
    if tr is not None:
        m, b, r2 = tr
        x_line = np.array([x.min(), x.max()])
        y_line = m*x_line + b
        ax.plot(x_line, y_line, linestyle=":", label=f"Trend (m={m:.3g} / Pulse, R²={r2:.2f})")
        trend_txt = "fallend" if m < 0 else ("steigend" if m > 0 else "neutral")
        ax.text(0.02, 0.95, f"Trend: {trend_txt}", transform=ax.transAxes,
                va="top", ha="left")

    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")

# ======= EIN FENSTER, ZWEI SUBPLOTS =======
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

x = df["pulse_id"].to_numpy(dtype=float)
y_esr = df["esr_mOhm"].to_numpy(dtype=float)
y_cap = df["cap_uF"].to_numpy(dtype=float)

plot_series(ax1, x, y_esr, ylabel="ESR [mΩ]",
            title=f"ESR über Pulsnummer – {RUN_NAME}", smooth_name="esr_mOhm")
plot_series(ax2, x, y_cap, ylabel="Kapazität [µF]",
            title=f"Kapazität über Pulsnummer – {RUN_NAME}", smooth_name="cap_uF")

# Nur ganzzahlige Pulse-IDs
ax2.xaxis.set_major_locator(MaxNLocator(integer=True))
ax2.set_xlabel("Pulse-ID")
plt.tight_layout()

# Optional speichern
if SAVE_PNG:
    out_esr_cap = RUN_DIR / f"{RUN_NAME}_esr_cap_over_pulses.png"
    plt.savefig(out_esr_cap)
    print(f"Gespeichert: {out_esr_cap}")

plt.show()

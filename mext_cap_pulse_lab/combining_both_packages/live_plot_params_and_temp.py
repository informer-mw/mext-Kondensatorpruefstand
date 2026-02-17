import time
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

BASE_DIR = Path(r"C:\Users\mext\Desktop\Messreihen")
RUN_NAME = "TESTLAUF_17022026"

# Für ESR/C wird SHOW_LAST_N praktisch nicht mehr gebraucht (es wird Gesamt-Historie gezeigt),
# kann aber erstmal bleiben. Temperatur bleibt "letzte Stunde" etc.
SHOW_LAST_N = 3000
SHOW_LAST_T = 3600

SMOOTH_OVERLAY = True
SMOOTH_WINDOW = 5
MARK_OUTLIERS = True
SHOW_TREND = True

# GUI / Pause
PAUSE_AFTER_S = 3.0
FAST_PAUSE_S = 0.05
SLOW_PAUSE_S = 0.30

# Downsampling für ESR/C Anzeige:
PLOT_EVERY_N_PULSE = 100   # nur jeder 1000. Puls wird geplottet

RUN_DIR = BASE_DIR / "Runs" / RUN_NAME
PARAMS = RUN_DIR / f"{RUN_NAME}.params.csv"
TEMPS  = RUN_DIR / f"{RUN_NAME}.tc08.csv"


def moving_average(y: pd.Series, window: int):
    if (not SMOOTH_OVERLAY) or window < 2 or len(y) < 3:
        return None
    return y.rolling(window=window, center=True, min_periods=max(1, window//2)).mean()


def iqr_outliers(y: pd.Series) -> np.ndarray:
    if (not MARK_OUTLIERS) or len(y) < 4:
        return np.array([], dtype=int)
    q1, q3 = y.quantile(0.25), y.quantile(0.75)
    iqr = q3 - q1
    low, high = q1 - 1.5*iqr, q3 + 1.5*iqr
    return np.where((y < low) | (y > high))[0]


def fit_trend(x: np.ndarray, y: np.ndarray):
    if (not SHOW_TREND) or len(x) < 2:
        return None
    m, b = np.polyfit(x, y, 1)
    y_hat = m*x + b
    ss_res = np.sum((y - y_hat)**2)
    ss_tot = np.sum((y - np.mean(y))**2) if len(y) > 1 else 0.0
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else np.nan
    return m, b, r2


def load_params_df():
    """
    Lädt die gesamte params.csv (kann zusätzliche Spalten hinten haben),
    nutzt nur die ersten 9 Spalten für ESR/C, und downsampled auf jeden 1000. Puls.
    """
    raw = pd.read_csv(PARAMS, comment="#", header=None)
    if raw.empty:
        return raw

    # nur die ersten 9 Spalten (Rest z.B. Temperaturen ignorieren)
    raw = raw.iloc[:, :9].copy()
    raw.columns = ["pulse_id","t_mid_s","esr_ohm","cap_F","E_J","P_peak_W","P_avg_W","i_col","source"]

    raw["pulse_id"] = pd.to_numeric(raw["pulse_id"], errors="coerce")
    raw["esr_mOhm"] = pd.to_numeric(raw["esr_ohm"], errors="coerce") * 1e3
    raw["cap_uF"]   = pd.to_numeric(raw["cap_F"], errors="coerce") * 1e6

    df = raw.dropna(subset=["pulse_id","esr_mOhm","cap_uF"]).sort_values("pulse_id").reset_index(drop=True)

    # ✅ gesamte Historie, aber nur jeder N-te Puls
    df = df[df["pulse_id"].astype(int) % int(PLOT_EVERY_N_PULSE) == 0].reset_index(drop=True)

    return df


def load_temps_df():
    df = pd.read_csv(TEMPS)
    if df.empty:
        return df
    df["epoch_s"] = pd.to_numeric(df.get("epoch_s"), errors="coerce")
    for ch in range(1, 9):
        col = f"T{ch}_C"
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["epoch_s"]).sort_values("epoch_s").reset_index(drop=True)
    if len(df) > SHOW_LAST_T:
        df = df.iloc[-SHOW_LAST_T:].reset_index(drop=True)
    return df


def plot_series(ax, x, y, ylabel, title):
    ax.clear()
    ax.plot(x, y, marker="o", linestyle="-", label=f"Messwerte (jeder {PLOT_EVERY_N_PULSE}. Puls)")

    idx = iqr_outliers(pd.Series(y))
    if idx.size > 0:
        ax.scatter(x[idx], y[idx], marker="x", s=70, label="Ausreißer (IQR)")

    ys = moving_average(pd.Series(y), SMOOTH_WINDOW)
    if ys is not None:
        ax.plot(x, ys.values, linestyle="--", label=f"Glättung (MA, w={SMOOTH_WINDOW})")

    tr = fit_trend(x, y)
    if tr is not None:
        m, b, r2 = tr
        xl = np.array([x.min(), x.max()])
        yl = m*xl + b
        ax.plot(xl, yl, linestyle=":", label=f"Trend (m={m:.3g}/Pulse, R²={r2:.2f})")
        ax.text(0.02, 0.95, f"Trend: {'fallend' if m<0 else ('steigend' if m>0 else 'neutral')}",
                transform=ax.transAxes, va="top", ha="left")

    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")


def plot_temps(ax, t_rel_s: np.ndarray, dft: pd.DataFrame):
    ax.clear()
    for ch in range(1, 9):
        col = f"T{ch}_C"
        if col in dft.columns:
            ax.plot(t_rel_s, dft[col].to_numpy(float), linestyle="-", label=col)

    ax.set_ylabel("Temperatur [°C]")
    ax.set_title(f"Temperaturen TC-08 – {RUN_NAME}")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", ncols=4)


def main():
    plt.ion()
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 9), sharex=False)

    last_pid = None
    last_temp_epoch = None

    last_update_pulse = time.time()
    last_update_temp  = time.time()

    while True:
        if not plt.fignum_exists(fig.number):
            break

        pulse_updated = False
        temp_updated = False

        # ---- Pulsdaten (downsampled) ----
        if PARAMS.exists():
            try:
                dfp = load_params_df()
                if not dfp.empty:
                    x = dfp["pulse_id"].to_numpy(float)
                    esr = dfp["esr_mOhm"].to_numpy(float)
                    cap = dfp["cap_uF"].to_numpy(float)

                    pid_now = int(x[-1])
                    if last_pid != pid_now:
                        last_pid = pid_now
                        last_update_pulse = time.time()
                        pulse_updated = True

                        plot_series(ax1, x, esr, "ESR [mΩ]", f"ESR über Pulsnummer – {RUN_NAME}")
                        plot_series(ax2, x, cap, "Kapazität [µF]", f"Kapazität über Pulsnummer – {RUN_NAME}")
                        ax2.set_xlabel("Pulse-ID")
            except Exception as e:
                print(f"[WARN] params plot: {e}")

        # ---- Temperaturdaten (letzte SHOW_LAST_T Punkte) ----
        if TEMPS.exists():
            try:
                dft = load_temps_df()
                if not dft.empty:
                    epoch_now = float(dft["epoch_s"].iloc[-1])
                    if last_temp_epoch != epoch_now:
                        last_temp_epoch = epoch_now
                        last_update_temp = time.time()
                        temp_updated = True

                        t0 = float(dft["epoch_s"].iloc[0])
                        t_rel = dft["epoch_s"].to_numpy(float) - t0
                        plot_temps(ax3, t_rel, dft)
                        ax3.set_xlabel("Zeit [s] (relativ)")
            except Exception as e:
                print(f"[WARN] temp plot: {e}")

        # ---- Titel / Status ----
        now = time.time()
        dt_p = now - last_update_pulse
        dt_t = now - last_update_temp

        p_state = "läuft" if dt_p <= PAUSE_AFTER_S else f"PAUSED (keine neuen Pulse seit {dt_p:.1f}s)"
        t_state = "läuft" if dt_t <= PAUSE_AFTER_S else f"PAUSED (keine neuen Temps seit {dt_t:.1f}s)"

        fig.suptitle(
            f"{RUN_NAME}  |  Pulse: {p_state} (Plot: jeder {PLOT_EVERY_N_PULSE}.)  |  Temp: {t_state}"
        )

        fig.canvas.draw_idle()
        plt.pause(FAST_PAUSE_S if (pulse_updated or temp_updated) else SLOW_PAUSE_S)


if __name__ == "__main__":
    main()

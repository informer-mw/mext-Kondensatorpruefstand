import time
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

BASE_DIR = Path(r"C:\Users\mext\Desktop\Messreihen")
RUN_NAME = "TESTLAUF_16022026"
REFRESH_S = 1.0
SHOW_LAST_N = 3000

SMOOTH_OVERLAY = True
SMOOTH_WINDOW = 5
MARK_OUTLIERS = True
SHOW_TREND = True

# --- Neu: Pause-Logik ---
PAUSE_AFTER_S = 3.0          # nach wie vielen Sekunden ohne neuen Puls "PAUSED" angezeigt wird
FAST_PAUSE_S = 0.05          # GUI-Eventloop beim normalen Betrieb
SLOW_PAUSE_S = 0.30          # GUI-Eventloop wenn pausiert / keine neuen Daten

RUN_DIR = BASE_DIR / "Runs" / RUN_NAME
PARAMS = RUN_DIR / f"{RUN_NAME}.params.csv"

COLS = ["pulse_id","t_mid_s","esr_ohm","cap_F","E_J","P_peak_W","P_avg_W","i_col","source"]

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

def load_df():
    df = pd.read_csv(PARAMS, comment="#", header=None, names=COLS)
    df["pulse_id"] = pd.to_numeric(df["pulse_id"], errors="coerce")
    df["esr_mOhm"] = pd.to_numeric(df["esr_ohm"], errors="coerce") * 1e3
    df["cap_uF"]   = pd.to_numeric(df["cap_F"], errors="coerce") * 1e6
    df = df.dropna(subset=["pulse_id","esr_mOhm","cap_uF"]).sort_values("pulse_id").reset_index(drop=True)
    if len(df) > SHOW_LAST_N:
        df = df.iloc[-SHOW_LAST_N:].reset_index(drop=True)
    return df

def plot_series(ax, x, y, ylabel, title):
    ax.clear()
    ax.plot(x, y, marker="o", linestyle="-", label="Messwerte")

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

def main():
    plt.ion()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10.5, 7.2), sharex=True)

    last_pid = None
    last_update_time = time.time()
    paused_state = False

    # Erste Überschrift
    fig.suptitle(f"Live – ESR & Kapazität: {RUN_NAME}")

    while True:
        # Fenster geschlossen? -> sauber beenden
        if not plt.fignum_exists(fig.number):
            break

        if not PARAMS.exists():
            fig.suptitle(f"Live – ESR & Kapazität: {RUN_NAME} (Warte auf params.csv …)")
            fig.canvas.draw_idle()
            plt.pause(SLOW_PAUSE_S)
            continue

        try:
            df = load_df()
            if df.empty:
                fig.suptitle(f"Live – ESR & Kapazität: {RUN_NAME} (keine Daten)")
                fig.canvas.draw_idle()
                plt.pause(SLOW_PAUSE_S)
                continue

            x = df["pulse_id"].to_numpy(float)
            esr = df["esr_mOhm"].to_numpy(float)
            cap = df["cap_uF"].to_numpy(float)

            pid_now = int(x[-1])

            # Nur neu plotten, wenn ein neuer Puls da ist
            if last_pid != pid_now:
                last_pid = pid_now
                last_update_time = time.time()

                plot_series(ax1, x, esr, "ESR [mΩ]", f"ESR über Pulsnummer – {RUN_NAME}")
                plot_series(ax2, x, cap, "Kapazität [µF]", f"Kapazität über Pulsnummer – {RUN_NAME}")
                ax2.set_xlabel("Pulse-ID")

                fig.suptitle(f"Live – ESR & Kapazität: {RUN_NAME} (läuft)  |  last pid: {pid_now}")
                fig.canvas.draw_idle()
                paused_state = False

            # Wenn lange kein Update: PAUSED anzeigen
            dt_no_update = time.time() - last_update_time
            if dt_no_update > PAUSE_AFTER_S:
                if not paused_state:
                    fig.suptitle(f"Live – ESR & Kapazität: {RUN_NAME} (PAUSED: keine neuen Pulse seit {dt_no_update:.1f}s)")
                    fig.canvas.draw_idle()
                    paused_state = True
                plt.pause(SLOW_PAUSE_S)
            else:
                plt.pause(FAST_PAUSE_S)

        except Exception as e:
            print(f"[WARN] {e}")
            plt.pause(SLOW_PAUSE_S)

if __name__ == "__main__":
    main()

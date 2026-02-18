import time
import json
import re
from pathlib import Path
import numpy as np

# ===================== CONFIG =====================
BASE_DIR = Path(r"C:\Users\mext\Desktop\Messreihen")
RUN_NAME = "TESTLAUF_18022026"

POLL_INTERVAL_S = 1.0
FILE_STABLE_AGE_S = 1.5 

# AC-Kopplung / DC-Bias für Energieberechnung:
U_IS_AC_COUPLED = True
U_DC_BIAS_V = 400.0  # anpassen!

KEEP_EVERY_N = 100   # nur jeden 1000. Puls als Rohdaten behalten
DRY_RUN = False        # erst True testen, dann False
# ==================================================

RUN_DIR = BASE_DIR / "Runs" / RUN_NAME
PULSES_DIR = RUN_DIR / "Pulses"
META_PATH = RUN_DIR / f"{RUN_NAME}.meta.json"
PARAMS_CSV = RUN_DIR / f"{RUN_NAME}.params.csv"
TEMPS_CSV = RUN_DIR / f"{RUN_NAME}.tc08.csv" 

# per_pulse Dateien: seit Umstellung bevorzugt .npz (binär, schnell)
# Falls alte Runs mit .csv auswerten, PULSE_EXT wieder auf "csv".
PULSE_EXT = "npz"  # "npz" oder "csv"
PULSE_RE = re.compile(rf"^{re.escape(RUN_NAME)}_pulse-(\d{{10}})\.{PULSE_EXT}$")

# Header fuer pramas.csv:
COL_HEADER = (
    "# columns: pulse_id,t_mid_s,esr_ohm,cap_F,E_J,P_peak_W,P_avg_W,i_col,source,"
    "T1_C,T2_C,T3_C,T4_C,T5_C,T6_C,T7_C,T8_C,temp_epoch_s\n"
)


def read_meta():
    if not META_PATH.exists():
        raise FileNotFoundError(f"Meta fehlt: {META_PATH}")
    return json.loads(META_PATH.read_text(encoding="utf-8"))


def ensure_params_header():
    if not PARAMS_CSV.exists():
        PARAMS_CSV.write_text(COL_HEADER, encoding="utf-8")


def load_processed_ids() -> set[int]:
    if not PARAMS_CSV.exists():
        return set()
    ids = set()
    with PARAMS_CSV.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            try:
                ids.add(int(line.split(",", 1)[0]))
            except Exception:
                pass
    return ids


def list_pulses() -> list[tuple[int, Path]]:
    if not PULSES_DIR.exists():
        return []
    items = []
    for p in PULSES_DIR.iterdir():
        if not p.is_file():
            continue
        m = PULSE_RE.match(p.name)
        if not m:
            continue
        items.append((int(m.group(1)), p))
    items.sort(key=lambda x: x[0])
    return items


def file_is_stable(p: Path, min_age_s: float) -> bool:
    try:
        return (time.time() - p.stat().st_mtime) >= min_age_s
    except FileNotFoundError:
        return False


def detect_i_col_from_header(path: Path) -> str:
    """Legacy-Helfer für alte per_pulse CSVs (nicht mehr Standard)."""
    i_col = "i_V"
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            if "columns:" in line:
                cols = line.split("columns:")[-1].strip()
                parts = [c.strip() for c in cols.split(",")]
                for c in parts:
                    if c.startswith("i_"):
                        return c
    return i_col


def read_pulse_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Legacy: per_pulse CSV: sample_idx,time_s,u_V,i_<unit>"""
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.strip().split(",")
            if len(parts) < 4:
                continue
            t = float(parts[1])
            u = float(parts[2])
            i = float(parts[3])
            rows.append((t, u, i))
    if not rows:
        raise ValueError(f"Keine Daten in {path.name}")
    rows.sort(key=lambda r: r[0])
    data = np.array(rows, dtype=float)
    return data[:, 0], data[:, 1], data[:, 2]


def read_pulse_npz(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, str]:
    """
    per_pulse NPZ (aus acquire_i_u_pulse_npz.py):
      t_s, u_V, i, i_unit
    Rückgabe: (t, u, i_sig, i_unit("A"/"V"), i_col("i_A"/"i_V"))
    """
    d = np.load(path, allow_pickle=False)
    t = d["t_s"].astype(float, copy=False)
    u = d["u_V"].astype(float, copy=False)
    i_sig = d["i"].astype(float, copy=False)

    iu = str(d["i_unit"]) if ("i_unit" in d.files) else "V"
    if iu.startswith("i_"):
        i_col = iu
        i_unit = iu.split("_", 1)[1]
    else:
        i_unit = iu
        i_col = f"i_{i_unit.upper()}"

    i_unit = i_unit.upper()
    if i_unit not in ("A", "V"):
        i_unit = "V"
        i_col = "i_V"

    return t, u, i_sig, i_unit, i_col


def estimate_esr_c_fft(t, u, i):
    t = np.asarray(t, float)
    u = np.asarray(u, complex)
    i = np.asarray(i, complex)

    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError("Zeitvektor nicht monoton")
    fs = 1.0 / np.mean(dt)
    N = t.size

    fU = np.fft.fftshift(np.fft.fft(u))
    fI = np.fft.fftshift(np.fft.fft(i))
    f = np.fft.fftshift(np.fft.fftfreq(N, d=1.0 / fs))
    w = 2.0 * np.pi * f

    pos = np.where(f > 0)[0]
    if pos.size == 0:
        raise ValueError("Keine pos. Frequenzen")
    idx = pos[1:] if pos.size > 1 else pos

    FI = fI[idx]
    W = w[idx]
    A = np.column_stack([FI, (-1j / W) * FI])
    b = fU[idx]
    x, *_ = np.linalg.lstsq(A, b, rcond=None)

    esr = float(np.real(x[0]))
    cap = float(np.real(1.0 / x[1]))
    return esr, cap


def energy_power(t, u, i, *, i_unit, rogowski_v_per_a):
    t = np.asarray(t, float)
    u = np.asarray(u, float)
    i = np.asarray(i, float)

    if i_unit.upper() == "V":
        if not rogowski_v_per_a:
            raise ValueError("rogowski_v_per_a fehlt")
        i = i / float(rogowski_v_per_a)

    # baseline (AC)
    n_pre = max(1, int(len(t) * 0.05))
    u = u - np.median(u[:n_pre])
    i = i - np.median(i[:n_pre])

    if U_IS_AC_COUPLED:
        u = u + float(U_DC_BIAS_V)

    p = u * i
    E = float(np.trapezoid(p, t))
    Ppk = float(np.max(p))
    dur = float(t[-1] - t[0]) if t.size else float("nan")
    Pav = float(E / dur) if dur > 0 else float("nan")
    return E, Ppk, Pav


def read_last_temps():
    """
    Liest die letzte Datenzeile aus RUN_NAME.tc08.csv:
    iso_time,epoch_s,T1_C..T8_C
    Rückgabe: (temps[8], epoch_s)
    """
    if not TEMPS_CSV.exists():
        return [float("nan")] * 8, float("nan")

    try:
        with TEMPS_CSV.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(0, end - 8192))
            tail = f.read().decode("utf-8", errors="ignore").splitlines()

        last = None
        for line in reversed(tail):
            if not line.strip():
                continue
            if line.startswith("iso_time,"):
                continue
            last = line
            break

        if not last:
            return [float("nan")] * 8, float("nan")

        parts = last.split(",")
        epoch = float(parts[1])
        temps = [float(parts[i]) for i in range(2, 10)]  # T1..T8
        return temps, epoch

    except Exception:
        return [float("nan")] * 8, float("nan")


def append_params(pulse_id, t, esr, cap, E, Ppk, Pav, i_col, temps, temp_epoch):
    ensure_params_header()
    t_mid = float(0.5 * (t[0] + t[-1])) if len(t) else float("nan")

    def fmt(x):
        try:
            return f"{float(x):.9e}"
        except Exception:
            return ""

    line = ",".join([
        str(int(pulse_id)),
        fmt(t_mid),
        fmt(esr),
        fmt(cap),
        fmt(E),
        fmt(Ppk),
        fmt(Pav),
        i_col,
        "per_pulse_online",
        *(fmt(x) for x in temps),
        fmt(temp_epoch),
    ]) + "\n"

    with PARAMS_CSV.open("a", encoding="utf-8") as f:
        f.write(line)


def main():
    meta = read_meta()
    rogowski = meta.get("ch_b", {}).get("rogowski_v_per_a", None)

    processed = load_processed_ids()
    print(f"[Start] processed={len(processed)} | KEEP_EVERY_N={KEEP_EVERY_N} | DRY_RUN={DRY_RUN}")

    while True:
        pulses = list_pulses()
        for pid, path in pulses:
            if pid in processed:
                continue
            if not file_is_stable(path, FILE_STABLE_AGE_S):
                continue

            try:
                if PULSE_EXT.lower() == "npz":
                    t, u, i_sig, i_unit, i_col = read_pulse_npz(path)
                else:
                    i_col = detect_i_col_from_header(path)  # i_A oder i_V
                    t, u, i_sig = read_pulse_csv(path)
                    i_unit = ("A" if i_col == "i_A" else "V")

                E, Ppk, Pav = energy_power(
                    t, u, i_sig,
                    i_unit=i_unit,
                    rogowski_v_per_a=rogowski
                )
                esr, cap = estimate_esr_c_fft(t, u, i_sig)

                #Temperaturen dazuholen
                temps, temp_epoch = read_last_temps()

                append_params(pid, t, esr, cap, E, Ppk, Pav, i_col, temps, temp_epoch)
                processed.add(pid)
                print(f"[OK] pid={pid} | ESR={esr:.6g} Ω | C={cap*1e6:.2f} µF | T1={temps[0]:.2f}°C")

                # Löschregel: nur jeden 1000. Rohpuls behalten
                keep_raw = (pid % KEEP_EVERY_N == 0)
                if not keep_raw:
                    if DRY_RUN:
                        print(f"[DRY] would delete {path.name}")
                    else:
                        path.unlink(missing_ok=True)
                        print(f"[DEL] {path.name}")

            except Exception as e:
                print(f"[ERR] pid={pid} | {e}")

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()

"""
Kapazitätsparameter-Berechnung aus Puls-Messdaten.

Dieses Modul berechnet die äquivalenten Schaltkreismodell-Parameter
(ESR: Equivalent Series Resistance, Kapazität) eines Kondensators
aus gemessenen Spannungs- und Strompulsen.

Die Berechnung basiert auf einer FFT-basierten Methode, die ein
lineares Gleichungssystem löst, um die Impedanz-Parameter zu bestimmen.

Erweiterung: optionales ESL-Modell (ESR + C + L_ESL) zum Vergleich.
"""

import os
import json
import numpy as np
from typing import Tuple
import matplotlib.pyplot as plt

# ===================== CONTROL =====================
BASE_DIR     = r"C:\Users\mext\Desktop\Messreihen"
RUN_NAME     = "TESTLAUF_14022026"   # muss zum Messlauf passen (CSV + meta.json)
USE_LAST     = False            # True: neuesten pulse_id verwenden; False: PULSE_ID nutzen
PULSE_ID     = 3               # nur wenn USE_LAST=False
U_DC_BIAS_V  = 400.0         # DC-Bias der Spannung (wenn AC-gekoppelt gemessen)

OVERLAY_IDS  = [1,2,3]       # z.B. [1,2,5] -> zusätzliche Pulse überlagern
SHOW_FFT     = False         # FFT des Hauptpulses
FIG_SIZE     = (13, 8)       # großes Fenster
LINEWIDTH    = 1.1
GRID_ALPHA   = 0.25
# ===================================================

# Pfade
RUN_DIR        = os.path.join(BASE_DIR, "Runs", RUN_NAME)
PER_PULSE_DIR  = os.path.join(RUN_DIR, "Pulses")
PARAMS_CSV_PATH = os.path.join(RUN_DIR, f"{RUN_NAME}.params.csv")
print(RUN_DIR)
CSV_PATH       = os.path.join(RUN_DIR, f"{RUN_NAME}.csv")
META_PATH      = os.path.join(RUN_DIR, f"{RUN_NAME}.meta.json")


# --------- Helpers ---------
def _combined_exists() -> bool:
    return os.path.isfile(CSV_PATH)

def _per_pulse_exists() -> bool:
    return os.path.isdir(PER_PULSE_DIR) and any(
        fn.startswith(RUN_NAME + "_pulse-") and fn.endswith(".csv")
        for fn in os.listdir(PER_PULSE_DIR)
    )

def _params_header():
    # kompakt, aber alles Wichtige für Zeitverlauf drin
    return (
        "# columns: pulse_id,t_mid_s,esr_ohm,cap_F,E_J,P_peak_W,P_avg_W,i_col,source\n"
    )

def _params_exists_write_header():
    if not os.path.exists(PARAMS_CSV_PATH):
        with open(PARAMS_CSV_PATH, "w", encoding="utf-8") as f:
            f.write(_params_header())

def _source_mode_str() -> str:
    if _combined_exists() and _per_pulse_exists():
        return "both"
    if _combined_exists():
        return "combined"
    if _per_pulse_exists():
        return "per_pulse"
    return "unknown"

def append_params_row(
    *, pulse_id: int, t: np.ndarray, esr: float, cap: float,
    res: dict, i_colname: str, source: str
):
    """
    Hängt eine Zeile an <RUN_NAME>.params.csv an.
    t_mid_s: Mittelpunkt-Zeit des Pulsfensters (relativ zum Puls-CSV)
    """
    _params_exists_write_header()
    # mittlere Pulszeit als einfacher Zeitstempel für Trends
    t_mid = float(0.5*(t[0] + t[-1])) if t.size else float("nan")

    def _num(x):
        # robust: NaNs → leer schreiben (CSV bleibt numerisch)
        try:
            return f"{float(x):.9e}"
        except Exception:
            return ""

    line = ",".join([
        str(int(pulse_id)),
        _num(t_mid),
        _num(esr),
        _num(cap),
        _num(res.get("E_J")),
        _num(res.get("P_peak_W")),
        _num(res.get("P_avg_W")),
        i_colname,
        source
    ]) + "\n"

    with open(PARAMS_CSV_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def list_pulse_ids_auto() -> list[int]:
    """
    Liefert alle verfügbaren pulse_id (aufsteigend), egal ob combined oder per_pulse.
    """
    if _combined_exists():
        ids = set()
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                try:
                    pid = int(line.split(",", 1)[0])
                    ids.add(pid)
                except Exception:
                    pass
        return sorted(ids)
    elif _per_pulse_exists():
        ids = []
        for fn in os.listdir(PER_PULSE_DIR):
            if fn.startswith(RUN_NAME + "_pulse-") and fn.endswith(".csv"):
                try:
                    pid = int(fn.split("-")[-1].split(".")[0])
                    ids.append(pid)
                except Exception:
                    pass
        return sorted(ids)
    else:
        raise FileNotFoundError(f"Weder combined CSV noch {PER_PULSE_DIR} gefunden.")

def detect_i_unit_auto(pulse_id: int | None = None) -> str:
    """
    Ermittelt 'i_A' oder 'i_V' aus Header – Quelle automatisch gewählt.
    Bei per_pulse braucht sie 'pulse_id' (nimmt letzte, wenn None).
    """
    if _combined_exists():
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    break
                if "columns:" in line:
                    parts = [p.strip() for p in line.split("columns:")[-1].split(",")]
                    for p in parts:
                        if p.startswith("i_"):
                            return p  # "i_A" oder "i_V"
        return "i_V"
    elif _per_pulse_exists():
        ids = list_pulse_ids_auto()
        pid = pulse_id if pulse_id is not None else (ids[-1] if ids else None)
        if pid is None:
            raise FileNotFoundError("Keine Pulsdateien gefunden.")
        path = os.path.join(PER_PULSE_DIR, f"{RUN_NAME}_pulse-{pid:010d}.csv")
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    break
                if "columns:" in line:
                    parts = [p.strip() for p in line.split("columns:")[-1].split(",")]
                    for p in parts:
                        if p.startswith("i_"):
                            return p
        return "i_V"
    else:
        raise FileNotFoundError("Keine Datenquelle gefunden.")

def read_pulse_auto(pulse_id: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Liest (t,u,i) für die angegebene pulse_id – Quelle automatisch.
    """
    if _combined_exists():
        rows = []
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line or line[0] == "#":
                    continue
                parts = line.strip().split(",")
                if len(parts) < 5:
                    continue
                try:
                    pid = int(parts[0])
                except Exception:
                    continue
                if pid == pulse_id:
                    t = float(parts[2])
                    u = float(parts[3])
                    i = float(parts[4])
                    rows.append((t, u, i))
        if not rows:
            raise FileNotFoundError(f"Pulse-ID {pulse_id} nicht in {CSV_PATH} gefunden.")
        rows.sort(key=lambda r: r[0])
        data = np.array(rows, dtype=float)
        return data[:,0], data[:,1], data[:,2]

    elif _per_pulse_exists():
        path = os.path.join(PER_PULSE_DIR, f"{RUN_NAME}_pulse-{pulse_id:010d}.csv")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Pulse-Datei fehlt: {path}")
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue
                t = float(parts[1])
                u = float(parts[2])
                i = float(parts[3])
                rows.append((t, u, i))
        if not rows:
            raise ValueError(f"Keine Datenzeilen in {path}.")
        rows.sort(key=lambda r: r[0])
        data = np.array(rows, dtype=float)
        return data[:,0], data[:,1], data[:,2]

    else:
        raise FileNotFoundError("Weder combined CSV noch per-pulse Verzeichnis vorhanden.")

def read_meta():
    if not os.path.isfile(META_PATH):
        raise FileNotFoundError(f"Meta-Datei fehlt: {META_PATH}")
    with open(META_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def detect_i_unit_from_header():
    """Liest Kopfzeilen (# ...) und erkennt die I-Spaltenbezeichnung (i_A oder i_V)."""
    if not os.path.isfile(CSV_PATH):
        raise FileNotFoundError(f"CSV nicht gefunden: {CSV_PATH}")
    i_colname = "i_V"
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            if "columns:" in line:
                cols = line.split("columns:")[-1].strip()
                parts = [p.strip() for p in cols.split(",")]
                for p in parts:
                    if p.startswith("i_"):
                        i_colname = p
                        break
    return i_colname  # "i_A" oder "i_V"


# ======= FFT-basierte Parameter-Schätzung (ohne ESL) =======
def estimate_cap_params(t: np.ndarray, u: np.ndarray, i: np.ndarray) -> Tuple[float, float]:
    """
    Schätzt ESR (Equivalent Series Resistance) und Kapazität aus Puls-Messdaten.

    Einfaches Serien-Ersatzschaltbild: ESR + C
    U(ω) = ESR * I(ω) + (1/jωC) * I(ω)
    """
    # Eingabevalidierung
    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=complex)
    i = np.asarray(i, dtype=complex)

    if len(t) != len(u) or len(t) != len(i):
        raise ValueError("Arrays t, u, i müssen gleiche Länge haben")

    # Zeitvektor prüfen: muss streng monoton steigend sein
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError("Zeitvektor muss streng monoton steigend sein")

    # Abtastfrequenz aus mittlerem Zeitabstand berechnen
    fs = 1.0 / np.mean(dt)
    N = t.size

    # FFT berechnen (shifted für symmetrische Darstellung)
    fU = np.fft.fftshift(np.fft.fft(u))
    fI = np.fft.fftshift(np.fft.fft(i))

    # Frequenzachse generieren (shifted)
    f = np.fft.fftshift(np.fft.fftfreq(N, d=1.0 / fs))
    omega = 2.0 * np.pi * f

    # Nur positive Frequenzen verwenden (DC ausschließen)
    pos_idx = np.where(f > 0)[0]
    if pos_idx.size == 0:
        raise ValueError("Keine positiven Frequenzen gefunden (N zu klein?)")

    # Erste positive Frequenz überspringen
    if pos_idx.size > 1:
        idx = pos_idx[1:]
    else:
        idx = pos_idx

    FI = fI[idx]
    OM = omega[idx]

    # Design-Matrix: A * x = b
    # x = [ESR, 1/C]
    A = np.column_stack([
        FI,
        (-1j / OM) * FI
    ])
    b = fU[idx]

    # Least-Squares-Lösung
    x, *_ = np.linalg.lstsq(A, b, rcond=None)

    esr_ohm = float(np.real(x[0]))
    capacitance_f = float(np.real(1.0 / x[1]))

    return esr_ohm, capacitance_f


# ======= FFT-basierte Parameter-Schätzung (mit ESL) =======
def estimate_cap_params_with_esl(
    t: np.ndarray,
    u: np.ndarray,
    i: np.ndarray
) -> Tuple[float, float, float]:
    """
    Schätzt ESR, Kapazität und ESL aus Puls-Messdaten mittels FFT-basierter Impedanzanalyse.

    Erweitertes Ersatzschaltbild:
        Z(ω) = ESR + jω L_ESL + 1/(jω C)
    """
    # Eingabevalidierung
    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=complex)
    i = np.asarray(i, dtype=complex)

    if len(t) != len(u) or len(t) != len(i):
        raise ValueError("Arrays t, u, i müssen gleiche Länge haben")

    # Zeitvektor prüfen
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError("Zeitvektor muss streng monoton steigend sein")

    # Abtastfrequenz und Anzahl Samples
    fs = 1.0 / np.mean(dt)
    N = t.size

    # FFT berechnen (mit shift)
    fU = np.fft.fftshift(np.fft.fft(u))
    fI = np.fft.fftshift(np.fft.fft(i))

    # Frequenzachse
    f = np.fft.fftshift(np.fft.fftfreq(N, d=1.0 / fs))
    omega = 2.0 * np.pi * f

    # Nur positive Frequenzen
    pos_idx = np.where(f > 0)[0]
    if pos_idx.size == 0:
        raise ValueError("Keine positiven Frequenzen gefunden (N zu klein?)")

    if pos_idx.size > 1:
        idx = pos_idx[1:]
    else:
        idx = pos_idx

    FI = fI[idx]
    OM = omega[idx]

    # Design-Matrix:
    # A(ω) = [ I(ω),  jω I(ω),  (-j/ω) I(ω) ]
    A = np.column_stack([
        FI,
        1j * OM * FI,
        (-1j / OM) * FI
    ])
    b = fU[idx]

    # Least-Squares-Lösung
    x, *_ = np.linalg.lstsq(A, b, rcond=None)

    esr_ohm = float(np.real(x[0]))
    esl_h = float(np.real(x[1]))
    capacitance_f = float(np.real(1.0 / x[2]))

    return esr_ohm, capacitance_f, esl_h


def pulse_energy_and_power(
    t, u, i, *,
    i_unit: str = "A",
    rogowski_per_a: float | None = None,
    u_is_ac_coupled: bool = True,
    u_dc_bias_V: float | None = None,
    baseline_correction: bool = True,
    pre_pct: float = 0.05
) -> dict:
    t = np.asarray(t, float)
    u = np.asarray(u, float)
    i = np.asarray(i, float)

    # Rogowski V -> A
    if i_unit.upper() == "V":
        if not rogowski_per_a:
            raise ValueError("rogowski_v_per_a nötig, wenn i in V vorliegt.")
        i = i / float(rogowski_per_a)

    # Offsets nur auf AC-Signale anwenden (vor DC-Addback)
    if baseline_correction and t.size > 10:
        n_pre = max(1, int(len(t) * pre_pct))
        u = u - np.median(u[:n_pre])
        i = i - np.median(i[:n_pre])

    # AC-Kopplung kompensieren: DC-Bias addieren (z.B. 400 V)
    if u_is_ac_coupled:
        if u_dc_bias_V is None:
            raise ValueError("u_dc_bias_V setzen (z.B. 400.0), wenn u AC-gekoppelt ist.")
        u = u + float(u_dc_bias_V)

    p = u * i
    E = float(np.trapezoid(p, t))
    P_peak = float(np.max(p))
    duration = float(t[-1] - t[0]) if t.size else float("nan")
    P_avg = float(E / duration) if duration > 0 else float("nan")

    return {"p_W": p, "E_J": E, "P_peak_W": P_peak, "P_avg_W": P_avg}


def read_pulse_from_csv(pulse_id, i_colname):
    """
    Liest einen Puls (alle Zeilen mit pulse_id) aus der CSV.
    Gibt (t, u, i) zurück.
    """
    if not os.path.isfile(CSV_PATH):
        raise FileNotFoundError(f"CSV nicht gefunden: {CSV_PATH}")

    rows = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line or line[0] == "#":
                continue
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            try:
                pid = int(parts[0])
            except Exception:
                continue
            if pid == pulse_id:
                t = float(parts[2])
                u = float(parts[3])
                i = float(parts[4])
                rows.append((t, u, i))

    if not rows:
        raise FileNotFoundError(f"Pulse-ID {pulse_id} nicht in CSV gefunden.")

    rows.sort(key=lambda r: r[0])
    data = np.array(rows, dtype=float)
    t = data[:, 0]
    u = data[:, 1]
    i = data[:, 2]
    return t, u, i


if __name__ == "__main__":
    # Arrays für Vergleich beider Modelle
    esr_simple_arr = []
    c_simple_arr   = []
    esr_esl_arr    = []
    c_esl_arr      = []
    l_esl_arr      = []

    meta = read_meta()
    print(f"Metadaten geladen: {meta}")

    # verfügbare IDs feststellen
    available_ids = list_pulse_ids_auto()
    print(f"Verfügbare pulse_id: {available_ids}")

    # I-Spalte erkennen (bei per_pulse ggf. letzte Datei genutzt)
    i_colname = detect_i_unit_auto(available_ids[-1] if available_ids else None)
    print(f"Erkannte I-Spalte: {i_colname}")

    # Ziel-IDs bestimmen
    if USE_LAST:
        ids_to_analyze = [available_ids[-1]]
    elif OVERLAY_IDS:
        ids_to_analyze = [pid for pid in OVERLAY_IDS if pid in available_ids]
    else:
        ids_to_analyze = [PULSE_ID] if PULSE_ID in available_ids else []

    if not ids_to_analyze:
        raise ValueError("Keine gültigen pulse_id für die Auswertung gefunden.")

    for pulse_id in ids_to_analyze:
        print(f"\n--- Analysiere Pulse-ID: {pulse_id} ---")

        i_colname = detect_i_unit_auto(pulse_id)
        t, u, i_sig = read_pulse_auto(pulse_id)
        print(f"Pulsdaten geladen: {len(t)} Samples")

        rogowski_scale = meta.get("ch_b", {}).get("rogowski_v_per_a", None)
        print(f"Rogowski-Skala: {rogowski_scale} V/A")

        res = pulse_energy_and_power(
            t, u, i_sig,
            i_unit="A" if i_colname == "i_A" else "V",
            rogowski_per_a=rogowski_scale,
            u_is_ac_coupled=True,
            u_dc_bias_V=U_DC_BIAS_V,
            baseline_correction=True,
            pre_pct=0.05
        )

        # --- Parameter-Fits ---
        esr_simple, c_simple = estimate_cap_params(t, u, i_sig)
        esr_esl, c_esl, l_esl = estimate_cap_params_with_esl(t, u, i_sig)

        # in Arrays sammeln
        esr_simple_arr.append(esr_simple)
        c_simple_arr.append(c_simple)
        esr_esl_arr.append(esr_esl)
        c_esl_arr.append(c_esl)
        l_esl_arr.append(l_esl)

        # relative Abweichungen (in %)
        d_esr_pct = 100.0 * (esr_esl - esr_simple) / esr_simple if esr_simple != 0 else np.nan
        d_c_pct   = 100.0 * (c_esl   - c_simple) / c_simple   if c_simple   != 0 else np.nan

        print(f"    ESR (ohne ESL): {esr_simple:.6f} Ω")
        print(f"    ESR (mit  ESL): {esr_esl:.6f} Ω   (Δ = {d_esr_pct:+.2f} %)")
        print(f"    C   (ohne ESL): {c_simple*1e6:.3f} µF")
        print(f"    C   (mit  ESL): {c_esl*1e6:.3f} µF (Δ = {d_c_pct:+.2f} %)")
        print(f"    L_ESL (fit):    {l_esl*1e9:.2f} nH")

        print(f"    Energie: {res['E_J']:.3f} J | "
              f"P_peak: {res['P_peak_W']:.1f} W | "
              f"P_avg: {res['P_avg_W']:.1f} W")

        # CSV-Logging: weiterhin das einfache Modell (ohne ESL),
        # damit bestehende Auswerteskripte unverändert laufen.
        append_params_row(
            pulse_id=pulse_id,
            t=t,
            esr=esr_simple,
            cap=c_simple,
            res=res,
            i_colname=i_colname,
            source=_source_mode_str()
        )

    # === Zusammenfassung ===
    print("\n=== Zusammenfassung (Mittelwerte) ===")
    mean_esr_simple = np.mean(esr_simple_arr)
    mean_esr_esl    = np.mean(esr_esl_arr)
    mean_c_simple   = np.mean(c_simple_arr)
    mean_c_esl      = np.mean(c_esl_arr)
    mean_l_esl      = np.mean(l_esl_arr)

    print(f"ESR ohne ESL: {mean_esr_simple:.6f} Ω")
    print(f"ESR mit  ESL: {mean_esr_esl:.6f} Ω")
    print(f"C   ohne ESL: {mean_c_simple*1e6:.3f} µF")
    print(f"C   mit  ESL: {mean_c_esl*1e6:.3f} µF")
    print(f"L_ESL (mit ESL): {mean_l_esl*1e9:.2f} nH")

    # globale Abweichungen
    mean_d_esr = 100.0 * (mean_esr_esl - mean_esr_simple) / mean_esr_simple if mean_esr_simple != 0 else np.nan
    mean_d_c   = 100.0 * (mean_c_esl   - mean_c_simple)   / mean_c_simple   if mean_c_simple   != 0 else np.nan

    print(f"Durchschnittliche Abweichung ESR: {mean_d_esr:+.2f} %")
    print(f"Durchschnittliche Abweichung C:   {mean_d_c:+.2f} %")

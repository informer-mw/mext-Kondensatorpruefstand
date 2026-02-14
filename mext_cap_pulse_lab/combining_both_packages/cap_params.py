"""
Kapazitätsparameter-Berechnung aus Puls-Messdaten.

Dieses Modul berechnet die äquivalenten Schaltkreismodell-Parameter
(ESR: Equivalent Series Resistance, Kapazität) eines Kondensators
aus gemessenen Spannungs- und Strompulsen.

Die Berechnung basiert auf einer FFT-basierten Methode, die ein
lineares Gleichungssystem löst, um die Impedanz-Parameter zu bestimmen.
"""

import numpy as np
from typing import Tuple

import os
import json
import numpy as np
import matplotlib.pyplot as plt

# ===================== CONTROL =====================
BASE_DIR     = r"C:\Users\mext\Desktop\Messreihen"
RUN_NAME     = "TESTLAUF_14022026"   # muss zum Messlauf passen (CSV + meta.json)
USE_LAST     = False            # True: neuesten pulse_id verwenden; False: PULSE_ID nutzen
PULSE_ID     = 3               # nur wenn USE_LAST=False
U_DC_BIAS_V  = 100.0         # DC-Bias der Spannung (wenn AC-gekoppelt gemessen)

OVERLAY_IDS  = list(range(1,500))              # z.B. [1,2,5] -> zusätzliche Pulse überlagern
SHOW_FFT     = False           # FFT des Hauptpulses
FIG_SIZE     = (13, 8)         # großes Fenster
LINEWIDTH    = 1.1
GRID_ALPHA   = 0.25
# ===================================================

# Pfade
RUN_DIR   = os.path.join(BASE_DIR, "Runs", RUN_NAME)
PER_PULSE_DIR = os.path.join(RUN_DIR, "Pulses")
PARAMS_CSV_PATH = os.path.join(RUN_DIR, f"{RUN_NAME}.params.csv")
print(RUN_DIR)
CSV_PATH  = os.path.join(RUN_DIR, f"{RUN_NAME}.csv")
META_PATH = os.path.join(RUN_DIR, f"{RUN_NAME}.meta.json")


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
    # robust: NaNs → leer schreiben (CSV bleibt numerisch)
    def _num(x): 
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
        # wie bisher aus der großen CSV
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
                    t = float(parts[2]); u = float(parts[3]); i = float(parts[4])
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
                # sample_idx = int(parts[0])  # optional
                t = float(parts[1]); u = float(parts[2]); i = float(parts[3])
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
                # Beispiel-Zeile: "# columns: pulse_id,sample_idx,time_s,u_V,i_A"
                cols = line.split("columns:")[-1].strip()
                parts = [p.strip() for p in cols.split(",")]
                for p in parts:
                    if p.startswith("i_"):
                        i_colname = p
                        break
    return i_colname  # "i_A" oder "i_V"


def estimate_cap_params(t: np.ndarray, u: np.ndarray, i: np.ndarray) -> Tuple[float, float]:
    """
    Schätzt ESR (Equivalent Series Resistance) und Kapazität aus Puls-Messdaten.
    
    Die Funktion verwendet eine FFT-basierte Analyse, um die Impedanz des
    Kondensators zu bestimmen. Dabei wird ein vereinfachtes Ersatzschaltbild
    angenommen: Serie aus Widerstand (ESR) und Kapazität.
    
    Die Methode löst ein lineares Gleichungssystem im Frequenzbereich:
    U(ω) = ESR * I(ω) + (1/jωC) * I(ω)
    
    Parameters
    ----------
    t : np.ndarray
        Zeitvektor in Sekunden (1D-Array).
        Muss streng monoton steigend sein.
    u : np.ndarray
        Spannungswerte in Volt (1D-Array, gleiche Länge wie t).
        Gemessene Spannung am Kondensator.
    i : np.ndarray
        Stromwerte in Ampere (1D-Array, gleiche Länge wie t).
        Gemessener Strom durch den Kondensator.
        Hinweis: Das Vorzeichen sollte so sein, dass positiver Strom
        eine Entladung darstellt (konsistent mit dem MATLAB-Code).
    
    Returns
    -------
    esr_ohm : float
        Geschätzter Equivalent Series Resistance in Ohm.
        Repräsentiert den Serienwiderstand des Kondensators.
    capacitance_f : float
        Geschätzte Kapazität in Farad.
        Kann in µF oder mF umgerechnet werden (1 µF = 1e-6 F).
    
    Raises
    ------
    ValueError
        Wenn Zeitvektor nicht streng monoton steigend ist,
        oder wenn die Arrays unterschiedliche Längen haben,
        oder wenn keine positiven Frequenzen gefunden werden.
    
    Notes
    -----
    - Die Funktion verwendet Least-Squares-Methode zur Lösung des
      überbestimmten Gleichungssystems im Frequenzbereich.
    - DC-Komponente (f=0) wird ausgeschlossen, da sie keine
      Impedanz-Information liefert.
    - Erste positive Frequenz wird übersprungen (ähnlich MATLAB-Code)
      um numerische Instabilitäten bei sehr kleinen Frequenzen zu vermeiden.
    - Nur positive Frequenzen werden verwendet (einseitiges Spektrum).
    
    Examples
    --------
    >>> import numpy as np
    >>> # Beispiel: Synthetische Daten
    >>> t = np.linspace(0, 1e-3, 1000)  # 1 ms, 1000 Samples
    >>> u = np.exp(-t / 1e-4) * 10  # Exponentieller Abfall
    >>> i = -np.diff(np.pad(u, (0, 1)))  # Vereinfachter Strom
    >>> esr, cap = estimate_cap_params(t, u, i)
    >>> print(f"ESR: {esr:.6f} Ω, C: {cap*1e6:.6f} µF")
    """
    # Eingabevalidierung
    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=complex)  # Komplex erlauben (für FFT)
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
    omega = 2.0 * np.pi * f  # Kreisfrequenz
    
    # Nur positive Frequenzen verwenden (DC ausschließen)
    pos_idx = np.where(f > 0)[0]
    if pos_idx.size == 0:
        raise ValueError("Keine positiven Frequenzen gefunden (N zu klein?)")
    
    # Erste positive Frequenz überspringen (wie im MATLAB-Code)
    # Vermeidet numerische Instabilitäten bei sehr kleinen Omega
    if pos_idx.size > 1:
        idx = pos_idx[1:]  # Ab Index 1
    else:
        idx = pos_idx  # Fallback: nur eine positive Frequenz
    
    # Lineares Gleichungssystem aufbauen: A * x = b
    # U(ω) = ESR * I(ω) + (1/jωC) * I(ω)
    # A = [I(ω), -I(ω)/(jω)]
    # x = [ESR, 1/C]
    # b = U(ω)
    FI = fI[idx]  # Strom-FFT bei ausgewählten Frequenzen
    OM = omega[idx]  # Kreisfrequenzen
    
    # Vermeide Division durch Null (sollte nicht passieren, da f > 0)
    A = np.column_stack([
        FI,  # Spalte 1: Strom-FFT (für ESR)
        (-1j / OM) * FI  # Spalte 2: Strom-FFT / jω (für 1/C)
    ])
    b = fU[idx]  # Spannungs-FFT (Zielvektor)
    
    # Least-Squares-Lösung (überbestimmtes System)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    
    # Parameter extrahieren
    esr_ohm = float(np.real(x[0]))  # Realteil von x[0] ist ESR
    capacitance_f = float(np.real(1.0 / x[1]))  # Realteil von 1/x[1] ist C
    
    return esr_ohm, capacitance_f

from typing import Tuple
import numpy as np

def estimate_cap_params_with_esl(
    t: np.ndarray,
    u: np.ndarray,
    i: np.ndarray
) -> Tuple[float, float, float]:
    """
    Schätzt ESR, Kapazität und ESL aus Puls-Messdaten mittels FFT-basierter Impedanzanalyse.
    
    Erweitertes Ersatzschaltbild:
        Z(ω) = ESR + jω L_ESL + 1/(jω C)
    
    Daraus folgt im Frequenzbereich:
        U(ω) = I(ω) * [ESR + jω L_ESL + 1/(jω C)]
             = ESR * I(ω) + (jω) * L_ESL * I(ω) + (1/(jωC)) * I(ω)
    
    Wir formulieren ein lineares Gleichungssystem:
        U(ω) = A(ω) * x
    
    mit
        A(ω) = [ I(ω),  (jω) I(ω),  (-j/ω) I(ω) ]
        x    = [ ESR,  L_ESL,       1/C        ]^T
    
    und lösen x im Least-Squares-Sinn.
    
    Parameters
    ----------
    t : np.ndarray
        Zeitvektor in Sekunden (1D-Array).
        Muss streng monoton steigend sein.
    u : np.ndarray
        Spannungswerte in Volt (1D-Array, gleiche Länge wie t).
        Gemessene Spannung am Kondensator.
    i : np.ndarray
        Stromwerte in Ampere (1D-Array, gleiche Länge wie t).
        Gemessener Strom durch den Kondensator.
    
    Returns
    -------
    esr_ohm : float
        Geschätzter Equivalent Series Resistance in Ohm.
    capacitance_f : float
        Geschätzte Kapazität in Farad.
    esl_h : float
        Geschätzte Serieninduktivität (ESL) in Henry.
    
    Raises
    ------
    ValueError
        Wenn Zeitvektor nicht streng monoton steigend ist,
        oder wenn die Arrays unterschiedliche Längen haben,
        oder wenn keine positiven Frequenzen gefunden werden.
    """
    # Eingabevalidierung
    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=complex)  # komplex für FFT
    i = np.asarray(i, dtype=complex)
    
    if len(t) != len(u) or len(t) != len(i):
        raise ValueError("Arrays t, u, i müssen gleiche Länge haben")
    
    # Zeitvektor prüfen: muss streng monoton steigend sein
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError("Zeitvektor muss streng monoton steigend sein")
    
    # Abtastfrequenz und Anzahl Samples
    fs = 1.0 / np.mean(dt)
    N = t.size
    
    # FFT berechnen (mit shift für symmetrische Darstellung)
    fU = np.fft.fftshift(np.fft.fft(u))
    fI = np.fft.fftshift(np.fft.fft(i))
    
    # Frequenzachse (shifted)
    f = np.fft.fftshift(np.fft.fftfreq(N, d=1.0 / fs))
    omega = 2.0 * np.pi * f  # Kreisfrequenz
    
    # Nur positive Frequenzen verwenden (DC ausschließen)
    pos_idx = np.where(f > 0)[0]
    if pos_idx.size == 0:
        raise ValueError("Keine positiven Frequenzen gefunden (N zu klein?)")
    
    # Erste positive Frequenz überspringen (vermeidet numerische Probleme)
    if pos_idx.size > 1:
        idx = pos_idx[1:]
    else:
        idx = pos_idx
    
    FI = fI[idx]
    OM = omega[idx]
    
    # Design-Matrix A aufbauen:
    # Spalte 1: I(ω)                 → ESR
    # Spalte 2: jω I(ω)              → L_ESL
    # Spalte 3: (-j/ω) I(ω)          → 1/C
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
    import numpy as np
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

    # Spalten: pulse_id,sample_idx,time_s,u_V,i_{V|A}
    # Wir lesen nur Datenzeilen (skip '#'), dann filtern wir auf pulse_id.
    # Für moderate Dateigrößen ist das okay. Bei >GB CSV später auf chunking umstellen.
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
            except:
                continue
            if pid == pulse_id:
                # sample_idx = int(parts[1])  # würde die Reihenfolge sichern, falls nötig
                t = float(parts[2])
                u = float(parts[3])
                i = float(parts[4])
                rows.append((t, u, i))

    if not rows:
        raise FileNotFoundError(f"Pulse-ID {pulse_id} nicht in CSV gefunden.")

    # nach Zeit sortieren (falls Zeilenreihenfolge nicht sicher)
    rows.sort(key=lambda r: r[0])
    data = np.array(rows, dtype=float)
    t = data[:, 0]
    u = data[:, 1]
    i = data[:, 2]
    return t, u, i

if __name__ == "__main__":
    esr_arr, cap_arr = [], []

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
    elif OVERLAY_IDS:                # deine Liste wie gehabt
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
            i_unit = "A" if i_colname == "i_A" else "V",
            rogowski_per_a = rogowski_scale,
            u_is_ac_coupled = True,
            u_dc_bias_V = U_DC_BIAS_V,
            baseline_correction = True,
            pre_pct = 0.05
        )

        esr, cap = estimate_cap_params(t, u, i_sig)
        esr_simple, c_simple = estimate_cap_params(t, u, i_sig)
        esr_esl, c_esl, l_esl = estimate_cap_params_with_esl(t, u, i_sig)

        esr_arr.append(esr); cap_arr.append(cap)
        print(f"ESR: {esr:.6f} Ω, C: {cap*1e6:.6f} µF")
        print(f"Energie: {res['E_J']:.3f} J | P_peak: {res['P_peak_W']:.1f} W | P_avg: {res['P_avg_W']:.1f} W")
        append_params_row(
            pulse_id=pulse_id,
            t=t,
            esr=esr,
            cap=cap,
            res=res,
            i_colname=i_colname,          # "i_A" oder "i_V"
            source=_source_mode_str()
        )

    print("\n=== Zusammenfassung ===")
    for pid, esr, cap in zip(ids_to_analyze, esr_arr, cap_arr):
        print(f"Pulse-ID {pid}: ESR = {esr:.6f} Ω, Kapazität = {cap*1e6:.6f} µF")
    print(f"Durchschnitt: ESR = {np.mean(esr_arr):.6f} Ω, C = {np.mean(cap_arr)*1e6:.6f} µF")

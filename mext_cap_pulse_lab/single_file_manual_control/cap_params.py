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
BASE_DIR     = r"/Users/peer/Documents/00 - MEXT BA/10 Code/MEXT/picoscope"
RUN_NAME     = "Puls_400V_1200A-BESTE"   # muss zum Messlauf passen (CSV + meta.json)
USE_LAST     = False            # True: neuesten pulse_id verwenden; False: PULSE_ID nutzen
PULSE_ID     = 3               # nur wenn USE_LAST=False

OVERLAY_IDS  = [1,2,3]              # z.B. [1,2,5] -> zusätzliche Pulse überlagern
SHOW_FFT     = False           # FFT des Hauptpulses
FIG_SIZE     = (13, 8)         # großes Fenster
LINEWIDTH    = 1.1
GRID_ALPHA   = 0.25
# ===================================================

# Pfade
RUN_DIR   = os.path.join(BASE_DIR, "Runs", RUN_NAME)
print(RUN_DIR)
CSV_PATH  = os.path.join(RUN_DIR, f"{RUN_NAME}.csv")
META_PATH = os.path.join(RUN_DIR, f"{RUN_NAME}.meta.json")


# --------- Helpers ---------
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




def pulse_energy_and_power(
    t, u, i, *,
    i_unit: str = "A",
    rogovski_v_per_a: float | None = None,
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
        if not rogovski_v_per_a:
            raise ValueError("rogowski_v_per_a nötig, wenn i in V vorliegt.")
        i = i / float(rogovski_v_per_a)

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
    E = float(np.trapz(p, t))
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
    # Metadaten laden

    esr_arr = []
    cap_arr = []

    meta = read_meta()
    print(f"Metadaten geladen: {meta}")

    # I-Spaltenbezeichnung erkennen
    i_colname = detect_i_unit_from_header()
    print(f"Erkannte I-Spalte: {i_colname}")

    # Pulse-ID bestimmen
    if False:
        if USE_LAST:
            # Letzte Pulse-ID aus CSV ermitteln
            last_id = None
            with open(CSV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if not line or line[0] == "#":
                        continue
                    try:
                        pid = int(line.split(",")[0])
                        last_id = pid if (last_id is None or pid > last_id) else last_id
                    except Exception:
                        pass
            if last_id is None:
                raise ValueError("Keine Datenzeilen in CSV gefunden.")
            pulse_id = last_id
        else:
            pulse_id = PULSE_ID
        print(f"Verwendete Pulse-ID: {pulse_id}")

    for i in range(1,10):
        pulse_id = i
        print(f"\n--- Analysiere Pulse-ID: {pulse_id} ---")
        
        # Pulsdaten laden
        t, u, i = read_pulse_from_csv(pulse_id, i_colname)
        print(f"Pulsdaten geladen: {len(t)} Samples")

        rogowski_scale = meta.get("ch_b", {}).get("rogowski_v_per_a", None)
        print(f"Rogowski-Skala: {rogowski_scale} V/A")
        # Energie und Leistung berechnen
        res = pulse_energy_and_power(
            t, u, i,
            i_unit = "A" if i_colname == "i_A" else "V",
            rogovski_v_per_a = rogowski_scale,
            u_is_ac_coupled = True,
            u_dc_bias_V = 400.0,
            baseline_correction = True,
            pre_pct = 0.05
        )

        # Kapazitätsparameter schätzen
        esr, cap = estimate_cap_params(t, u, i)
        esr_arr.append(esr)
        cap_arr.append(cap)
        print(f"Geschätzte Parameter für Pulse-ID {pulse_id}:")
        print(f"  ESR: {esr:.6f} Ω")
        print(f"  Kapazität: {cap*1e6:.6f} µF")
        print(f"Energie  : {res['E_J']:.3f} J")
        print(f"Peak-Leistung : {res['P_peak_W']:.1f} W")
        print(f"Mittlere Leistung im Puls : {res['P_avg_W']:.1f} W")
    
    print("\n=== Zusammenfassung aller Pulse ===")
    for idx, (esr, cap) in enumerate(zip(esr_arr, cap_arr), start=1):
        print(f"Pulse-ID {idx}: ESR = {esr:.6f} Ω, Kapazität = {cap*1e6:.6f} µF")
    avg_esr = np.mean(esr_arr)
    avg_cap = np.mean(cap_arr)
    print(f"\nDurchschnittswerte: ESR = {avg_esr:.6f} Ω, Kapazität = {avg_cap*1e6:.6f} µF")
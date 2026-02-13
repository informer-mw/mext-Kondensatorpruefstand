Beschreibung der Struktur:

combining_both_packages -> beinhaltet alle relevanten Python-Skripte um eine Messreihe zu starten
mext_pulse_lab_control_suite -> beihaltet die Version2 der GUI (Version 1 ist die Datei: Testbench_Control_Windows.exe)
single_file_manual_control -> beinhaltet alle relevanten Python Skripte für Einzelmessungen (wobei dieser Ordner eher unrelevant)

Vorgehen:

1. Vorbereitung

• Picoscope angeschlossen
• Rogowski korrekt montiert
• Spannungstastkopf korrekt angeschlossen
• Massefuehrung sauber
• Zwischenkreisspannung korrekt eingestellt
• Triggerfunktion getestet

2. Messung konfigurieren (acuire_i_u_pulse.py)
   

Wichtige Parameter:

RUN_NAME = "Name_Messreihe"
SAVE_MODE = "per_pulse"
N_PULSES = 10000
ROGOWSKI_V_PER_A =
U_PROBE_ATTENUATION =
TRIG_LEVEL_V =


3. Messung starten

Script starten: acquire_i_u_pulse.py

Waehrend der Messung pruefen:
- Keine Overflow-Meldung
- Spannung und Strom plausibel
- Pulsdateien werden im Runs-Ordner erzeugt

4. Parameter berechnen  (cap_params_2.py)

RUN_NAME korrekt setzen
U_DC_BIAS_V entsprechend der realen Zwischenkreisspannung einstellen
Script starten: cap_params_2.py
Ergebnis: .params.csv mit ESR, C, Energie, Leistung



5. Trendanalyse (plot_cap_params.py)

Script starten: plot_cap_params.py
Anzeige:
- ESR ueber Pulsnummer
- Kapazitaet ueber Pulsnummer
- Trendlinie und Ausreisser



Schnell-Checkliste vor Langzeittest

• RUN_NAME korrekt gesetzt
• SAVE_MODE = per_pulse
• Rogowski-Faktor korrekt
• Tastkopffaktor korrekt
• DC-Bias korrekt eingestellt
• Kein Signal-Clipping (Overflow=0)
• Datensicherung vorbereitet












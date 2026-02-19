import sys
import time
import subprocess
from pathlib import Path

# ====== CONFIG ======
BASE_DIR = Path(r"C:\Users\mext\Desktop\mext-Kondensatorpruefstand\mext_cap_pulse_lab\combining_both_packages")

# Muss identisch sein zu acquire_i_u_pulse.py & online_eval_keep_1000.py & tc08_logger.py & live_plot_params_and_temp.py
RUN_NAME = "TESTLAUF_18022026"
MEAS_BASE_DIR = Path(r"C:\Users\mext\Desktop\Messreihen")

# Welche Skripte starten?
ACQUIRE = BASE_DIR / "acquire_i_u_pulse.py"
EVAL    = BASE_DIR / "online_eval_keep_1000.py"
TC08    = BASE_DIR / "tc08_logger.py"
LIVE    = BASE_DIR / "live_plot_params_and_temp.py"

# Pulse Preview (Spannung+Strom in einem Plot, twin y-axis)
PREVIEW = BASE_DIR / "pulse_preview_plot_twinaxis.py"
START_PREVIEW = True
PREVIEW_EVERY_N = 1000
PREVIEW_POLL_S = 0.5

# Optional: Testbench mit starten
TESTBENCH_EXE = BASE_DIR / "testbench_control_Windows.exe"
START_TESTBENCH = False

# Meta-Wartezeit (damit Evaluierung nicht zu früh startet)
WAIT_META_TIMEOUT_S = 90
# ====================

CREATE_NEW_CONSOLE = 0x00000010

def popen_new_console(cmd, cwd):
    return subprocess.Popen(cmd, creationflags=CREATE_NEW_CONSOLE, cwd=str(cwd))

def wait_for_meta(meta_path: Path, timeout_s: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if meta_path.exists():
            return True
        time.sleep(0.5)
    return False

def main():
    py = sys.executable

    runs_root = MEAS_BASE_DIR / "Runs"
    run_dir = runs_root / RUN_NAME
    meta_path = run_dir / f"{RUN_NAME}.meta.json"

    print("Launcher startet...")

    # Optional Testbench
    if START_TESTBENCH and TESTBENCH_EXE.exists():
        popen_new_console([str(TESTBENCH_EXE)], cwd=BASE_DIR)
        print(" - Testbench gestartet")

    # 1) Acquire zuerst
    popen_new_console([py, str(ACQUIRE)], cwd=BASE_DIR)
    print(" - Acquire gestartet")

    # 2) TC-08 Logger kann parallel starten
    popen_new_console([py, str(TC08)], cwd=BASE_DIR)
    print(" - TC-08 Logger gestartet")

    # 2b) NEW: Preview-Plot parallel starten (unabhängig, beeinflusst Run nicht)
    if START_PREVIEW:
        if PREVIEW.exists():
            popen_new_console([
                py, str(PREVIEW),
                "--runs-root", str(runs_root),
                "--run-name", RUN_NAME,
                "--every", str(PREVIEW_EVERY_N),
                "--poll", str(PREVIEW_POLL_S),
            ], cwd=BASE_DIR)
            print(f" - Preview Plot gestartet (Update alle {PREVIEW_EVERY_N} Pulse)")
        else:
            print(f"WARN: Preview-Skript nicht gefunden: {PREVIEW}")

    # 3) Warten auf meta.json (Acquire legt die an)
    print(f" - Warte auf meta.json: {meta_path}")
    ok = wait_for_meta(meta_path, WAIT_META_TIMEOUT_S)
    if ok:
        print(" - meta.json gefunden -> starte Online Eval")
    else:
        print("WARN: meta.json nicht gefunden (Timeout). Starte Eval trotzdem.")
        print("      (Falls Eval 'Meta fehlt' meldet: einmal Puls auslösen / RUN_NAME prüfen.)")

    # 4) Online Eval + Live Plot
    popen_new_console([py, str(EVAL)], cwd=BASE_DIR)
    print(" - Online Eval gestartet")

    popen_new_console([py, str(LIVE)], cwd=BASE_DIR)
    print(" - Live Plot (ESR/C/Temp) gestartet")

    print("\nFertig. Beenden: Fenster schließen oder Prozesse mit Ctrl+C stoppen.")
    print("Hinweis: RUN_NAME muss in allen Skripten identisch sein!")

if __name__ == "__main__":
    main()

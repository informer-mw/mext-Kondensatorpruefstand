import sys
import time
import subprocess
from pathlib import Path

BASE_DIR = Path(r"C:\Users\mext\Desktop\mext-Kondensatorpruefstand\mext_cap_pulse_lab\combining_both_packages")

ACQUIRE = BASE_DIR / "acquire_i_u_pulse.py"
EVAL    = BASE_DIR / "online_eval_keep_1000.py"
LIVE    = BASE_DIR / "live_plot_params.py"

RUN_NAME = "TESTLAUF_16022026"

RUN_DIR = Path(r"C:\Users\mext\Desktop\Messreihen") / "Runs" / RUN_NAME
META_PATH = RUN_DIR / f"{RUN_NAME}.meta.json"

CREATE_NEW_CONSOLE = 0x00000010

def popen_new_console(cmd, cwd):
    return subprocess.Popen(cmd, creationflags=CREATE_NEW_CONSOLE, cwd=str(cwd))

def wait_for_meta(timeout_s=30):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if META_PATH.exists():
            return True
        time.sleep(0.5)
    return False

def main():
    py = sys.executable
    print("Launcher startet Acquire...")
    popen_new_console([py, str(ACQUIRE)], cwd=BASE_DIR)

    print(f"Warte auf meta.json: {META_PATH}")
    ok = wait_for_meta(timeout_s=60)
    if not ok:
        print("WARN: meta.json nicht gefunden. Bitte einmal Puls auslösen / Acquire prüfen.")
        # Trotzdem starten (falls meta woanders liegt)
    else:
        print("meta.json gefunden -> starte Eval + Live Plot")

    popen_new_console([py, str(EVAL)], cwd=BASE_DIR)
    popen_new_console([py, str(LIVE)], cwd=BASE_DIR)

    print("Fertig. (Testbench wird separat gestartet)")

if __name__ == "__main__":
    main()

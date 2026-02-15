import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(r"C:\Users\mext\Desktop\s\mext-Kondensatorpruefstand\mext_cap_pulse_lab\combining_both_packages")

ACQUIRE = BASE_DIR / "acquire_i_u_pulse.py"
EVAL    = BASE_DIR / "online_eval_keep_1000.py"
LIVE    = BASE_DIR / "live_plot_params.py"

# Optionales starten der Testbench:
TESTBENCH_EXE = BASE_DIR / "testbench_control_Windows.exe" 
START_TESTBENCH = False

def popen_new_console(args):
    # Windows: neues Konsolenfenster
    CREATE_NEW_CONSOLE = 0x00000010
    return subprocess.Popen(args, creationflags=CREATE_NEW_CONSOLE)

def main():
    py = sys.executable

    procs = []

    if START_TESTBENCH and TESTBENCH_EXE.exists():
        procs.append(popen_new_console([str(TESTBENCH_EXE)]))

    procs.append(popen_new_console([py, str(ACQUIRE)]))
    procs.append(popen_new_console([py, str(EVAL)]))
    procs.append(popen_new_console([py, str(LIVE)]))

    print("Launcher gestartet:")
    print(" - Acquire")
    print(" - Online Eval + Keep every 1000 + Delete")
    print(" - Live Plot")
    print("\nBeenden: Fenster schließen oder Prozesse in den Konsolen stoppen.")

if __name__ == "__main__":
    main()

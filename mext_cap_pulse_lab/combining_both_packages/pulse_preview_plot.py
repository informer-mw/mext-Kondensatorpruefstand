#!/usr/bin/env python3
"""
pulse_preview_plot.py

Separater Preview-Plotter von Strom/Spannung eines Pulses:
- Beobachtet einen Puls-Ordner mit per-pulse NPZ Dateien: <RUN_NAME>_pulse-XXXXXXXXXX.npz
- Aktualisiert den Plot beim ersten gefundenen Puls und danach alle N Pulse (Default: 1000)

Beispiele:
  python pulse_preview_plot.py --run-name RUN_20260218_0900
  python pulse_preview_plot.py --pulses-dir "Runs/RUN_20260218_0900/Pulses" --every 1000
  python pulse_preview_plot.py --runs-root Runs --latest --every 1000

Hinweis:
- Erwartet NPZ Keys: t_s, u_V, i, i_unit, pulse_id (wie in acquire_i_u_pulse_npz.py geschrieben)
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt


PULSE_RE = re.compile(r"^(?P<prefix>.+)_pulse-(?P<pid>\d{10})\.npz$")


def find_latest_run_dir(runs_root: Path) -> Path | None:
    if not runs_root.exists():
        return None
    run_dirs = [p for p in runs_root.iterdir() if p.is_dir()]
    if not run_dirs:
        return None
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return run_dirs[0]


def find_latest_pulse_npz(pulses_dir: Path) -> tuple[Path | None, int | None]:
    if not pulses_dir.exists():
        return None, None
    best_path = None
    best_pid = None
    for p in pulses_dir.iterdir():
        if not p.is_file():
            continue
        m = PULSE_RE.match(p.name)
        if not m:
            continue
        pid = int(m.group("pid"))
        if best_pid is None or pid > best_pid:
            best_pid = pid
            best_path = p
    return best_path, best_pid


def load_pulse_npz(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, int]:
    d = np.load(path, allow_pickle=False)
    t = d["t_s"].astype(np.float64, copy=False)
    u = d["u_V"].astype(np.float64, copy=False)
    i = d["i"].astype(np.float64, copy=False)
    i_unit = str(d.get("i_unit", "A"))
    pid = int(d.get("pulse_id", -1))
    if pid < 0:
        m = PULSE_RE.match(path.name)
        if m:
            pid = int(m.group("pid"))
    return t, u, i, i_unit, pid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", type=str, default="Runs", help="Root-Verzeichnis der Runs (Default: Runs)")
    ap.add_argument("--run-name", type=str, default=None, help="Run-Name (Ordner unter runs-root)")
    ap.add_argument("--latest", action="store_true", help="Nimm automatisch den neuesten Run-Ordner unter runs-root")
    ap.add_argument("--pulses-dir", type=str, default=None, help="Direkter Pfad zum Pulses-Ordner (überschreibt runs-root/run-name)")
    ap.add_argument("--every", type=int, default=1000, help="Update alle N Pulse (Default: 1000)")
    ap.add_argument("--poll", type=float, default=0.5, help="Polling-Intervall in Sekunden (Default: 0.5)")
    args = ap.parse_args()

    # Pulses-Ordner bestimmen
    if args.pulses_dir:
        pulses_dir = Path(args.pulses_dir)
        run_label = pulses_dir.parent.name if pulses_dir.parent else str(pulses_dir)
    else:
        runs_root = Path(args.runs_root)
        if args.latest or (args.run_name is None):
            run_dir = find_latest_run_dir(runs_root)
            if run_dir is None:
                print(f"[preview] Kein Run-Ordner gefunden unter: {runs_root.resolve()}")
                return 2
        else:
            run_dir = runs_root / args.run_name
            if not run_dir.exists():
                print(f"[preview] Run-Ordner nicht gefunden: {run_dir.resolve()}")
                return 2
        pulses_dir = run_dir / "Pulses"
        run_label = run_dir.name

    print(f"[preview] Pulses-Ordner: {pulses_dir.resolve()}")
    print(f"[preview] Update: alle {args.every} Pulse | poll={args.poll}s")

    # Plot-Setup
    plt.ion()
    fig, ax_u = plt.subplots(1, 1)
    try:
        fig.canvas.manager.set_window_title("Pulse Preview")
    except Exception:
        pass

    ax_i = ax_u.twinx()

    line_u, = ax_u.plot([], [], label="Voltage")
    line_i, = ax_i.plot([], [], label="Current")

    ax_u.set_ylabel("U [V]")
    ax_i.set_ylabel("I [A]")
    ax_u.set_xlabel("t [µs]")
    ax_u.grid(True)

    title = ax_u.set_title("Warte auf Pulsdaten…")

    last_shown_pid = None
    showed_first = False

    try:
        while plt.fignum_exists(fig.number):
            path, pid = find_latest_pulse_npz(pulses_dir)
            if pid is not None and path is not None:
                should_show = False
                if not showed_first:
                    should_show = True  # sofort beim ersten Fund
                elif last_shown_pid is None:
                    should_show = True
                elif pid != last_shown_pid and (pid % args.every == 0):
                    should_show = True

                if should_show:
                    try:
                        t, u, i, i_unit, pid2 = load_pulse_npz(path)
                        pid = pid2
                        t_us = (t - t[0]) * 1e6

                        line_u.set_data(t_us, u)
                        line_i.set_data(t_us, i)
                        ax_i.set_ylabel(f"I [{i_unit}]")

                        ax_u.relim(); ax_u.autoscale_view()
                        ax_i.relim(); ax_i.autoscale_view()

                        # Gemeinsame Legende (einmal pro Update ist ok)
                        ax_u.legend(handles=[line_u, line_i], loc="best")

                        title.set_text(f"{run_label} – Pulse {pid} (Update alle {args.every})")
                        fig.canvas.draw_idle()
                        fig.canvas.flush_events()

                        last_shown_pid = pid
                        showed_first = True
                        print(f"[preview] update -> pulse_id={pid} ({path.name})")
                    except Exception as e:
                        print(f"[preview] Fehler beim Laden/Plotten von {path.name}: {e}")

            time.sleep(args.poll)

    except KeyboardInterrupt:
        pass

    print("[preview] beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

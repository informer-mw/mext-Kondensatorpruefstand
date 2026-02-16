import time
import csv
import datetime as dt
from pathlib import Path
from ctypes import c_int16, c_int32, c_float

# ===================== CONFIG =====================
BASE_DIR = Path(r"C:\Users\mext\Desktop\Messreihen")
RUN_NAME = "TESTLAUF_16022026"

LOG_HZ = 1.0                  # 1 Hz
THERMO_TYPE = "K"             # K-Typ
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]

UNITS_C = 0                   # 0 = Celsius 
FILL_MISSING = 1              # 1 = fehlende Werte auffüllen 
READ_TIMEOUT_S = 2.0          # max. Wartezeit pro Kanal, bis ein Sample vorhanden ist
# ==================================================

RUN_DIR = BASE_DIR / "Runs" / RUN_NAME
OUT_CSV = RUN_DIR / f"{RUN_NAME}.tc08.csv"


def main():
    from picosdk.usbtc08 import usbtc08 as tc08

    RUN_DIR.mkdir(parents=True, exist_ok=True)

    #open_unit() ohne Argumente -> handle (int16)
    handle = tc08.usb_tc08_open_unit()
    if handle <= 0:
        raise RuntimeError(
            f"TC-08 konnte nicht geöffnet werden (handle={handle}). "
            f"Ist PicoLog/PicoScope offen oder ein anderes Script aktiv?"
        )

    try:
        try:
            tc08.usb_tc08_set_mains(handle, 0)
        except Exception:
            pass

        # Kanäle konfigurieren (K-Typ)
        for ch in CHANNELS:
            rc = tc08.usb_tc08_set_channel(handle, ch, ord(THERMO_TYPE))
            if rc == 0:
                raise RuntimeError(f"usb_tc08_set_channel fehlgeschlagen für CH{ch}")

        # Streaming starten: Abtastintervall in ms
        req_interval_ms = int(round(1000.0 / float(LOG_HZ)))
        actual_interval_ms = tc08.usb_tc08_run(handle, req_interval_ms)
        if actual_interval_ms == 0:
            raise RuntimeError("usb_tc08_run fehlgeschlagen")

        print(f"[TC08] Logging -> {OUT_CSV}")
        print(
            f"[TC08] LOG_HZ={LOG_HZ} (requested {req_interval_ms} ms, actual {actual_interval_ms} ms) "
            f"| channels={CHANNELS} | type={THERMO_TYPE}"
        )

        # Nach run() kurz warten, bis erste Samples im Buffer sind
        time.sleep(max(0.2, actual_interval_ms / 1000.0))

        # CSV Header
        is_new = not OUT_CSV.exists()
        with OUT_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["iso_time", "epoch_s"] + [f"T{ch}_C" for ch in CHANNELS])

            period = 1.0 / float(LOG_HZ)
            next_t = time.time()

            # 1-Sample Buffer pro Kanal
            temp_buf = (c_float * 1)()
            time_buf = (c_int32 * 1)()
            ovf_buf = (c_int16 * 1)()

            while True:
                temps = []

                for ch in CHANNELS:
                    rc = 0
                    t0 = time.time()

                    # Retry solange buffer leer (rc==0) bis Timeout
                    while rc == 0 and (time.time() - t0) < READ_TIMEOUT_S:
                        rc = tc08.usb_tc08_get_temp(
                            handle,
                            temp_buf,
                            time_buf,
                            1,          # buffer_length
                            ovf_buf,
                            ch,         # channel
                            UNITS_C,
                            FILL_MISSING
                        )
                        if rc == 0:
                            time.sleep(0.05)

                    if rc == 0:
                        # Debug-Info
                        try:
                            err = tc08.usb_tc08_get_last_error(handle)
                        except Exception:
                            err = "unknown"
                        raise RuntimeError(
                            f"usb_tc08_get_temp lieferte nach Timeout keine Daten bei CH{ch} | last_error={err}"
                        )

                    temps.append(float(temp_buf[0]))

                now = time.time()
                iso = dt.datetime.fromtimestamp(now).isoformat(timespec="seconds")
                w.writerow([iso, f"{now:.3f}"] + temps)
                f.flush()

                # Timing
                next_t += period
                sleep_s = next_t - time.time()
                if sleep_s > 0:
                    time.sleep(sleep_s)
                else:
                    next_t = time.time()

    finally:

        try:
            tc08.usb_tc08_stop(handle)
        except Exception:
            pass
        try:
            tc08.usb_tc08_close_unit(handle)
        except Exception:
            pass
        print("[TC08] closed")


if __name__ == "__main__":
    main()

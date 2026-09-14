"""Desktop launcher: bootstrap → migrate → serve → open browser.

Entry point for the packaged Windows build (PyInstaller) and for
`python launcher.py` in development. Keeps running until the console window
is closed or Ctrl+C.
"""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler

from app.bootstrap import prepare_runtime

PREFERRED_PORT = 8765


def _free_port(preferred: int) -> int:
    for port in (preferred, *range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


def _open_when_ready(url: str, health: str) -> None:
    import urllib.request

    for _ in range(100):
        try:
            with urllib.request.urlopen(health, timeout=1):  # noqa: S310 — local loopback only
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    webbrowser.open(url)


def main() -> int:
    os.environ.setdefault("PROSPERYA_PORTABLE", "1")
    data = prepare_runtime(migrate=True)

    handler = RotatingFileHandler(data / "logs" / "prosperya.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[handler, logging.StreamHandler(sys.stdout)])

    import uvicorn

    from app.main import app

    port = _free_port(int(os.environ.get("PROSPERYA_PORT", PREFERRED_PORT)))
    if not port:
        print("Nessuna porta libera trovata.")
        return 1
    url = f"http://127.0.0.1:{port}/"
    print("=" * 60)
    print(f"  Prosperya è in esecuzione: {url}")
    print(f"  Dati in: {data}")
    print("  Chiudi questa finestra per arrestare il programma.")
    print("=" * 60)
    threading.Thread(target=_open_when_ready, args=(url, url + "health"), daemon=True).start()
    # log_config=None → uvicorn reuses our root handlers (file + console).
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", access_log=False,
                log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())

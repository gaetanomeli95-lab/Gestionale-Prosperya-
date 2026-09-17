"""Desktop launcher: bootstrap → migrate → seed → serve → open window.

Entry point for the packaged Windows build (PyInstaller) and for
`python launcher.py` in development. Prefers a native WebView2 window
(pywebview) when available; falls back to the default browser. Keeps
running until the window is closed or Ctrl+C.
"""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler

from app.bootstrap import maybe_seed_preview, prepare_runtime

PREFERRED_PORT = 8765


def _free_port(preferred: int) -> int:
    for port in (preferred, *range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


def _wait_ready(health: str, attempts: int = 150) -> bool:
    import urllib.request

    for _ in range(attempts):
        try:
            with urllib.request.urlopen(health, timeout=1):  # noqa: S310 — local loopback only
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def _open_when_ready(url: str, health: str) -> None:
    if _wait_ready(health):
        webbrowser.open(url)


def _native_window(url: str, health: str) -> bool:
    """Open a chromeless WebView2 window via pywebview. Returns False when
    pywebview or the runtime is unavailable — caller falls back to browser."""
    try:
        import webview  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return False
    if not _wait_ready(health):
        return False
    try:
        webview.create_window("Prosperya", url, width=1440, height=900,
                              min_size=(1024, 640))
        webview.start(gui="edgechromium")
        return True
    except Exception:  # noqa: BLE001
        logging.getLogger("launcher").exception("Finestra nativa non disponibile")
        return False


def main() -> int:
    os.environ.setdefault("PROSPERYA_PORTABLE", "1")
    # This branch ships the client-validation build: always preview mode.
    os.environ.setdefault("PROSPERYA_PREVIEW", "1")
    try:
        data = prepare_runtime(migrate=True)
    except Exception:  # noqa: BLE001 — surface a readable error, keep logs
        _fatal("Impossibile preparare l'ambiente dati.")
        return 1

    handler = RotatingFileHandler(data / "logs" / "prosperya.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    # In --noconsole frozen builds sys.stdout is None: file handler only.
    handlers = [handler] + ([logging.StreamHandler(sys.stdout)] if sys.stdout else [])
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=handlers)

    log = logging.getLogger("launcher")
    try:
        maybe_seed_preview()
    except Exception:  # noqa: BLE001
        log.exception("Seed preview fallito")

    import uvicorn

    from app.main import app

    port = _free_port(int(os.environ.get("PROSPERYA_PORT", PREFERRED_PORT)))
    if not port:
        _fatal("Nessuna porta libera trovata.")
        return 1
    url = f"http://127.0.0.1:{port}/"
    log.info("Prosperya in esecuzione su %s — dati in %s", url, data)

    def _serve() -> None:
        # log_config=None → uvicorn reuses our root handlers (file + console).
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info",
                    access_log=False, log_config=None)

    server = threading.Thread(target=_serve, daemon=True)
    server.start()

    # Native window first (no browser chrome, no visible URL); browser as
    # fallback when WebView2/pywebview is unavailable.
    if not _native_window(url, url + "health"):
        threading.Thread(target=_open_when_ready, args=(url, url + "health"),
                         daemon=True).start()
        print("=" * 60)
        print(f"  Prosperya è in esecuzione: {url}")
        print(f"  Dati in: {data}")
        print("  Chiudi questa finestra per arrestare il programma.")
        print("=" * 60)
        try:
            while server.is_alive():
                server.join(timeout=1)
        except KeyboardInterrupt:
            pass
    return 0


def _fatal(message: str) -> None:
    """Human-readable startup failure: log it and, when frozen, show a
    Windows message box instead of dying silently."""
    logging.getLogger("launcher").exception("Avvio fallito: %s", message)
    print(f"ERRORE: {message}")
    print("Dettagli in data/logs/prosperya.log")
    if getattr(sys, "frozen", False):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0, f"{message}\n\nDettagli nel file di log dell'applicazione.",
                "Prosperya — errore di avvio", 0x10)
        except Exception:  # noqa: BLE001, S110 — best-effort UI, log already written
            pass


if __name__ == "__main__":
    sys.exit(main())

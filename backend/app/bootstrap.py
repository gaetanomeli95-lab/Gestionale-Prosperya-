"""Runtime bootstrap for a self-contained installation.

Resolves where the app lives (source tree or PyInstaller bundle), where user
data must go, generates a persistent JWT secret on first run, and applies
Alembic migrations. Idempotent: safe to call at every start.

Layout of a packaged install:
    <install>/Prosperya.exe
    <install>/_internal/...        (code, frontend dist, alembic scripts)
    <install>/data/prosperya.db    (user data — survives upgrades)
    <install>/data/.env            (generated secret + local overrides)
    <install>/data/logs/
"""
import logging
import os
import secrets
import sys
from pathlib import Path

log = logging.getLogger("bootstrap")

IS_FROZEN = getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """Read-only resources: alembic scripts, frontend dist."""
    if IS_FROZEN:
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent  # backend/


def install_dir() -> Path:
    """Writable root: next to the exe when frozen, repo root otherwise."""
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent  # repo root


def data_dir() -> Path:
    d = Path(os.environ.get("PROSPERYA_DATA_DIR") or install_dir() / "data")
    d.mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(exist_ok=True)
    return d


def frontend_dist() -> Path:
    if IS_FROZEN:
        return bundle_dir() / "frontend_dist"
    return install_dir() / "frontend" / "dist"


def _ensure_env(data: Path) -> None:
    """First run: write data/.env with a random secret and a local SQLite URL.
    Existing files are never overwritten (customers may edit them)."""
    env_file = data / ".env"
    if not env_file.exists():
        db_path = (data / "prosperya.db").as_posix()
        env_file.write_text(
            "# Generato al primo avvio. Non condividere questo file.\n"
            f"JWT_SECRET={secrets.token_urlsafe(48)}\n"
            f"DATABASE_URL=sqlite:///{db_path}\n"
            "ENVIRONMENT=production\n"
            "APP_NAME=Prosperya\n",
            encoding="utf-8",
        )
        log.info("Creato %s", env_file)
    # Load into process env WITHOUT overriding explicit env vars.
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config()
    cfg.set_main_option("script_location", str(bundle_dir() / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(bundle_dir()))
    command.upgrade(cfg, "head")


def prepare_runtime(*, migrate: bool = True) -> Path:
    """Call BEFORE importing app.main/app.db (settings are cached on import)."""
    data = data_dir()
    if IS_FROZEN or os.environ.get("PROSPERYA_PORTABLE"):
        _ensure_env(data)
    if migrate:
        run_migrations()
    return data

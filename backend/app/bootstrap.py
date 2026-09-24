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
    """Writable user data. Frozen builds use %LOCALAPPDATA%\\Prosperya so the
    app can install per-user without admin rights and upgrades/uninstalls
    never touch the database. PROSPERYA_DATA_DIR overrides everything."""
    override = os.environ.get("PROSPERYA_DATA_DIR")
    if override:
        d = Path(override)
    elif IS_FROZEN:
        d = Path(os.environ.get("LOCALAPPDATA", install_dir())) / "Prosperya"
    else:
        d = install_dir() / "data"
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
        preview = os.environ.get("PROSPERYA_PREVIEW") == "1"
        env_file.write_text(
            "# Generato al primo avvio. Non condividere questo file.\n"
            f"JWT_SECRET={secrets.token_urlsafe(48)}\n"
            f"DATABASE_URL=sqlite:///{db_path}\n"
            "ENVIRONMENT=production\n"
            "APP_NAME=Prosperya\n"
            + ("PROSPERYA_PREVIEW=1\n"
               "SEED_ADMIN_EMAIL=demo@prosperya.it\n"
               "SEED_ADMIN_PASSWORD=Prosperya-Demo-2026\n" if preview else ""),
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


def maybe_seed_preview() -> None:
    """Populate the demo dataset on first run of a preview build.

    Only runs when PROSPERYA_PREVIEW=1 (written into the generated .env by
    preview packaging) and the users table is still empty. Both seed()
    and seed_preview() are idempotent, so a re-run is harmless.
    """
    if os.environ.get("PROSPERYA_PREVIEW") != "1":
        return
    try:
        from sqlalchemy import select

        import app.models_all  # noqa: F401 — full mapper registry
        from app.db import SessionLocal
        from app.modules.users.models import User

        with SessionLocal() as db:
            if db.scalar(select(User).limit(1)) is not None:
                return
        from app.preview_seed import seed_preview
        from app.seed import seed

        with SessionLocal() as db:
            seed(db)
        with SessionLocal() as db:
            seed_preview(db)
        log.info("Dataset dimostrativo inizializzato.")
    except Exception:  # noqa: BLE001 — never block startup on seeding
        log.exception("Seed del dataset dimostrativo fallito")


def prepare_runtime(*, migrate: bool = True) -> Path:
    """Call BEFORE importing app.main/app.db (settings are cached on import)."""
    data = data_dir()
    if IS_FROZEN or os.environ.get("PROSPERYA_PORTABLE"):
        _ensure_env(data)
    if migrate:
        run_migrations()
    return data

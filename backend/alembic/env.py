"""Alembic environment. The URL comes from app.config so a single
DATABASE_URL drives the app, tests and migrations."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import Base

# Import all models so autogenerate sees every table.
import app.modules.users.models  # noqa: F401
import app.modules.service_lines.models  # noqa: F401
import app.modules.companies.models  # noqa: F401
import app.modules.contacts.models  # noqa: F401
import app.modules.leads.models  # noqa: F401
import app.modules.opportunities.models  # noqa: F401
import app.modules.tasks.models  # noqa: F401
import app.modules.notes.models  # noqa: F401
import app.modules.activities.models  # noqa: F401
import app.modules.audit.models  # noqa: F401
import app.modules.billing.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_settings().database_url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

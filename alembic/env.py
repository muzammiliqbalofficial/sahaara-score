"""
Alembic environment configuration.

Imports the app's Settings so the migration URL always matches the running
application. Also imports all ORM models via ``target_metadata`` so that
``alembic revision --autogenerate`` can diff against the current schema.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.database import Base

# Import all models so they register with Base.metadata.
import app.models # noqa: F401

# Alembic Config object.
config = context.config

# Override sqlalchemy.url from app settings (takes precedence over alembic.ini).
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Python logging setup from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to the database).

    Uses NullPool since migrations are short-lived and don't benefit
    from connection pooling. pool_pre_ping + connect_timeout handle
    Neon's serverless cold-start behaviour.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

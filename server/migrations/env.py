import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from radd.config import settings
from radd.db import Base
from radd.kernel import import_models

# Core modules' tables are managed — the plugin system applies to migrations too.
# Installable (non-core) plugins are ALSO scanned: their tables persist across
# enable/disable (install = migrate, so their schema is version-controlled even
# while a plugin is disabled), so autogenerate must see them or it would propose
# dropping an installed-but-disabled plugin's table (spec 93 / A4).
import_models(settings.modules + settings.installable_plugins)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

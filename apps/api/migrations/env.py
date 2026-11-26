import os

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app import models


url = os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("Set DATABASE_URL explicitly before running migrations.")

options = {"target_metadata": models.Base.metadata, "compare_type": True}

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True, **options)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, **options)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()

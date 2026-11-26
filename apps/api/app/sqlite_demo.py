"""Add legacy columns to the isolated SQLite demo before initializing tables."""
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Engine


DEMO_COLUMNS = {
    "organizations": {
        "timezone": "VARCHAR(80) NOT NULL DEFAULT 'UTC'",
        "currency": "VARCHAR(3) NOT NULL DEFAULT 'USD'",
        "industry": "VARCHAR(100) NOT NULL DEFAULT ''",
        "branding_json": "TEXT NOT NULL DEFAULT '{}'",
        "settings_json": "TEXT NOT NULL DEFAULT '{}'",
        "onboarding_json": "TEXT NOT NULL DEFAULT '{}'",
    },
    "incidents": {
        "assignee_id": "VARCHAR REFERENCES users(id)",
        "team": "VARCHAR(120) NOT NULL DEFAULT ''",
    },
}


def upgrade_demo_columns(engine: Engine) -> None:
    database = Path(engine.url.database or "")
    expected = Path.cwd().resolve() / ".dev-logs" / "vyrnexis-demo.db"
    if engine.dialect.name != "sqlite" or database.resolve() != expected:
        raise RuntimeError("SQLite demo upgrade requires .dev-logs/vyrnexis-demo.db")
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        schema = inspect(connection)
        for table, definitions in DEMO_COLUMNS.items():
            if not schema.has_table(table):
                continue
            present = {column["name"] for column in schema.get_columns(table)}
            for name, definition in definitions.items():
                if name not in present:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        if schema.has_table("incidents"):
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_incidents_assignee_id ON incidents (assignee_id)")
        connection.commit()

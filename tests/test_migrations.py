from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
import pytest

from app.sqlite_demo import upgrade_demo_columns


def test_sqlite_demo_compatibility_preserves_legacy_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".dev-logs").mkdir()
    engine = create_engine("sqlite:///./.dev-logs/vyrnexis-demo.db")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE organizations (id TEXT PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("CREATE TABLE incidents (id TEXT PRIMARY KEY, title TEXT)")
        connection.exec_driver_sql("INSERT INTO organizations VALUES ('org', 'Existing organization')")
        connection.exec_driver_sql("INSERT INTO incidents VALUES ('incident', 'Existing incident')")
    try:
        upgrade_demo_columns(engine)
        upgrade_demo_columns(engine)
        with engine.connect() as connection:
            organization = connection.exec_driver_sql("SELECT name, timezone, currency FROM organizations").one()
            incident = connection.exec_driver_sql("SELECT title, assignee_id, team FROM incidents").one()
            assert organization == ("Existing organization", "UTC", "USD")
            assert incident == ("Existing incident", None, "")
        assert [index["name"] for index in inspect(engine).get_indexes("incidents")] == ["ix_incidents_assignee_id"]
    finally:
        engine.dispose()

    protected = create_engine("sqlite:///./vyrnexis.db")
    try:
        with pytest.raises(RuntimeError, match="SQLite demo upgrade requires"):
            upgrade_demo_columns(protected)
        assert not (tmp_path / "vyrnexis.db").exists()
    finally:
        protected.dispose()


def test_detection_migration_preserves_existing_organizations(tmp_path, monkeypatch):
    database = tmp_path / "migrations.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "apps/api/alembic.ini"))
    command.upgrade(config, "0001")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO organizations (id, name, slug, created_at) "
                                    "VALUES ('saved', 'Existing record', 'saved', CURRENT_TIMESTAMP)"))
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT name FROM organizations WHERE id = 'saved'")) == "Existing record"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0018"
        assert "detection_runs" in inspect(engine).get_table_names()
        assert "commerce_findings" in inspect(engine).get_table_names()
        assert "custody_events" in inspect(engine).get_table_names()
        assert "investigation_tasks" in inspect(engine).get_table_names()
        assert "evidence_image_metadata" in inspect(engine).get_table_names()
        assert "knowledge_chunks" in inspect(engine).get_table_names()
        assert "copilot_turns" in inspect(engine).get_table_names()
        assert "investigation_replays" in inspect(engine).get_table_names()
        assert "counterfactual_scenarios" in inspect(engine).get_table_names()
        assert "workflow_approvals" in inspect(engine).get_table_names()
        assert "twin_simulations" in inspect(engine).get_table_names()
        assert "knowledge_embeddings" in inspect(engine).get_table_names()
        columns = {column["name"] for column in inspect(engine).get_columns("organizations")}
        assert {"timezone", "currency", "industry", "branding_json", "settings_json", "onboarding_json"} <= columns
        assert "asset_assignments" in inspect(engine).get_table_names()
        assert "asset_history" in inspect(engine).get_table_names()
        assert "asset_vulnerabilities" in inspect(engine).get_table_names()
        incident_columns = {column["name"] for column in inspect(engine).get_columns("incidents")}
        assert {"assignee_id", "team"} <= incident_columns
        assert "threat_indicators" in inspect(engine).get_table_names()
        assert "report_records" in inspect(engine).get_table_names()
        assert "api_credentials" in inspect(engine).get_table_names()
        assert "notifications" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

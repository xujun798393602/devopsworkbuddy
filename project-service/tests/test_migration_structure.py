"""Migration SQL/metadata structure tests — run without a database connection."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"

_MIGRATION_FILES = {
    "0001": "0001_projects_and_idempotency",
    "0002": "0002_project_collaboration",
}


def _load_migration(revision: str):
    """Dynamically load a migration module by revision ID."""
    filename = _MIGRATION_FILES[revision]
    module_path = MIGRATIONS_DIR / f"{filename}.py"
    spec = importlib.util.spec_from_file_location(filename, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigration0001Structure:
    """Static structure checks for 0001 — no database required."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.migration = _load_migration("0001")

    def test_revision_chain(self) -> None:
        assert self.migration.revision == "0001"
        assert self.migration.down_revision is None

    def test_upgrade_creates_projects_and_idempotency(self) -> None:
        """upgrade() must define both tables and their sequences."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        assert "CREATE SEQUENCE project_business_no_seq" in source
        assert 'create_table(' in source and '"projects"' in source
        assert 'create_table(' in source and '"idempotency_records"' in source
        assert "uq_idempotency_scope_key" in source

    def test_downgrade_drops_tables_and_sequence(self) -> None:
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        assert 'drop_table("idempotency_records"' in source
        assert 'drop_table("projects"' in source
        assert "DROP SEQUENCE project_business_no_seq" in source

    def test_upgrade_downgrade_symmetry(self) -> None:
        """Every table created in upgrade must be dropped in downgrade."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        import re

        # Extract table names from multi-line create_table("table_name",
        created = set(re.findall(r'create_table\(\s*"(\w+)"', source))
        dropped = set(re.findall(r'drop_table\("(\w+)"', source))
        assert created == dropped, f"Asymmetric: created={created}, dropped={dropped}"


class TestMigration0002Structure:
    """Static structure checks for 0002 — no database required."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.migration = _load_migration("0002")

    def test_revision_chain(self) -> None:
        assert self.migration.revision == "0002"
        assert self.migration.down_revision == "0001"

    def test_pgcrypto_before_gen_random_uuid(self) -> None:
        """pgcrypto extension must be created before gen_random_uuid() backfill."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        crypto_pos = source.index('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
        # Find the actual SQL usage, not the comment
        gen_uuid_pos = source.index("SELECT gen_random_uuid()")
        assert crypto_pos < gen_uuid_pos, "pgcrypto must be created before gen_random_uuid()"

    def test_no_duplicate_ck_idempotency_status_creation(self) -> None:
        """0002 must not re-create ck_idempotency_status (already created in 0001)."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        # 0002 should drop ck_idempotency_state but NOT re-create ck_idempotency_status
        assert 'drop_constraint("ck_idempotency_state"' in source
        # The following line must NOT appear in 0002's upgrade:
        upgrade_section = source.split("def downgrade")[0]
        assert (
            'create_check_constraint(\n        "ck_idempotency_status"' not in upgrade_section
        ), "0002 must not re-create ck_idempotency_status (already exists from 0001)"

    def test_all_tables_created_in_correct_dependency_order(self) -> None:
        """Tables with composite FKs must be created after their referent tables."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        import re

        def first_create_pos(table_name: str) -> int:
            match = re.search(rf'create_table\(\s*"{table_name}"', source)
            assert match, f"Table {table_name} not found in upgrade"
            return match.start()

        pos_projects = source.index("projects")  # projects already exists from 0001
        pos_rv = first_create_pos("release_versions")
        pos_iter = first_create_pos("iterations")
        pos_tasks = first_create_pos("tasks")
        pos_tp = first_create_pos("task_participants")
        pos_wl = first_create_pos("worklogs")

        # release_versions and iterations reference projects (created in 0001) — both after projects
        assert pos_rv > pos_projects
        assert pos_iter > pos_projects
        # tasks references release_versions and iterations via composite FK
        assert pos_tasks > pos_rv
        assert pos_tasks > pos_iter
        # task_participants references tasks via composite FK
        assert pos_tp > pos_tasks
        # worklogs references tasks via composite FK
        assert pos_wl > pos_tasks

    def test_upgrade_downgrade_index_symmetry(self) -> None:
        """Every index created in upgrade must be dropped in downgrade."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        import re

        upgrade_section = source.split("def downgrade")[0]
        downgrade_section = source.split("def downgrade")[1]

        created_indexes = re.findall(r'create_index\(\s*"(\w+)"', upgrade_section)
        dropped_indexes = re.findall(r'drop_index\("(\w+)"', downgrade_section)

        created_set = set(created_indexes)
        dropped_set = set(dropped_indexes)
        missing = created_set - dropped_set
        assert not missing, f"Indexes created but not dropped: {missing}"

    def test_upgrade_downgrade_table_symmetry(self) -> None:
        """Every table created in upgrade must be dropped in downgrade."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        import re

        upgrade_section = source.split("def downgrade")[0]
        downgrade_section = source.split("def downgrade")[1]

        created_tables = re.findall(r'create_table\(\s*"(\w+)"', upgrade_section)
        dropped_tables = re.findall(r'drop_table\("(\w+)"', downgrade_section)

        created_set = set(created_tables)
        dropped_set = set(dropped_tables)
        missing = created_set - dropped_set
        assert not missing, f"Tables created but not dropped: {missing}"

    def test_upgrade_downgrade_column_symmetry(self) -> None:
        """Every column added to idempotency_records in upgrade must be dropped in downgrade."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        import re

        upgrade_section = source.split("def downgrade")[0]
        downgrade_section = source.split("def downgrade")[1]

        added_columns = re.findall(r'add_column\(\s*"idempotency_records",\s*sa\.Column\("(\w+)"', upgrade_section)
        dropped_columns = re.findall(r'drop_column\("idempotency_records",\s*"(\w+)"', downgrade_section)

        added_set = set(added_columns)
        dropped_set = set(dropped_columns)
        missing = added_set - dropped_set
        assert not missing, f"Columns added but not dropped: {missing}"

    def test_downgrade_restores_resource_id_fk(self) -> None:
        """Downgrade must restore the resource_id FK that upgrade dropped."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        downgrade_section = source.split("def downgrade")[1]
        assert "idempotency_records_resource_id_fkey" in downgrade_section
        assert "create_foreign_key" in downgrade_section

    def test_downgrade_restores_ck_idempotency_state(self) -> None:
        """Downgrade must restore ck_idempotency_state that upgrade dropped."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        downgrade_section = source.split("def downgrade")[1]
        assert "ck_idempotency_state" in downgrade_section

    def test_owner_backfill_uses_gen_random_uuid(self) -> None:
        """The owner membership backfill must use gen_random_uuid() for IDs."""
        source = Path(self.migration.__file__).read_text(encoding="utf-8")
        assert "gen_random_uuid()" in source
        assert "INSERT INTO project_memberships" in source


class TestTableMetadataStructure:
    """Verify SQLAlchemy table metadata matches migration DDL structure."""

    def test_all_tables_present_in_metadata(self) -> None:
        from project_service.persistence.tables import Base

        table_names = set(Base.metadata.tables.keys())
        expected = {
            "projects",
            "project_memberships",
            "project_counters",
            "release_versions",
            "iterations",
            "tasks",
            "task_participants",
            "worklogs",
            "idempotency_records",
            "audit_records",
            "outbox_events",
        }
        assert expected <= table_names, f"Missing tables: {expected - table_names}"

    def test_task_composite_fk_columns_exist(self) -> None:
        from project_service.persistence.tables import TaskRow

        columns = {col.name for col in TaskRow.__table__.columns}
        assert {"project_id", "release_version_id", "iteration_id"} <= columns

    def test_worklog_composite_fk_columns_exist(self) -> None:
        from project_service.persistence.tables import WorklogRow

        columns = {col.name for col in WorklogRow.__table__.columns}
        assert {"project_id", "task_id"} <= columns

    def test_idempotency_record_has_replay_columns(self) -> None:
        from project_service.persistence.tables import IdempotencyRecordRow

        columns = {col.name for col in IdempotencyRecordRow.__table__.columns}
        assert {"response_status", "response_body", "response_headers", "operation"} <= columns

    def test_membership_partial_unique_indexes_exist(self) -> None:
        from project_service.persistence.tables import ProjectMembershipRow

        index_names = {idx.name for idx in ProjectMembershipRow.__table__.indexes}
        assert "uq_membership_active_user" in index_names
        assert "uq_membership_active_owner" in index_names

    def test_version_normalized_name_index_exists(self) -> None:
        from project_service.persistence.tables import ReleaseVersionRow

        index_names = {idx.name for idx in ReleaseVersionRow.__table__.indexes}
        assert "uq_versions_normalized_name" in index_names

    def test_iteration_active_partial_unique_exists(self) -> None:
        from project_service.persistence.tables import IterationRow

        index_names = {idx.name for idx in IterationRow.__table__.indexes}
        assert "uq_iterations_active" in index_names

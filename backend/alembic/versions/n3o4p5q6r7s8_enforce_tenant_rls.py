"""enforce tenant constraints and PostgreSQL row-level security

Revision ID: n3o4p5q6r7s8
Revises: m2n3o4p5q6r7
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "n3o4p5q6r7s8"
down_revision: Union[str, None] = "m2n3o4p5q6r7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = (
    "users",
    "positions",
    "question_banks",
    "resumes",
    "department_reviews",
    "interviews",
    "interview_panels",
    "offers",
    "offer_templates",
    "coding_tests",
    "coding_submissions",
    "system_configs",
    "workflows",
    "workflow_nodes",
    "workflow_edges",
    "workflow_executions",
    "workflow_node_executions",
    "stored_files",
)

GLOBAL_TABLES = (
    "tenants",
    "tenant_domains",
    "platform_users",
    "platform_audit_logs",
    "public_access_tokens",
)

# child table, local id column, parent table, ON DELETE action, pre-RLS FK name.
# A None legacy name means the old schema had no foreign key for that column.
COMPOSITE_FOREIGN_KEYS = (
    ("positions", "hiring_manager_id", "users", None, "fk_positions_hiring_manager"),
    ("question_banks", "source_file_id", "stored_files", None, "fk_question_banks_source_file_id"),
    ("question_banks", "position_id", "positions", None, "question_banks_position_id_fkey"),
    ("resumes", "position_id", "positions", None, "resumes_position_id_fkey"),
    ("resumes", "file_id", "stored_files", None, "fk_resumes_file_id"),
    ("resumes", "rejected_by", "users", "SET NULL", "fk_resumes_rejected_by"),
    ("department_reviews", "resume_id", "resumes", "CASCADE", "department_reviews_resume_id_fkey"),
    ("department_reviews", "reviewer_id", "users", "CASCADE", "department_reviews_reviewer_id_fkey"),
    ("interviews", "resume_id", "resumes", None, "interviews_resume_id_fkey"),
    ("interviews", "position_id", "positions", None, "interviews_position_id_fkey"),
    ("interviews", "interviewer_id", "users", None, "interviews_interviewer_id_fkey"),
    ("interview_panels", "interview_id", "interviews", None, "interview_panels_interview_id_fkey"),
    ("interview_panels", "interviewer_id", "users", None, "interview_panels_interviewer_id_fkey"),
    ("offers", "resume_id", "resumes", None, "offers_resume_id_fkey"),
    ("offers", "position_id", "positions", None, "offers_position_id_fkey"),
    ("offers", "created_by", "users", None, "offers_created_by_fkey"),
    ("offer_templates", "position_id", "positions", None, "offer_templates_position_id_fkey"),
    ("offer_templates", "created_by", "users", None, "offer_templates_created_by_fkey"),
    ("coding_tests", "question_bank_id", "question_banks", None, "coding_tests_question_bank_id_fkey"),
    ("coding_tests", "created_by", "users", None, "coding_tests_created_by_fkey"),
    ("coding_tests", "resume_id", "resumes", None, "coding_tests_resume_id_fkey"),
    ("coding_tests", "position_id", "positions", None, "coding_tests_position_id_fkey"),
    ("coding_submissions", "coding_test_id", "coding_tests", None, "coding_submissions_coding_test_id_fkey"),
    ("workflows", "created_by", "users", None, "workflows_created_by_fkey"),
    ("workflow_nodes", "workflow_id", "workflows", None, "workflow_nodes_workflow_id_fkey"),
    ("workflow_edges", "workflow_id", "workflows", None, "workflow_edges_workflow_id_fkey"),
    ("workflow_executions", "workflow_id", "workflows", None, "workflow_executions_workflow_id_fkey"),
    ("workflow_executions", "triggered_by", "users", None, "workflow_executions_triggered_by_fkey"),
    ("workflow_node_executions", "execution_id", "workflow_executions", None, "workflow_node_executions_execution_id_fkey"),
)

POSTGRESQL_SET_NULL_COLUMNS = {
    ("resumes", "rejected_by"): ("rejected_by",),
}


def _create_missing_business_schema(bind) -> None:
    """Finish tables historically supplied by metadata.create_all.

    Older deployments already have these objects. Fresh PostgreSQL databases
    need Alembic to own them now that the runtime role cannot execute DDL.
    Compatibility objects are intentionally retained by downgrade so tenant
    business data is never deleted.
    """

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "interview_panels" not in existing_tables:
        op.create_table(
            "interview_panels",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("interview_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("interviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("scores", sa.JSON(), nullable=True),
            sa.Column("comments", sa.JSON(), nullable=True),
            sa.Column("audio_records", sa.JSON(), nullable=True),
            sa.Column("transcripts", sa.JSON(), nullable=True),
            sa.Column("total_score", sa.Integer(), nullable=True),
            sa.Column("is_submitted", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_interview_panels_tenant_id", "interview_panels", ["tenant_id"])

    if "offers" not in existing_tables:
        op.create_table(
            "offers",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("candidate_name", sa.String(), nullable=False),
            sa.Column("candidate_email", sa.String(), nullable=False),
            sa.Column("salary_monthly", sa.Float(), nullable=True),
            sa.Column("salary_annual", sa.Float(), nullable=True),
            sa.Column("salary_structure", sa.Text(), nullable=True),
            sa.Column("position_title", sa.String(), nullable=False),
            sa.Column("department", sa.String(), nullable=True),
            sa.Column("report_to", sa.String(), nullable=True),
            sa.Column("work_location", sa.String(), nullable=True),
            sa.Column("work_hours", sa.String(), nullable=True),
            sa.Column("onboard_date", sa.DateTime(), nullable=True),
            sa.Column("probation_months", sa.Integer(), nullable=True),
            sa.Column("benefits", sa.Text(), nullable=True),
            sa.Column("bonus", sa.Text(), nullable=True),
            sa.Column("special_terms", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("valid_until", sa.DateTime(), nullable=True),
            sa.Column("status", sa.Enum("DRAFT", "PENDING", "SENT", "ACCEPTED", "REJECTED", "EXPIRED", "WITHDRAWN", name="offerstatus"), nullable=True),
            sa.Column("token", sa.String(), nullable=True, unique=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_index("ix_offers_tenant_id", "offers", ["tenant_id"])

    if "offer_templates" not in existing_tables:
        op.create_table(
            "offer_templates",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("salary_monthly", sa.Float(), nullable=True),
            sa.Column("salary_annual", sa.Float(), nullable=True),
            sa.Column("salary_structure", sa.Text(), nullable=True),
            sa.Column("department", sa.String(), nullable=True),
            sa.Column("report_to", sa.String(), nullable=True),
            sa.Column("work_location", sa.String(), nullable=True),
            sa.Column("work_hours", sa.String(), nullable=True),
            sa.Column("probation_months", sa.Integer(), nullable=True),
            sa.Column("benefits", sa.Text(), nullable=True),
            sa.Column("bonus", sa.Text(), nullable=True),
            sa.Column("special_terms", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("valid_days", sa.Integer(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_index("ix_offer_templates_tenant_id", "offer_templates", ["tenant_id"])

    if "coding_tests" not in existing_tables:
        op.create_table(
            "coding_tests",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("test_type", sa.String(20), nullable=True),
            sa.Column("difficulty", sa.String(), nullable=True),
            sa.Column("language", sa.String(), nullable=True),
            sa.Column("starter_code", sa.Text(), nullable=True),
            sa.Column("test_cases", sa.JSON(), nullable=True),
            sa.Column("time_limit_ms", sa.Integer(), nullable=True),
            sa.Column("memory_limit_mb", sa.Integer(), nullable=True),
            sa.Column("public_token", sa.String(), nullable=False, unique=True),
            sa.Column("status", sa.Enum("DRAFT", "PUBLISHED", "CLOSED", name="codingteststatus"), nullable=True),
            sa.Column("question_bank_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("questions", sa.JSON(), nullable=True),
            sa.Column("question_generation_status", sa.String(20), nullable=True),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_coding_tests_public_token", "coding_tests", ["public_token"])
        op.create_index("ix_coding_tests_tenant_id", "coding_tests", ["tenant_id"])

    if "coding_submissions" not in existing_tables:
        op.create_table(
            "coding_submissions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("coding_test_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("candidate_name", sa.String(), nullable=True),
            sa.Column("candidate_email", sa.String(), nullable=True),
            sa.Column("language", sa.String(), nullable=True),
            sa.Column("code", sa.Text(), nullable=True),
            sa.Column("answers", sa.JSON(), nullable=True),
            sa.Column("run_result", sa.JSON(), nullable=True),
            sa.Column("passed", sa.Boolean(), nullable=True),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("ai_evaluation", sa.Text(), nullable=True),
            sa.Column("status", sa.Enum("DRAFT", "SUBMITTED", "EVALUATED", name="codingsubmissionstatus"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_coding_submissions_tenant_id", "coding_submissions", ["tenant_id"])

    inspector = sa.inspect(bind)
    existing_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("resumes", "interviews")
    }
    if "stage" not in existing_columns["resumes"]:
        op.add_column("resumes", sa.Column("stage", sa.String(), nullable=True))
    interview_columns = {
        "interviewer_id": sa.Column("interviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
        "round": sa.Column("round", sa.Integer(), nullable=True),
        "started_at": sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        "panel_members": sa.Column("panel_members", sa.JSON(), nullable=True),
        "audio_records": sa.Column("audio_records", sa.JSON(), nullable=True),
        "transcripts": sa.Column("transcripts", sa.JSON(), nullable=True),
    }
    for name, column in interview_columns.items():
        if name not in existing_columns["interviews"]:
            op.add_column("interviews", column)


def _tenant_identity_name(table: str) -> str:
    return f"uq_{table}_tenant_id_id"


def _tenant_fk_name(table: str, column: str) -> str:
    return f"fk_{table}_{column}_tenant"


def _create_tenant_foreign_key(
    child: str, column: str, parent: str, ondelete: str | None
) -> None:
    set_null_columns = POSTGRESQL_SET_NULL_COLUMNS.get((child, column), ())
    if set_null_columns:
        # PostgreSQL 15 supports a column list for SET NULL. Without it the
        # composite action also clears tenant_id and violates NOT NULL.
        quoted_set_null_columns = ", ".join(
            f'"{set_null_column}"' for set_null_column in set_null_columns
        )
        op.execute(
            f'ALTER TABLE "{child}" '
            f'ADD CONSTRAINT "{_tenant_fk_name(child, column)}" '
            f'FOREIGN KEY (tenant_id, "{column}") '
            f'REFERENCES "{parent}" (tenant_id, id) '
            f"ON DELETE SET NULL ({quoted_set_null_columns})"
        )
        return
    op.create_foreign_key(
        _tenant_fk_name(child, column),
        child,
        parent,
        ["tenant_id", column],
        ["tenant_id", "id"],
        ondelete=ondelete,
    )


def _unique_column_sets(inspector, table: str) -> set[tuple[str, ...]]:
    return {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table)
    }


def _foreign_keys_for(inspector, table: str, column: str, parent: str):
    return [
        foreign_key
        for foreign_key in inspector.get_foreign_keys(table)
        if foreign_key["constrained_columns"] == [column]
        and foreign_key["referred_table"] == parent
    ]


def _assert_complete_schema(bind) -> None:
    existing_tables = set(sa.inspect(bind).get_table_names())
    missing_tables = sorted(set(TENANT_TABLES) - existing_tables)
    if missing_tables:
        raise RuntimeError(
            "Cannot enforce tenant isolation; missing tenant tables: "
            + ", ".join(missing_tables)
        )


def _assert_no_null_tenant_ids(bind) -> None:
    for table in TENANT_TABLES:
        null_count = bind.execute(
            sa.text(f'SELECT count(*) FROM "{table}" WHERE tenant_id IS NULL')
        ).scalar_one()
        if null_count:
            raise RuntimeError(
                f'Cannot enforce tenant isolation on "{table}": '
                f"{null_count} rows have NULL tenant_id"
            )


def _assert_no_cross_tenant_references(bind) -> None:
    for child, column, parent, _ondelete, _legacy_name in COMPOSITE_FOREIGN_KEYS:
        mismatch_count = bind.execute(
            sa.text(
                f'SELECT count(*) FROM "{child}" AS child '
                f'JOIN "{parent}" AS parent ON parent.id = child."{column}" '
                f'WHERE child."{column}" IS NOT NULL '
                "AND child.tenant_id <> parent.tenant_id"
            )
        ).scalar_one()
        if mismatch_count:
            raise RuntimeError(
                f'Cannot enforce tenant reference "{child}.{column}": '
                f"{mismatch_count} rows reference another tenant"
            )


def upgrade() -> None:
    bind = op.get_bind()
    _create_missing_business_schema(bind)
    _assert_complete_schema(bind)
    _assert_no_null_tenant_ids(bind)
    _assert_no_cross_tenant_references(bind)

    for table in TENANT_TABLES:
        op.alter_column(
            table,
            "tenant_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )

    inspector = sa.inspect(bind)
    for table in TENANT_TABLES:
        if ("tenant_id", "id") not in _unique_column_sets(inspector, table):
            op.create_unique_constraint(
                _tenant_identity_name(table), table, ["tenant_id", "id"]
            )
            inspector = sa.inspect(bind)

    for child, column, parent, ondelete, _legacy_name in COMPOSITE_FOREIGN_KEYS:
        inspector = sa.inspect(bind)
        for foreign_key in _foreign_keys_for(inspector, child, column, parent):
            if foreign_key["name"]:
                op.drop_constraint(foreign_key["name"], child, type_="foreignkey")
        _create_tenant_foreign_key(child, column, parent, ondelete)

    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''
            CREATE POLICY "{table}_tenant_isolation" ON "{table}"
            USING (
              tenant_id = NULLIF(
                current_setting('app.current_tenant_id', true), ''
              )::uuid
            )
            WITH CHECK (
              tenant_id = NULLIF(
                current_setting('app.current_tenant_id', true), ''
              )::uuid
            )
            '''
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    scoped_tables = [table for table in TENANT_TABLES if table in existing_tables]

    for table in reversed(scoped_tables):
        op.execute(
            f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"'
        )
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

    for child, column, parent, ondelete, legacy_name in reversed(
        COMPOSITE_FOREIGN_KEYS
    ):
        if child not in existing_tables or parent not in existing_tables:
            continue
        constraint_name = _tenant_fk_name(child, column)
        foreign_key_names = {
            foreign_key["name"]
            for foreign_key in sa.inspect(bind).get_foreign_keys(child)
        }
        if constraint_name in foreign_key_names:
            op.drop_constraint(constraint_name, child, type_="foreignkey")
        if legacy_name is not None:
            op.create_foreign_key(
                legacy_name,
                child,
                parent,
                [column],
                ["id"],
                ondelete=ondelete,
            )

    for table in reversed(scoped_tables):
        constraint_name = _tenant_identity_name(table)
        unique_names = {
            constraint["name"]
            for constraint in sa.inspect(bind).get_unique_constraints(table)
        }
        if table != "users" and constraint_name in unique_names:
            op.drop_constraint(constraint_name, table, type_="unique")

    for table in scoped_tables:
        if table == "stored_files":
            continue
        op.alter_column(
            table,
            "tenant_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )

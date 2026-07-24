"""add tenant-scoped stored files

Revision ID: m2n3o4p5q6r7
Revises: l1m2n3o4p5q6
Create Date: 2026-07-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "m2n3o4p5q6r7"
down_revision: Union[str, None] = "l1m2n3o4p5q6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255)),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stored_files_tenant_id", "stored_files", ["tenant_id"])
    op.create_index("ix_stored_files_resource_type", "stored_files", ["resource_type"])
    op.create_index("ix_stored_files_resource_id", "stored_files", ["resource_id"])
    op.create_index("ix_stored_files_tenant_resource", "stored_files", ["tenant_id", "resource_type", "resource_id"])
    op.add_column("resumes", sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_resumes_file_id", "resumes", "stored_files", ["file_id"], ["id"])
    op.create_index("ix_resumes_file_id", "resumes", ["file_id"])
    op.add_column("question_banks", sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_question_banks_source_file_id", "question_banks", "stored_files", ["source_file_id"], ["id"])
    op.create_index("ix_question_banks_source_file_id", "question_banks", ["source_file_id"])

def downgrade() -> None:
    op.drop_index("ix_question_banks_source_file_id", table_name="question_banks")
    op.drop_constraint("fk_question_banks_source_file_id", "question_banks", type_="foreignkey")
    op.drop_column("question_banks", "source_file_id")
    op.drop_index("ix_resumes_file_id", table_name="resumes")
    op.drop_constraint("fk_resumes_file_id", "resumes", type_="foreignkey")
    op.drop_column("resumes", "file_id")
    op.drop_index("ix_stored_files_tenant_resource", table_name="stored_files")
    op.drop_index("ix_stored_files_resource_id", table_name="stored_files")
    op.drop_index("ix_stored_files_resource_type", table_name="stored_files")
    op.drop_index("ix_stored_files_tenant_id", table_name="stored_files")
    op.drop_table("stored_files")

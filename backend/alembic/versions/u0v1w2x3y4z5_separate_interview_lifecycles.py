"""separate interview lifecycle, recording, AI analysis, and human review

Revision ID: u0v1w2x3y4z5
Revises: t9u0v1w2x3y4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "u0v1w2x3y4z5"
down_revision = "t9u0v1w2x3y4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("interviews", sa.Column("lifecycle_state", sa.String(), nullable=False, server_default="scheduled"))
    op.add_column("interviews", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("end_reason", sa.Text(), nullable=True))
    op.add_column("interviews", sa.Column("recording_session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("interviews", sa.Column("recording_owner_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("interviews", sa.Column("recording_state", sa.String(), nullable=False, server_default="idle"))
    op.add_column("interviews", sa.Column("recording_reservation_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("recording_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("recording_chunks", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("interviews", sa.Column("recording_delete_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("ai_analysis_status", sa.String(), nullable=False, server_default="pending"))
    op.add_column("interviews", sa.Column("ai_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("interviews", sa.Column("ai_analysis_error", sa.Text(), nullable=True))
    op.add_column("interviews", sa.Column("ai_analysis_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("interviews", sa.Column("ai_analysis_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("ai_analysis_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("final_decision_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("interviews", sa.Column("final_decision_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interviews", sa.Column("notes_revealed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_interviews_recording_owner_id_tenant", "interviews", "users", ["tenant_id", "recording_owner_id"], ["tenant_id", "id"])
    op.create_foreign_key("fk_interviews_final_decision_by_tenant", "interviews", "users", ["tenant_id", "final_decision_by"], ["tenant_id", "id"])

    op.add_column("interview_panels", sa.Column("live_notes", sa.Text(), nullable=True))
    op.add_column("interview_panels", sa.Column("note_supplements", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("interview_panels", sa.Column("notes_frozen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interview_panels", sa.Column("human_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("interview_panels", sa.Column("human_comments", sa.Text(), nullable=True))
    op.add_column("interview_panels", sa.Column("human_recommendation", sa.String(), nullable=True))
    op.add_column("interview_panels", sa.Column("human_review_submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interview_panels", sa.Column("human_review_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interview_panels", sa.Column("human_review_reminder_sent_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE interviews SET lifecycle_state = CASE WHEN status::text = 'scheduled' THEN 'scheduled' WHEN status::text = 'in_progress' THEN 'in_progress' WHEN status::text IN ('analyzing', 'completed') THEN 'ended' ELSE status::text END")


def downgrade():
    for name in [
        "human_review_reminder_sent_at", "human_review_updated_at",
        "human_review_submitted_at", "human_recommendation", "human_comments",
        "human_scores", "notes_frozen_at", "note_supplements", "live_notes",
    ]:
        op.drop_column("interview_panels", name)
    op.drop_constraint("fk_interviews_final_decision_by_tenant", "interviews", type_="foreignkey")
    op.drop_constraint("fk_interviews_recording_owner_id_tenant", "interviews", type_="foreignkey")
    for name in [
        "notes_revealed_at", "final_decision_at", "final_decision_by",
        "ai_analysis_completed_at", "ai_analysis_started_at", "ai_analysis_version",
        "ai_analysis_error", "ai_analysis", "ai_analysis_status",
        "recording_delete_after", "recording_chunks", "recording_heartbeat_at",
        "recording_reservation_expires_at", "recording_state", "recording_owner_id",
        "recording_session_id", "end_reason", "ended_at", "lifecycle_state",
    ]:
        op.drop_column("interviews", name)

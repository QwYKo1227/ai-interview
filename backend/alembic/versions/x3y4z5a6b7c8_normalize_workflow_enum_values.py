"""normalize legacy workflow enum values

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
"""

from alembic import op


revision = "x3y4z5a6b7c8"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


ENUM_VALUE_RENAMES = {
    "workflowstatus": (
        ("DRAFT", "draft"),
        ("PUBLISHED", "published"),
        ("ARCHIVED", "archived"),
    ),
    "workflowexecutionstatus": (
        ("PENDING", "pending"),
        ("RUNNING", "running"),
        ("COMPLETED", "completed"),
        ("FAILED", "failed"),
        ("CANCELLED", "cancelled"),
    ),
    "nodetype": (
        ("START", "start"),
        ("END", "end"),
        ("LLM", "llm"),
        ("CONDITION", "condition"),
        ("TOOL", "tool"),
        ("HTTP_REQUEST", "http_request"),
        ("EMAIL", "email"),
        ("DATABASE", "database"),
        ("CODE", "code"),
        ("VARIABLE", "variable"),
        ("LOOP", "loop"),
        ("PARALLEL", "parallel"),
        ("HUMAN_INPUT", "human_input"),
    ),
}


def _rename_legacy_execution_type() -> None:
    op.execute(
        """
        DO $migration$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'executionstatus'
            ) AND NOT EXISTS (
                SELECT 1
                FROM pg_type
                WHERE typname = 'workflowexecutionstatus'
            ) THEN
                ALTER TYPE executionstatus RENAME TO workflowexecutionstatus;
            ELSIF EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'executionstatus'
            ) AND EXISTS (
                SELECT 1
                FROM pg_type
                WHERE typname = 'workflowexecutionstatus'
            ) THEN
                RAISE EXCEPTION
                    'both executionstatus and workflowexecutionstatus exist';
            END IF;
        END
        $migration$;
        """
    )


def _rename_enum_value(enum_type: str, old_value: str, new_value: str) -> None:
    op.execute(
        f"""
        DO $migration$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type type
                JOIN pg_enum enum ON enum.enumtypid = type.oid
                WHERE type.typname = '{enum_type}'
                  AND enum.enumlabel = '{old_value}'
            ) THEN
                IF EXISTS (
                    SELECT 1
                    FROM pg_type type
                    JOIN pg_enum enum ON enum.enumtypid = type.oid
                    WHERE type.typname = '{enum_type}'
                      AND enum.enumlabel = '{new_value}'
                ) THEN
                    RAISE EXCEPTION
                        'enum type {enum_type} contains both {old_value} and {new_value}';
                END IF;
                ALTER TYPE {enum_type}
                    RENAME VALUE '{old_value}' TO '{new_value}';
            END IF;
        END
        $migration$;
        """
    )


def upgrade() -> None:
    _rename_legacy_execution_type()
    for enum_type, renames in ENUM_VALUE_RENAMES.items():
        for old_value, new_value in renames:
            _rename_enum_value(enum_type, old_value, new_value)


def downgrade() -> None:
    # This migration repairs legacy schema drift. Reintroducing the uppercase
    # values would make the schema incompatible with the application models.
    pass

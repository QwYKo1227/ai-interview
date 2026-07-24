from dataclasses import dataclass

import sqlalchemy as sa
from alembic.autogenerate import comparators, renderers
from alembic.operations import ops

from app.models.tenant_constraints import TenantForeignKeyConstraint


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@dataclass(frozen=True)
class TenantForeignKeyDefinition:
    source_schema: str | None
    source_table: str
    name: str
    source_columns: tuple[str, ...]
    target_schema: str | None
    target_table: str
    target_columns: tuple[str, ...]
    ondelete: str | None
    onupdate: str | None
    deferrable: bool | None
    initially: str | None

    @classmethod
    def from_constraint(cls, constraint: TenantForeignKeyConstraint):
        first_target_table = constraint.elements[0].column.table
        return cls(
            source_schema=constraint.table.schema,
            source_table=constraint.table.name,
            name=constraint.name,
            source_columns=tuple(
                foreign_key.parent.name for foreign_key in constraint.elements
            ),
            target_schema=first_target_table.schema,
            target_table=first_target_table.name,
            target_columns=tuple(
                foreign_key.column.name for foreign_key in constraint.elements
            ),
            ondelete=constraint.ondelete,
            onupdate=constraint.onupdate,
            deferrable=constraint.deferrable,
            initially=constraint.initially,
        )


class SyncTenantForeignKeySetNullColumnsOp(ops.MigrateOperation):
    def __init__(self, definition, previous_columns, desired_columns):
        self.definition = definition
        self.previous_columns = tuple(previous_columns)
        self.desired_columns = tuple(desired_columns)

    def reverse(self):
        return SyncTenantForeignKeySetNullColumnsOp(
            self.definition,
            self.desired_columns,
            self.previous_columns,
        )


def _qualified_name(schema: str | None, name: str) -> str:
    if schema:
        return f"{_quote(schema)}.{_quote(name)}"
    return _quote(name)


def _create_constraint_ddl(
    definition: TenantForeignKeyDefinition,
    set_null_columns: tuple[str, ...],
) -> str:
    source_columns = ", ".join(_quote(column) for column in definition.source_columns)
    target_columns = ", ".join(_quote(column) for column in definition.target_columns)
    ddl = (
        f"ALTER TABLE {_qualified_name(definition.source_schema, definition.source_table)} "
        f"ADD CONSTRAINT {_quote(definition.name)} "
        f"FOREIGN KEY ({source_columns}) "
        f"REFERENCES {_qualified_name(definition.target_schema, definition.target_table)} "
        f"({target_columns})"
    )
    if definition.ondelete:
        ddl += f" ON DELETE {definition.ondelete}"
        if set_null_columns:
            ddl += " (" + ", ".join(
                _quote(column) for column in set_null_columns
            ) + ")"
    if definition.onupdate:
        ddl += f" ON UPDATE {definition.onupdate}"
    if definition.deferrable is not None:
        ddl += " DEFERRABLE" if definition.deferrable else " NOT DEFERRABLE"
    if definition.initially:
        ddl += f" INITIALLY {definition.initially}"
    return ddl


@renderers.dispatch_for(SyncTenantForeignKeySetNullColumnsOp)
def _render_sync_set_null_columns(_autogen_context, operation):
    definition = operation.definition
    drop_ddl = (
        f"ALTER TABLE {_qualified_name(definition.source_schema, definition.source_table)} "
        f"DROP CONSTRAINT {_quote(definition.name)}"
    )
    create_ddl = _create_constraint_ddl(
        definition, operation.desired_columns
    )
    return [f"op.execute({drop_ddl!r})", f"op.execute({create_ddl!r})"]


def _metadata_tenant_foreign_keys(metadata):
    return {
        (table.schema, table.name, constraint.name): constraint
        for table in metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, TenantForeignKeyConstraint)
    }


@comparators.dispatch_for("schema")
def compare_tenant_foreign_key_set_null_columns(
    autogen_context, upgrade_ops, _schemas
):
    if autogen_context.dialect.name != "postgresql":
        return

    metadata_constraints = _metadata_tenant_foreign_keys(autogen_context.metadata)
    if not metadata_constraints:
        return

    rows = autogen_context.connection.execute(
        sa.text(
            "SELECT namespace.nspname AS schema_name, child.relname AS table_name, "
            "       constraint_record.conname AS constraint_name, "
            "       COALESCE(ARRAY("
            "         SELECT attribute.attname "
            "         FROM unnest(constraint_record.confdelsetcols) "
            "              WITH ORDINALITY AS selected(attnum, position) "
            "         JOIN pg_attribute attribute "
            "           ON attribute.attrelid = constraint_record.conrelid "
            "          AND attribute.attnum = selected.attnum "
            "         ORDER BY selected.position"
            "       ), ARRAY[]::name[]) AS set_null_columns "
            "FROM pg_constraint constraint_record "
            "JOIN pg_class child ON child.oid = constraint_record.conrelid "
            "JOIN pg_namespace namespace ON namespace.oid = child.relnamespace "
            "WHERE constraint_record.contype = 'f'"
        )
    ).mappings()
    default_schema = autogen_context.dialect.default_schema_name
    database_columns = {
        (
            None if row["schema_name"] == default_schema else row["schema_name"],
            row["table_name"],
            row["constraint_name"],
        ): tuple(row["set_null_columns"])
        for row in rows
    }

    for key, constraint in metadata_constraints.items():
        desired_columns = constraint.postgresql_set_null_columns
        previous_columns = database_columns.get(key, ())
        if previous_columns == desired_columns:
            continue
        upgrade_ops.ops.append(
            SyncTenantForeignKeySetNullColumnsOp(
                TenantForeignKeyDefinition.from_constraint(constraint),
                previous_columns,
                desired_columns,
            )
        )


def render_tenant_constraint(type_, constraint, autogen_context):
    if type_ != "foreign_key" or not isinstance(
        constraint, TenantForeignKeyConstraint
    ):
        return False
    if not constraint.postgresql_set_null_columns:
        return False

    autogen_context.imports.add(
        "from app.models.tenant_constraints import TenantForeignKeyConstraint"
    )
    source_columns = [
        foreign_key.parent.name for foreign_key in constraint.elements
    ]
    target_columns = [
        foreign_key.target_fullname for foreign_key in constraint.elements
    ]
    options = [f"name={constraint.name!r}"]
    if constraint.ondelete:
        options.append(f"ondelete={constraint.ondelete!r}")
    options.append(
        "postgresql_set_null_columns="
        f"{constraint.postgresql_set_null_columns!r}"
    )
    return (
        f"TenantForeignKeyConstraint({source_columns!r}, {target_columns!r}, "
        + ", ".join(options)
        + ")"
    )

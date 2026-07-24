from collections.abc import Iterable

from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.ext.compiler import compiles


POSTGRESQL_SET_NULL_COLUMNS_INFO_KEY = "postgresql_set_null_columns"


class TenantForeignKeyConstraint(ForeignKeyConstraint):
    """A tenant FK with machine-readable PostgreSQL partial SET NULL semantics."""

    inherit_cache = True

    def __init__(
        self,
        columns,
        refcolumns,
        *,
        postgresql_set_null_columns: Iterable[str] = (),
        **kwargs,
    ):
        set_null_columns = tuple(postgresql_set_null_columns)
        constrained_columns = tuple(
            column if isinstance(column, str) else column.name for column in columns
        )
        unknown_columns = set(set_null_columns) - set(constrained_columns)
        if unknown_columns:
            raise ValueError(
                "postgresql_set_null_columns must be constrained columns: "
                + ", ".join(sorted(unknown_columns))
            )
        if set_null_columns and str(kwargs.get("ondelete", "")).upper() != "SET NULL":
            raise ValueError(
                "postgresql_set_null_columns requires ondelete='SET NULL'"
            )

        info = dict(kwargs.pop("info", None) or {})
        existing = tuple(info.get(POSTGRESQL_SET_NULL_COLUMNS_INFO_KEY, ()))
        if existing and existing != set_null_columns:
            raise ValueError("conflicting PostgreSQL SET NULL column metadata")
        info[POSTGRESQL_SET_NULL_COLUMNS_INFO_KEY] = set_null_columns
        super().__init__(columns, refcolumns, info=info, **kwargs)

    @property
    def postgresql_set_null_columns(self) -> tuple[str, ...]:
        return tuple(self.info[POSTGRESQL_SET_NULL_COLUMNS_INFO_KEY])


def _base_foreign_key_ddl(element, compiler, **kwargs) -> str:
    return compiler.visit_foreign_key_constraint(element, **kwargs)


def _without_unsafe_composite_set_null(ddl: str, element) -> str:
    if not element.postgresql_set_null_columns:
        return ddl
    return ddl.replace(" ON DELETE SET NULL", "", 1)


@compiles(TenantForeignKeyConstraint)
def _compile_default_tenant_foreign_key(element, compiler, **kwargs):
    ddl = _base_foreign_key_ddl(element, compiler, **kwargs)
    return _without_unsafe_composite_set_null(ddl, element)


@compiles(TenantForeignKeyConstraint, "postgresql")
def _compile_postgresql_tenant_foreign_key(element, compiler, **kwargs):
    ddl = _base_foreign_key_ddl(element, compiler, **kwargs)
    set_null_columns = element.postgresql_set_null_columns
    if not set_null_columns:
        return ddl
    quoted_columns = ", ".join(
        compiler.preparer.quote(column) for column in set_null_columns
    )
    marker = " ON DELETE SET NULL"
    if marker not in ddl:
        raise ValueError("partial SET NULL constraint is missing ON DELETE SET NULL")
    return ddl.replace(marker, f"{marker} ({quoted_columns})", 1)


@compiles(TenantForeignKeyConstraint, "sqlite")
def _compile_sqlite_tenant_foreign_key(element, compiler, **_kwargs):
    set_null_columns = element.postgresql_set_null_columns
    if not set_null_columns:
        return _base_foreign_key_ddl(element, compiler)

    elements_by_local_column = {
        foreign_key.parent.name: foreign_key for foreign_key in element.elements
    }
    selected = [elements_by_local_column[column] for column in set_null_columns]
    target_tables = {foreign_key.column.table for foreign_key in selected}
    if len(target_tables) != 1:
        raise ValueError("SQLite SET NULL fallback requires one target table")

    constraint_prefix = ""
    if element.name:
        constraint_prefix = (
            f"CONSTRAINT {compiler.preparer.format_constraint(element)} "
        )
    local_columns = ", ".join(
        compiler.preparer.quote(foreign_key.parent.name)
        for foreign_key in selected
    )
    target_table = compiler.preparer.format_table(next(iter(target_tables)))
    target_columns = ", ".join(
        compiler.preparer.quote(foreign_key.column.name)
        for foreign_key in selected
    )
    return (
        f"{constraint_prefix}FOREIGN KEY({local_columns}) "
        f"REFERENCES {target_table} ({target_columns}) ON DELETE SET NULL"
    )

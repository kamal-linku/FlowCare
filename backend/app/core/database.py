from sqlalchemy import MetaData, create_engine, inspect, literal
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def migrate_sqlite_schema(database_engine=engine):
    if database_engine.dialect.name != "sqlite":
        return

    preparer = database_engine.dialect.identifier_preparer

    with database_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            inspector = inspect(connection)
            existing_tables = set(inspector.get_table_names())
            connection.commit()
            with connection.begin():
                for table in Base.metadata.sorted_tables:
                    if table.name not in existing_tables:
                        continue

                    existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
                    for column in table.columns:
                        if column.name in existing_columns:
                            continue
                        if column.primary_key:
                            raise RuntimeError(
                                f"Cannot automatically migrate SQLite primary key column "
                                f"{table.name}.{column.name}."
                            )

                        column_sql = (
                            f"ALTER TABLE {preparer.quote(table.name)} "
                            f"ADD COLUMN {preparer.quote(column.name)} "
                            f"{column.type.compile(dialect=database_engine.dialect)}"
                        )
                        default = column.server_default.arg if column.server_default is not None else None
                        if default is None and column.default is not None and not callable(column.default.arg):
                            default = column.default.arg
                        if default is not None:
                            rendered_default = literal(default, type_=column.type).compile(
                                dialect=database_engine.dialect,
                                compile_kwargs={"literal_binds": True},
                            )
                            column_sql += f" DEFAULT {rendered_default}"
                            if not column.nullable:
                                column_sql += " NOT NULL"
                        connection.exec_driver_sql(column_sql)
                        existing_columns.add(column.name)

                registration_table = Base.metadata.tables.get("registration_sessions")
                if registration_table is not None and "registration_sessions" in existing_tables:
                    unique_constraints = inspector.get_unique_constraints("registration_sessions")
                    if any(
                        constraint.get("column_names") == ["session_date"]
                        for constraint in unique_constraints
                    ):
                        migration_metadata = MetaData()
                        Base.metadata.tables["departments"].to_metadata(migration_metadata)
                        migrated_table = registration_table.to_metadata(
                            migration_metadata,
                            name="registration_sessions__migration",
                        )
                        connection.execute(CreateTable(migrated_table))
                        migrated_columns = {item["name"] for item in inspector.get_columns("registration_sessions")}
                        for column in registration_table.columns:
                            if column.name not in migrated_columns or column.nullable or column.default is None:
                                continue
                            default_value = column.default.arg
                            if callable(default_value):
                                default_value = default_value(None)
                            rendered_default = literal(default_value, type_=column.type).compile(
                                dialect=database_engine.dialect,
                                compile_kwargs={"literal_binds": True},
                            )
                            connection.exec_driver_sql(
                                f"UPDATE {preparer.quote(registration_table.name)} "
                                f"SET {preparer.quote(column.name)} = {rendered_default} "
                                f"WHERE {preparer.quote(column.name)} IS NULL"
                            )
                        migrated_columns = [
                            column.name for column in registration_table.columns
                            if column.name in migrated_columns
                        ]
                        quoted_columns = ", ".join(preparer.quote(name) for name in migrated_columns)
                        connection.exec_driver_sql(
                            f"INSERT INTO {preparer.quote(migrated_table.name)} ({quoted_columns}) "
                            f"SELECT {quoted_columns} FROM {preparer.quote(registration_table.name)}"
                        )
                        connection.exec_driver_sql(
                            f"DROP TABLE {preparer.quote(registration_table.name)}"
                        )
                        connection.exec_driver_sql(
                            f"ALTER TABLE {preparer.quote(migrated_table.name)} "
                            f"RENAME TO {preparer.quote(registration_table.name)}"
                        )

                for table in Base.metadata.sorted_tables:
                    if table.name in existing_tables:
                        for index in table.indexes:
                            index.create(bind=connection, checkfirst=True)
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

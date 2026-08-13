from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from config import settings

# Create engine with pool options only for DBs that support them (e.g., Postgres/asyncpg).
_db_url = make_url(settings.DATABASE_URL)
if _db_url.drivername.startswith("sqlite"):
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def create_tables():
    try:
        async with engine.begin() as conn:
            def _inspect_tables(sync_conn):
                return set(inspect(sync_conn).get_table_names())

            existing_tables = await conn.run_sync(_inspect_tables)

            for table in Base.metadata.sorted_tables:
                if table.name in existing_tables:
                    continue

                try:
                    await conn.run_sync(lambda sync_conn, tbl=table: tbl.create(bind=sync_conn, checkfirst=True))
                except IntegrityError as exc:
                    msg = str(exc).lower()
                    if "duplicate key value violates unique constraint" in msg and "pg_type_typname_nsp_index" in msg:
                        print("Schema already initialized; continuing startup without re-creating existing tables.")
                        continue
                    raise
    except IntegrityError as exc:
        msg = str(exc).lower()
        if "duplicate key value violates unique constraint" in msg and "pg_type_typname_nsp_index" in msg:
            print("Schema already initialized; continuing startup without re-creating existing tables.")
        else:
            raise

    async with engine.begin() as conn:
        def _get_table_columns(sync_conn):
            inspector = inspect(sync_conn)
            return {
                table_name: {column["name"] for column in inspector.get_columns(table_name)}
                for table_name in inspector.get_table_names()
            }

        table_columns = await conn.run_sync(_get_table_columns)

        if "orders" in table_columns and "status_details" not in table_columns["orders"]:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS status_details TEXT"))

        if "orders" in table_columns and "error_message" not in table_columns["orders"]:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS error_message TEXT"))

        if "orders" in table_columns and "notes" not in table_columns["orders"]:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS notes TEXT"))

        if "services" in table_columns and "is_recommended" not in table_columns["services"]:
            await conn.execute(text(
                "ALTER TABLE services ADD COLUMN IF NOT EXISTS is_recommended BOOLEAN NOT NULL DEFAULT false"
            ))

        await conn.execute(text("CREATE SEQUENCE IF NOT EXISTS order_number_seq START 10001"))

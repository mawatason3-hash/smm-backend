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
            inspector = await conn.run_sync(inspect)
            existing_tables = set(inspector.get_table_names())

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
        await conn.execute(text("CREATE SEQUENCE IF NOT EXISTS order_number_seq START 10001"))
        await conn.execute(text(
            "ALTER TABLE services ADD COLUMN IF NOT EXISTS is_recommended BOOLEAN NOT NULL DEFAULT false"
        ))

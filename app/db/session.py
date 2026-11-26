import os
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

load_dotenv()

raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./game.db").strip().strip('"').strip("'")

if raw_url.startswith("postgres://"):
    raw_url = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_url.startswith("postgresql://") and not raw_url.startswith("postgresql+asyncpg://"):
    raw_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

connect_args = {}
if raw_url.startswith("postgresql+asyncpg://"):
    parts = urlsplit(raw_url)
    # asyncpg가 싫어할 수 있는 sslmode 등 쿼리 옵션 정리
    filtered_query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in {"sslmode", "channel_binding"}
    ]
    raw_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered_query), parts.fragment))
    connect_args = {
        "ssl": "require",
        "statement_cache_size": 0,
    }

engine_kwargs = {"echo": False, "connect_args": connect_args}
if raw_url.startswith("postgresql+asyncpg://"):
    engine_kwargs.update({"pool_pre_ping": True, "pool_recycle": 300, "pool_size": 10, "max_overflow": 20})

engine = create_async_engine(raw_url, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# .env 파일이 존재할 경우 환경 변수 자동 로드
load_dotenv()

# 로컬 테스트 기본값으로 sqlite 지원, 배포 시 환경 변수 DATABASE_URL (postgresql+asyncpg://...) 사용
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./game.db").strip().strip('"').strip("'")

# Render나 Supabase에서 postgres:// 로 들어올 경우 호환 처리
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

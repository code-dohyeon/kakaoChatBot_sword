from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.core.config import config
from app.routers.kakao_router import router as kakao_router
from app.routers.extra_router import router as extra_router
from app.db.session import engine, Base

app = FastAPI(
    title="검 강화 대장간 스킬 서버",
    description="카카오톡 챗봇 연동 검 강화 로그라이크 게임 API",
    version="0.1.0"
)

# assets 정적 파일 마운트 (/assets/upgrade_**.png)
assets_path = Path(__file__).parent.parent / "assets"
assets_path.mkdir(exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

@app.on_event("startup")
async def startup_event():
    # SQLite/PostgreSQL 테이블 생성
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

app.include_router(kakao_router)
app.include_router(extra_router)

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "sword_upgrade_kakao",
        "max_round": config.rules.get("max_round", 10)
    }


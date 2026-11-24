import time
import asyncio
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import config
from app.routers.kakao_router import router as kakao_router
from app.routers.extra_router import router as extra_router
from app.db.session import engine, Base
from app.utils.kakao_builder import KakaoResponseBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("skill_server")

app = FastAPI(
    title="검 강화 대장간 스킬 서버",
    description="카카오톡 챗봇 연동 검 강화 로그라이크 게임 API",
    version="0.1.0"
)

# assets 정적 파일 마운트 (/assets/upgrade_**.png)
assets_path = Path(__file__).parent.parent / "assets"
assets_path.mkdir(exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

# 5초 타임아웃 방어 및 지연 모니터링 미들웨어
@app.middleware("http")
async def timeout_and_latency_middleware(request: Request, call_next):
    start_time = time.time()
    path = request.url.path

    # 카카오 API 요청인 경우 4.5초 타임아웃 가드 적용 (카카오 i 오픈빌더 타임아웃 5초 대비)
    if path.startswith("/api/kakao"):
        try:
            response = await asyncio.wait_for(call_next(request), timeout=4.5)
            duration = time.time() - start_time
            if duration > 1.0:
                logger.warning(f"⚠️ [SLOWNESS WARNING] {path} took {duration:.3f}s")
            return response
        except asyncio.TimeoutError:
            logger.error(f"🚨 [TIMEOUT GUARD] {path} exceeded 4.5s limit!")
            return JSONResponse(
                status_code=200,
                content=KakaoResponseBuilder.simple_text(
                    "서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."
                )
            )
        except Exception as e:
            logger.error(f"❌ [UNHANDLED ERROR] {path}: {str(e)}", exc_info=True)
            return JSONResponse(
                status_code=200,
                content=KakaoResponseBuilder.simple_text(
                    "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                )
            )

    return await call_next(request)

@app.on_event("startup")
async def startup_event():
    # SQLite/PostgreSQL 테이블 생성
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 기존 DB 테이블에 round_sales_gold 컬럼이 없을 경우 자동 추가
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE runs ADD COLUMN round_sales_gold INTEGER DEFAULT 0"))
            logger.info("✅ Successfully added 'round_sales_gold' column to runs table.")
        except Exception:
            pass  # 이미 컬럼이 존재하면 통과

app.include_router(kakao_router)
app.include_router(extra_router)

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "sword_upgrade_kakao",
        "max_round": config.rules.get("max_round", 10)
    }

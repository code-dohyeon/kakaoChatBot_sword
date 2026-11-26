import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc
from app.models.game import User, Run, Ranking, RunHistory, EnhanceLog
from app.core.config import config
from app.services.game_engine import GameEngine
from typing import Optional, Dict, Any, Tuple

class RunService:
    _user_id_cache: Dict[str, int] = {}

    @classmethod
    async def get_user_id_fast(cls, db: AsyncSession, kakao_user_key: str) -> int:
        if kakao_user_key in cls._user_id_cache:
            return cls._user_id_cache[kakao_user_key]
        user = await cls.get_or_create_user(db, kakao_user_key)
        cls._user_id_cache[kakao_user_key] = user.id
        return user.id

    @classmethod
    async def get_or_create_user(cls, db: AsyncSession, kakao_user_key: str) -> User:
        stmt = select(User).where(User.kakao_user_key == kakao_user_key)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if not user:
            user = User(kakao_user_key=kakao_user_key)
            db.add(user)
            await db.flush()

            # 랭킹 기본 행 생성 (단일 트랜잭션으로 커밋)
            ranking = Ranking(user_id=user.id, best_round=1, best_level=0)
            db.add(ranking)
            await db.commit()
        cls._user_id_cache[kakao_user_key] = user.id
        return user

    @staticmethod
    async def get_active_run(db: AsyncSession, user_id: int) -> Optional[Run]:
        stmt = select(Run).where(Run.user_id == user_id, Run.status == "playing")
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @classmethod
    async def start_new_run(cls, db: AsyncSession, user_id: int) -> Run:
        stmt = select(Run).where(Run.user_id == user_id)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        # 라운드 1 기본 검 3개 지급
        starting_swords = [
            {"id": i + 1, "type": "normal", "level": 0}
            for i in range(config.rules.get("swords_per_round", 3))
        ]

        if existing:
            existing.round = 1
            existing.gold = config.rules.get("starting_gold", 0)
            existing.round_sales_gold = 0
            existing.relic_points = 0
            existing.swords = starting_swords
            existing.items = []
            existing.relics = []
            existing.shield = 0
            existing.boost = 0
            existing.destroyed_count = 0
            existing.last_destroyed_sword = None
            existing.status = "playing"
            await db.commit()
            return existing

        new_run = Run(
            user_id=user_id,
            round=1,
            gold=config.rules.get("starting_gold", 0),
            round_sales_gold=0,
            relic_points=0,
            swords=starting_swords,
            items=[],
            relics=[],
            shield=0,
            boost=0,
            destroyed_count=0,
            status="playing"
        )
        db.add(new_run)
        await db.commit()
        return new_run

    @classmethod
    async def advance_round(cls, db: AsyncSession, run: Run) -> Tuple[bool, str]:
        """라운드 납품/마감 처리 (해당 라운드 검 판매 수익 기준)"""
        target_gold = GameEngine.get_target_gold_for_round(run.round)
        sales_gold = getattr(run, "round_sales_gold", 0) or 0

        if sales_gold < target_gold:
            # 실패: 게임 오버
            run.status = "failed"
            await cls._record_run_end(db, run, "failed")
            await db.commit()
            return False, f"이번 라운드 검 판매 수익({sales_gold:,}G)이 목표 골드({target_gold:,}G)에 부족하여 납품에 실패했습니다. (소지금: {run.gold:,}G)"

        # 10라운드 클리어 체크
        if run.round >= config.rules.get("max_round", 10):
            run.status = "cleared"
            await cls._record_run_end(db, run, "cleared")
            await db.commit()
            return True, "축하합니다! 10라운드 최종 납품에 성공하여 게임을 완주(클리어)했습니다!"

        # 다음 라운드 진행
        run.round += 1
        run.round_sales_gold = 0 # 다음 라운드 판매 수익 초기화
        # 검 지급 (기존 검에 누적)
        current_swords = list(run.swords or [])
        start_id = max([s.get("id", 0) for s in current_swords], default=0) + 1
        for i in range(config.rules.get("swords_per_round", 3)):
            current_swords.append({"id": start_id + i, "type": "normal", "level": 0})
        run.swords = current_swords

        # 수호의 가호 유물 보유 시 방어막 1회 충전
        if "guardians_grace" in (run.relics or []):
            run.shield = 1

        await db.commit()
        return True, f"납품 완료! {run.round}라운드가 시작되었습니다. 새로운 기본 검 {config.rules.get('swords_per_round', 3)}개가 추가되었습니다."

    @staticmethod
    async def _record_run_end(db: AsyncSession, run: Run, result: str):
        # 최고 강화 레벨 계산
        best_level = max([s.get("level", 0) for s in (run.swords or [])], default=0)
        history = RunHistory(
            user_id=run.user_id,
            best_level=best_level,
            reached_round=run.round,
            destroyed_count=run.destroyed_count or 0,
            relics=run.relics or [],
            result=result
        )
        db.add(history)

        # 랭킹 갱신
        stmt = select(Ranking).where(Ranking.user_id == run.user_id)
        res = await db.execute(stmt)
        ranking = res.scalar_one_or_none()
        if ranking:
            if run.round > ranking.best_round or (run.round == ranking.best_round and best_level > ranking.best_level):
                ranking.best_round = run.round
                ranking.best_level = best_level

    @staticmethod
    async def add_enhance_log(
        db: AsyncSession,
        user_id: int,
        run_id: int,
        sword_type: str,
        from_level: int,
        to_level: int,
        result: str
    ):
        """
        강화 로그 기록:
        - 역대 최고 강화 기록 1개 보존 (최고 기록 갱신 시 자동 반영)
        - 최근 일반 강화 로그 20개만 유지 (오래된 로그 자동 삭제)
        """
        # 1. 새 로그 추가
        new_log = EnhanceLog(
            user_id=user_id,
            run_id=run_id,
            sword_type=sword_type,
            from_level=from_level,
            to_level=to_level,
            result=result
        )
        db.add(new_log)

        # DB 왕복 최소화를 위해 약 20% 확률(5회당 1회)로만 오래된 로그 정리 실행
        if random.random() >= 0.20:
            return

        await db.flush()

        # 2. 해당 유저의 역대 최고 강화 레벨 로그 ID 확인
        best_stmt = (
            select(EnhanceLog.id)
            .where(EnhanceLog.user_id == user_id)
            .order_by(desc(EnhanceLog.to_level), desc(EnhanceLog.created_at))
            .limit(1)
        )
        best_res = await db.execute(best_stmt)
        best_log_id = best_res.scalar_one_or_none()

        # 3. 최고 기록(best_log_id)을 제외한 최신 20개 로그의 ID 조회
        recent_stmt = (
            select(EnhanceLog.id)
            .where(EnhanceLog.user_id == user_id)
            .where(EnhanceLog.id != best_log_id)
            .order_by(desc(EnhanceLog.created_at))
            .limit(20)
        )
        recent_res = await db.execute(recent_stmt)
        keep_ids = set(recent_res.scalars().all())
        if best_log_id:
            keep_ids.add(best_log_id)

        # 4. 보존할 ID 목록에 없는 오래된 로그 일괄 삭제
        if keep_ids:
            del_stmt = (
                delete(EnhanceLog)
                .where(EnhanceLog.user_id == user_id)
                .where(~EnhanceLog.id.in_(keep_ids))
            )
            await db.execute(del_stmt)

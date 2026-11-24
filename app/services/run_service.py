from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.game import User, Run, Ranking, RunHistory, EnhanceLog
from app.core.config import config
from app.services.game_engine import GameEngine
from typing import Optional, Dict, Any, Tuple

class RunService:
    @staticmethod
    async def get_or_create_user(db: AsyncSession, kakao_user_key: str) -> User:
        stmt = select(User).where(User.kakao_user_key == kakao_user_key)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if not user:
            user = User(kakao_user_key=kakao_user_key)
            db.add(user)
            await db.commit()
            await db.refresh(user)

            # 랭킹 기본 행 생성
            ranking = Ranking(user_id=user.id, best_round=1, best_level=0)
            db.add(ranking)
            await db.commit()
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
        if existing:
            await db.delete(existing)
            await db.commit()

        # 라운드 1 기본 검 3개 지급
        starting_swords = [
            {"id": i + 1, "type": "normal", "level": 0}
            for i in range(config.rules.get("swords_per_round", 3))
        ]

        new_run = Run(
            user_id=user_id,
            round=1,
            gold=config.rules.get("starting_gold", 0),
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
        await db.refresh(new_run)
        return new_run

    @classmethod
    async def advance_round(cls, db: AsyncSession, run: Run) -> Tuple[bool, str]:
        """라운드 납품/마감 처리"""
        target_gold = GameEngine.get_target_gold_for_round(run.round)
        if run.gold < target_gold:
            # 실패: 게임 오버
            run.status = "failed"
            await cls._record_run_end(db, run, "failed")
            await db.commit()
            return False, f"목표 골드({target_gold:,}G)가 부족하여 납품에 실패했습니다. (보유: {run.gold:,}G)"

        # 10라운드 클리어 체크
        if run.round >= config.rules.get("max_round", 10):
            run.status = "cleared"
            await cls._record_run_end(db, run, "cleared")
            await db.commit()
            return True, "축하합니다! 10라운드 최종 납품에 성공하여 게임을 완주(클리어)했습니다!"

        # 다음 라운드 진행
        run.round += 1
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

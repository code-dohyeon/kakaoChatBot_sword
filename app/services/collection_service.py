from typing import List, Tuple, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from app.models.game import UserMeta
from app.core.config import config

# 도감 완성도 계산용 기준 레벨 (각 검 타입별 0~15강 = 16개씩)
MAX_CATALOG_SWORD_LEVEL = 15


class CollectionService:
    @staticmethod
    async def get_or_create_meta(db: AsyncSession, user_id: int) -> UserMeta:
        stmt = select(UserMeta).where(UserMeta.user_id == user_id)
        res = await db.execute(stmt)
        meta = res.scalar_one_or_none()
        if not meta:
            meta = UserMeta(
                user_id=user_id,
                collected_swords=[],
                collected_relics=[],
                collected_events=[],
                unlocked_titles=[],
                equipped_title=None,
                stats={}
            )
            db.add(meta)
            await db.flush()
        return meta

    @staticmethod
    def calculate_completion(meta: UserMeta) -> Tuple[int, int, float]:
        """(수집 수, 전체 기준 수, 완성도 %) 반환"""
        sword_types = list(config.sword_types.keys())
        total_swords = len(sword_types) * (MAX_CATALOG_SWORD_LEVEL + 1)
        total_relics = len(config.relics)
        total_events = len(config.round_events)
        total_count = total_swords + total_relics + total_events

        # 기준 범위 내 수집된 검만 카운트 (15강 초과도 수집 리스트엔 남기되 % 계산은 cap)
        collected_swords = set(meta.collected_swords or [])
        valid_sword_cnt = 0
        for key in collected_swords:
            try:
                stype, lvl_str = key.split(":")
                if stype in config.sword_types and 0 <= int(lvl_str) <= MAX_CATALOG_SWORD_LEVEL:
                    valid_sword_cnt += 1
            except ValueError:
                pass

        collected_relic_cnt = len(set(meta.collected_relics or []) & set(config.relics.keys()))
        collected_event_cnt = len(set(meta.collected_events or []) & set(config.round_events.keys()))

        collected_count = valid_sword_cnt + collected_relic_cnt + collected_event_cnt
        percent = (collected_count / total_count * 100.0) if total_count > 0 else 0.0
        return collected_count, total_count, min(round(percent, 1), 100.0)

    @classmethod
    def _check_collection_achievements(cls, meta: UserMeta) -> List[str]:
        """도감 관련 업적/칭호 자동 해금 체크 후 새로 해금된 칭호명 리스트 반환"""
        unlocked = list(meta.unlocked_titles or [])
        newly_unlocked_names = []

        def unlock(ach_id: str):
            if ach_id not in unlocked and ach_id in config.achievements:
                unlocked.append(ach_id)
                newly_unlocked_names.append(config.achievements[ach_id]["title"])

        _, _, pct = cls.calculate_completion(meta)
        if pct >= 25.0:
            unlock("ach_32")  # 수집 입문
        if pct >= 50.0:
            unlock("ach_33")  # 수집가
        if pct >= 100.0:
            unlock("ach_34")  # 도감 마스터

        # 유물 7종 모두 수집
        if len(set(meta.collected_relics or []) & set(config.relics.keys())) >= len(config.relics):
            unlock("ach_31")  # 유물 수집가

        # 이벤트 6종 모두 경험
        if len(set(meta.collected_events or []) & set(config.round_events.keys())) >= len(config.round_events):
            unlock("ach_37")  # 모험가

        # 나뭇가지 +10, 꼬챙이 +10
        swords = set(meta.collected_swords or [])
        for key in swords:
            try:
                stype, lvl_str = key.split(":")
                lvl = int(lvl_str)
                if stype == "stick" and lvl >= 10:
                    unlock("ach_35")
                if stype == "skewer" and lvl >= 10:
                    unlock("ach_36")
            except ValueError:
                pass

        if newly_unlocked_names:
            meta.unlocked_titles = unlocked
            flag_modified(meta, "unlocked_titles")
        return newly_unlocked_names

    @classmethod
    async def register_sword(cls, db: AsyncSession, user_id: int, sword_type: str, level: int) -> Tuple[bool, List[str]]:
        """검 도감 등록. (is_new, 새로 해금된 칭호명 목록) 반환"""
        meta = await cls.get_or_create_meta(db, user_id)
        key = f"{sword_type}:{level}"
        swords = list(meta.collected_swords or [])
        is_new = key not in swords
        new_titles = []
        if is_new:
            swords.append(key)
            meta.collected_swords = swords
            flag_modified(meta, "collected_swords")
            new_titles = cls._check_collection_achievements(meta)
        return is_new, new_titles

    @classmethod
    async def register_relic(cls, db: AsyncSession, user_id: int, relic_id: str) -> Tuple[bool, List[str]]:
        """유물 도감 등록. (is_new, 새로 해금된 칭호명 목록) 반환"""
        meta = await cls.get_or_create_meta(db, user_id)
        relics = list(meta.collected_relics or [])
        is_new = relic_id not in relics
        new_titles = []
        if is_new:
            relics.append(relic_id)
            meta.collected_relics = relics
            flag_modified(meta, "collected_relics")
            new_titles = cls._check_collection_achievements(meta)
        return is_new, new_titles

    @classmethod
    async def register_event(cls, db: AsyncSession, user_id: int, event_id: str) -> Tuple[bool, List[str]]:
        """이벤트 도감 등록. (is_new, 새로 해금된 칭호명 목록) 반환"""
        meta = await cls.get_or_create_meta(db, user_id)
        events = list(meta.collected_events or [])
        is_new = event_id not in events
        new_titles = []
        if is_new:
            events.append(event_id)
            meta.collected_events = events
            flag_modified(meta, "collected_events")
            new_titles = cls._check_collection_achievements(meta)
        return is_new, new_titles

from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from app.models.game import UserMeta, Run
from app.core.config import config
from app.services.collection_service import CollectionService


class AchievementService:
    @staticmethod
    def _unlock(meta: UserMeta, ach_id: str, newly_unlocked: List[str]):
        unlocked = list(meta.unlocked_titles or [])
        if ach_id not in unlocked and ach_id in config.achievements:
            unlocked.append(ach_id)
            meta.unlocked_titles = unlocked
            flag_modified(meta, "unlocked_titles")
            newly_unlocked.append(config.achievements[ach_id]["title"])

    @classmethod
    async def on_enhance(
        cls,
        db: AsyncSession,
        user_id: int,
        run: Run,
        prev_level: int,
        to_level: int,
        result: str,
        details: Dict[str, Any],
    ) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        counters = dict(getattr(run, "meta_counters", None) or {})
        newly: List[str] = []

        if result in ("success", "great_success"):
            counters["win_streak"] = counters.get("win_streak", 0) + 1
            counters["destroy_streak"] = 0

            if result == "great_success":
                cls._unlock(meta, "ach_01", newly)
            if counters["win_streak"] >= 3:
                cls._unlock(meta, "ach_02", newly)
            if counters["win_streak"] >= 5:
                cls._unlock(meta, "ach_03", newly)
            if to_level >= 5:
                cls._unlock(meta, "ach_04", newly)
            if to_level >= 10:
                cls._unlock(meta, "ach_05", newly)
            if to_level >= 15:
                cls._unlock(meta, "ach_06", newly)
            if to_level >= 20:
                cls._unlock(meta, "ach_07", newly)
            if (to_level - prev_level) >= 3:
                cls._unlock(meta, "ach_08", newly)

            probs = details.get("probabilities") or {}
            if (probs.get("success", 1.0) + probs.get("great_success", 0.0)) <= 0.25:
                cls._unlock(meta, "ach_09", newly)

        elif result == "keep":
            counters["win_streak"] = 0
            counters["destroy_streak"] = 0
            if details.get("protected_by") == "protect_destroy":
                cls._unlock(meta, "ach_17", newly)

        elif result == "destroy":
            counters["win_streak"] = 0
            counters["destroy_streak"] = counters.get("destroy_streak", 0) + 1
            cls._unlock(meta, "ach_11", newly)
            if counters["destroy_streak"] >= 3:
                cls._unlock(meta, "ach_12", newly)
            if prev_level >= 10:
                cls._unlock(meta, "ach_13", newly)
            if prev_level >= 15:
                cls._unlock(meta, "ach_14", newly)
            if (run.destroyed_count or 0) >= 20:
                cls._unlock(meta, "ach_15", newly)

        run.meta_counters = counters
        flag_modified(run, "meta_counters")
        return newly

    @classmethod
    async def on_revert_sword(cls, db: AsyncSession, user_id: int) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        newly: List[str] = []
        cls._unlock(meta, "ach_16", newly)
        return newly

    @classmethod
    async def on_round_clear(
        cls,
        db: AsyncSession,
        user_id: int,
        run: Run,
        cleared_round: int,
        is_game_clear: bool,
        target_gold: int,
    ) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        counters = dict(getattr(run, "meta_counters", None) or {})
        newly: List[str] = []

        if cleared_round >= 3:
            cls._unlock(meta, "ach_18", newly)
        if cleared_round >= 5:
            cls._unlock(meta, "ach_19", newly)
        if is_game_clear or cleared_round >= 10:
            cls._unlock(meta, "ach_20", newly)
        if len(run.swords or []) == 0:
            cls._unlock(meta, "ach_21", newly)
        if (run.gold or 0) >= target_gold * 3:
            cls._unlock(meta, "ach_22", newly)
        if not counters.get("round_bought", False):
            cls._unlock(meta, "ach_25", newly)
        if is_game_clear and (run.destroyed_count or 0) == 0:
            cls._unlock(meta, "ach_26", newly)

        return newly

    @classmethod
    async def on_sell_sword(cls, db: AsyncSession, user_id: int, run: Run) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        counters = dict(getattr(run, "meta_counters", None) or {})
        counters["round_sells"] = counters.get("round_sells", 0) + 1
        run.meta_counters = counters
        flag_modified(run, "meta_counters")

        newly: List[str] = []
        if counters["round_sells"] >= 5:
            cls._unlock(meta, "ach_27", newly)
        return newly

    @classmethod
    async def on_transform_sword(cls, db: AsyncSession, user_id: int, run: Run, pt_gain: int) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        counters = dict(getattr(run, "meta_counters", None) or {})
        counters["total_relic_pts"] = counters.get("total_relic_pts", 0) + pt_gain
        run.meta_counters = counters
        flag_modified(run, "meta_counters")

        newly: List[str] = []
        if counters["total_relic_pts"] >= 10:
            cls._unlock(meta, "ach_28", newly)
        return newly

    @classmethod
    async def on_buy_shop_item(cls, db: AsyncSession, user_id: int, run: Run) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        counters = dict(getattr(run, "meta_counters", None) or {})
        counters["round_bought"] = True
        run.meta_counters = counters
        flag_modified(run, "meta_counters")

        stats = dict(meta.stats or {})
        stats["total_shop_buys"] = stats.get("total_shop_buys", 0) + 1
        meta.stats = stats
        flag_modified(meta, "stats")

        newly: List[str] = []
        if stats["total_shop_buys"] >= 10:
            cls._unlock(meta, "ach_30", newly)
        return newly

    @classmethod
    async def on_buy_relic(cls, db: AsyncSession, user_id: int, run: Run) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        newly: List[str] = []
        max_slots = config.rules.get("relic_slots", 4)
        if len(run.relics or []) >= max_slots:
            cls._unlock(meta, "ach_29", newly)
        return newly

    @classmethod
    async def on_gamble_event(cls, db: AsyncSession, user_id: int, counters: Dict[str, Any]) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        newly: List[str] = []
        if counters.get("gamble_streak", 0) >= 2:
            cls._unlock(meta, "ach_38", newly)
        if counters.get("gamble_lost"):
            cls._unlock(meta, "ach_39", newly)
        return newly

    @classmethod
    async def on_friend_added(cls, db: AsyncSession, user_id: int, friend_count: int) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        newly: List[str] = []
        if friend_count >= 1:
            cls._unlock(meta, "ach_40", newly)
        if friend_count >= 10:
            cls._unlock(meta, "ach_41", newly)
        return newly

    @classmethod
    async def on_rank_first(cls, db: AsyncSession, user_id: int) -> List[str]:
        meta = await CollectionService.get_or_create_meta(db, user_id)
        newly: List[str] = []
        cls._unlock(meta, "ach_42", newly)
        return newly

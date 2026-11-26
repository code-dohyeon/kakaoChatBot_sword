import random
from typing import Dict, Any, Tuple
from app.core.config import config
from app.models.game import Run, EnhanceLog

class GameEngine:
    @staticmethod
    def calculate_enhance_probabilities(sword_level: int, run_relics: list, boost_stack: int = 0) -> Dict[str, float]:
        """
        GDD 3-1 기반 강화 확률 계산:
        - 파괴 가중치: 레벨당 0.03 증가 (최대 0.4)
        - 성공 가중치: 0.8에서 레벨당 0.045 감소 (최소 0.2)
        - 대성공 가중치: 0.07 고정
        - 유지 가중치: 0.12 고정
        합으로 나누어 100%로 정규화 후, 유물 효과를 가산/승산 적용.
        """
        weights = config.enhance_weights
        destroy_w = min(weights.get("destroy_base", 0.0) + sword_level * weights.get("destroy_per_level", 0.03), weights.get("destroy_max", 0.4))
        success_w = max(weights.get("success_base", 0.8) - sword_level * weights.get("success_per_level_reduction", 0.045), weights.get("success_min", 0.2))
        great_w = weights.get("great_success_fixed", 0.07)
        keep_w = weights.get("keep_fixed", 0.12)

        total = destroy_w + success_w + great_w + keep_w
        p_destroy = destroy_w / total
        p_success = success_w / total
        p_great = great_w / total
        p_keep = keep_w / total

        # 유물 효과 적용
        # 1. 방패 부적: 파괴 확률 -30%
        if "shield_charm" in run_relics:
            p_destroy *= 0.70

        # 2. 행운의 클로버: 성공 확률 +6%p
        if "lucky_clover" in run_relics:
            p_success += 0.06

        # 3. 쌍날 룬: 대성공 확률 +5%p
        if "twin_rune" in run_relics:
            p_great += 0.05

        # 4. 끈질긴 손잡이: 유지 누적 보너스 스택 반영
        if "tenacious_grip" in run_relics and boost_stack > 0:
            boost_val = min(boost_stack * 0.15, 0.30)
            p_great += boost_val

        # 5. 달인의 손길: +0~+4강 강화 시 성공 확률 +15%p
        if "master_touch" in run_relics and sword_level <= 4:
            p_success += 0.15

        # 재정규화 (합이 1.0이 되도록)
        new_total = p_destroy + p_success + p_great + p_keep
        return {
            "destroy": p_destroy / new_total,
            "success": p_success / new_total,
            "great_success": p_great / new_total,
            "keep": p_keep / new_total
        }

    @classmethod
    def enhance_sword(cls, run: Run, sword_idx: int) -> Tuple[str, Dict[str, Any]]:
        """
        선택한 검을 1회 강화.
        결과: ("success" | "great_success" | "keep" | "destroy", 상세정보 dict)
        """
        if sword_idx < 0 or sword_idx >= len(run.swords):
            raise ValueError("유효하지 않은 검 번호입니다.")

        sword = run.swords[sword_idx]
        current_level = sword["level"]
        relics = run.relics or []
        items = run.items or []

        probs = cls.calculate_enhance_probabilities(current_level, relics, run.boost or 0)
        roll = random.random()

        result = "destroy"
        cumulative = 0.0

        for outcome in ["success", "great_success", "keep", "destroy"]:
            cumulative += probs[outcome]
            if roll <= cumulative:
                result = outcome
                break

        prev_level = current_level
        to_level = current_level
        protected_by = None
        bonus_gold = 0
        scrap_gold = 0

        if result == "success":
            to_level = current_level + 1
            sword["level"] = to_level
            run.boost = 0 # 유지 스택 리셋
            if "golden_whetstone" in relics:
                bonus_gold = to_level * 30
                run.gold = (run.gold or 0) + bonus_gold
        elif result == "great_success":
            gain = 2
            if "blacksmith_soul" in relics:
                gain += 1 # 대장장이의 혼: 총 +3
            to_level = current_level + gain
            sword["level"] = to_level
            run.boost = 0 # 유지 스택 리셋
            if "golden_whetstone" in relics:
                bonus_gold = to_level * 30
                run.gold = (run.gold or 0) + bonus_gold
        elif result == "keep":
            if "tenacious_grip" in relics:
                run.boost = min((run.boost or 0) + 1, 2)
        elif result == "destroy":
            # 1. 수호의 가호 유물 체크 (라운드당 1회 방어)
            if "guardians_grace" in relics and (run.shield or 0) > 0:
                result = "keep"
                run.shield -= 1
                protected_by = "guardians_grace"
            # 2. 기적의 부적 유물 체크 (20% 확률로 파괴 무효화)
            elif "miracle_charm" in relics and random.random() < 0.20:
                result = "keep"
                protected_by = "miracle_charm"
            # 3. 파괴 방지 부적 아이템 체크
            elif "protect_destroy" in items:
                result = "keep"
                items.remove("protect_destroy")
                run.items = items
                protected_by = "protect_destroy"
            else:
                # 실제 파괴
                if "scrap_collector" in relics and current_level > 0:
                    scrap_gold = current_level * 50
                    run.gold = (run.gold or 0) + scrap_gold
                run.last_destroyed_sword = {
                    "type": sword.get("type", "normal"),
                    "level": current_level
                }
                run.destroyed_count = (run.destroyed_count or 0) + 1
                run.swords.pop(sword_idx)
                to_level = 0
                run.boost = 0

        # swords 리스트를 새 객체로 복사 재할당 (SQLAlchemy JSON 변경 강제 감지)
        run.swords = [dict(s) for s in run.swords]

        details = {
            "result": result,
            "from_level": prev_level,
            "to_level": to_level,
            "protected_by": protected_by,
            "bonus_gold": bonus_gold,
            "scrap_gold": scrap_gold,
            "probabilities": probs
        }
        return result, details

    @staticmethod
    def calculate_sell_price(sword: Dict[str, Any], relics: list) -> int:
        """
        판매가 계산: 100G * (1.6 ^ level)
        상인의 혀 유물 보유 시 +20%
        """
        sword_type = sword.get("type", "normal")
        type_conf = config.sword_types.get(sword_type, config.sword_types.get("normal"))
        base_price = type_conf.get("base_price", 100)
        multiplier = type_conf.get("price_multiplier", 1.6)
        level = sword.get("level", 0)

        price = int(base_price * (multiplier ** level))
        if "merchants_tongue" in relics:
            price = int(price * 1.20)
        return price

    @staticmethod
    def calculate_relic_points(sword: Dict[str, Any], relics: list = None) -> int:
        """
        변환 포인트 계산: 기본 검 1pt + 5레벨마다 +1pt
        재활용의 미학 유물 보유 시 +1pt 추가
        """
        sword_type = sword.get("type", "normal")
        type_conf = config.sword_types.get(sword_type, config.sword_types.get("normal"))
        base_pts = type_conf.get("base_relic_points", 1)
        per_5 = type_conf.get("relic_points_per_5_levels", 1)
        level = sword.get("level", 0)

        pts = base_pts + (level // 5) * per_5
        if relics and "recycling_art" in relics:
            pts += 1
        return pts

    @staticmethod
    def get_target_gold_for_round(round_num: int) -> int:
        """
        라운드별 납품 목표 골드: 800G * (1.55 ^ (round - 1))
        """
        base = config.rules.get("target_gold_base", 800)
        multiplier = config.rules.get("target_gold_multiplier", 1.55)
        return int(base * (multiplier ** (round_num - 1)))

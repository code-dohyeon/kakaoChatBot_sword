import copy
import random
from types import SimpleNamespace
from typing import List, Dict, Any
from app.core.config import config
from app.services.game_engine import GameEngine

class GameSimulator:
    def __init__(self, strategy: str = "balanced"):
        self.strategy = strategy

    def run_one_game(self) -> Dict[str, Any]:
        """
        1회의 런(1~10라운드)을 시뮬레이션합니다.
        """
        run = SimpleNamespace(
            round=1,
            gold=0,
            relic_points=0,
            swords=[],
            relics=[],
            items=[],
            shield=0,
            boost=0,
            destroyed_count=0,
            last_destroyed_sword=None,
            status="playing"
        )

        rounds_cleared = 0
        swords_destroyed = 0
        max_level_reached = 0

        max_round = config.rules.get("max_round", 10)
        swords_per_round = config.rules.get("swords_per_round", 3)

        for r in range(1, max_round + 1):
            run.round = r
            # 라운드 시작 시 기본 검 지급
            start_id = max([s.get("id", 0) for s in run.swords], default=0) + 1
            for i in range(swords_per_round):
                run.swords.append({"id": start_id + i, "type": "normal", "level": 0})

            # 수호의 가호 유물 보유 시 방어막 1 충전
            if "guardians_grace" in run.relics:
                run.shield = 1

            target_gold = GameEngine.get_target_gold_for_round(r)

            # 라운드 내 강화 및 행동 결정
            # 전략별 목표 강화 레벨
            if self.strategy == "conservative":
                target_lvl = min(3 + (r // 2), 9)
            elif self.strategy == "aggressive":
                target_lvl = min(5 + r, 14)
            else: # balanced
                target_lvl = min(4 + (r * 2 // 3), 11)

            # 유물 우선 구매 로직 (포인트 있을 때)
            self._try_buy_relics(run)

            # 강화 루프
            attempts = 0
            while run.swords and attempts < 100:
                attempts += 1
                # 골드가 이미 목표를 달성했고 검이 남아있다면 다음 라운드를 위해 보존
                if run.gold >= target_gold and any(s["level"] >= target_lvl for s in run.swords):
                    break

                # 강화할 검 선택 (가장 레벨 낮은 검 먼저 또는 목표 미달 검)
                eligible_swords = [i for i, s in enumerate(run.swords) if s["level"] < target_lvl]
                if not eligible_swords:
                    break

                idx = eligible_swords[0]
                prev_lvl = run.swords[idx]["level"]
                res, details = GameEngine.enhance_sword(run, idx)

                if res == "destroy":
                    swords_destroyed += 1
                else:
                    if details["to_level"] > max_level_reached:
                        max_level_reached = details["to_level"]

                    # 목표 레벨 도달 검 처리
                    if details["to_level"] >= target_lvl:
                        # 골드가 부족하면 판매
                        if run.gold < target_gold:
                            sold_sword = run.swords.pop(idx)
                            run.gold += GameEngine.calculate_sell_price(sold_sword, run.relics)
                        # 골드가 충분하고 유물 슬롯/포인트가 필요하면 변환
                        elif len(run.relics) < 4 and random.random() < 0.5:
                            trans_sword = run.swords.pop(idx)
                            run.relic_points += GameEngine.calculate_relic_points(trans_sword)
                            self._try_buy_relics(run)

            # 검이 남았고 골드가 아직 부족하다면 추가 판매 시도
            if run.gold < target_gold and run.swords:
                # 레벨 높은 순으로 판매
                run.swords.sort(key=lambda s: s["level"], reverse=True)
                while run.swords and run.gold < target_gold:
                    sold_sword = run.swords.pop(0)
                    run.gold += GameEngine.calculate_sell_price(sold_sword, run.relics)

            # 라운드 마감 판정
            if run.gold < target_gold:
                # 실패: 게임 오버
                return {
                    "cleared": False,
                    "final_round": r,
                    "final_gold": run.gold,
                    "swords_destroyed": swords_destroyed,
                    "max_level": max_level_reached,
                    "relics_count": len(run.relics)
                }

            rounds_cleared = r

        return {
            "cleared": True,
            "final_round": 10,
            "final_gold": run.gold,
            "swords_destroyed": swords_destroyed,
            "max_level": max_level_reached,
            "relics_count": len(run.relics)
        }

    def _try_buy_relics(self, run):
        """효율적인 유물 우선 구매"""
        priority_relics = ["shield_charm", "guardians_grace", "merchants_tongue", "lucky_clover", "twin_rune"]
        for r_id in priority_relics:
            if len(run.relics) >= 4:
                break
            if r_id not in run.relics:
                cost = config.relics[r_id]["point_cost"]
                if run.relic_points >= cost:
                    run.relic_points -= cost
                    run.relics.append(r_id)
                    if r_id == "guardians_grace":
                        run.shield = 1

def run_simulation(n_simulations: int = 5000):
    print("=" * 65)
    print(f"📊 [게임 밸런스 대규모 시뮬레이션] (전략별 각 {n_simulations:,}회 실행)")
    print("=" * 65)

    strategies = ["conservative", "balanced", "aggressive"]
    strategy_names = {
        "conservative": "안정형 (낮은 목표강화, 안전 판매)",
        "balanced": "균형형 (라운드별 점진적 목표 상향, 유물 투자)",
        "aggressive": "공격형 (고강화 추구, 하이리스크 하이리턴)"
    }

    results_summary = {}

    for strat in strategies:
        sim = GameSimulator(strategy=strat)
        cleared_count = 0
        round_deaths = {r: 0 for r in range(1, 11)}
        total_destroyed_swords = 0
        total_max_levels = []
        total_gold_list = []

        for _ in range(n_simulations):
            res = sim.run_one_game()
            if res["cleared"]:
                cleared_count += 1
            else:
                round_deaths[res["final_round"]] += 1
            total_destroyed_swords += res["swords_destroyed"]
            total_max_levels.append(res["max_level"])
            total_gold_list.append(res["final_gold"])

        clear_rate = (cleared_count / n_simulations) * 100
        avg_destroyed = total_destroyed_swords / n_simulations
        avg_max_lvl = sum(total_max_levels) / len(total_max_levels)
        avg_gold = sum(total_gold_list) / len(total_gold_list)

        results_summary[strat] = {
            "clear_rate": clear_rate,
            "round_deaths": round_deaths,
            "avg_destroyed": avg_destroyed,
            "avg_max_lvl": avg_max_lvl,
            "avg_gold": avg_gold
        }

        print(f"\n▶ [{strategy_names[strat]}]")
        print(f"  • 10라운드 최종 완주율 (클리어율): {clear_rate:.2f}% ({cleared_count:,} / {n_simulations:,})")
        print(f"  • 게임당 평균 파괴된 검 수: {avg_destroyed:.1f}개")
        print(f"  • 달성 평균 최고 강화 레벨: +{avg_max_lvl:.1f}강")
        print(f"  • 평균 획득 골드: {int(avg_gold):,}G")
        print("  • 라운드별 탈락(사망) 분포:")
        for r in range(1, 11):
            pct = (round_deaths[r] / n_simulations) * 100
            bar = "■" * int(pct // 2)
            print(f"    R{r:<2}: {pct:5.1f}% | {bar}")

    print("\n" + "=" * 65)
    print("📈 [밸런스 분석 종합 결론]")
    print("=" * 65)
    bal_cr = results_summary["balanced"]["clear_rate"]
    print(f"• 대표 표준 전략(균형형) 완주율: {bal_cr:.2f}%")
    if 5.0 <= bal_cr <= 25.0:
        print("  ✅ [적정 밸런스 범위 달성!]")
        print("     일반적인 로그라이크 캐주얼 게임의 황금 타겟 완주율(8~20%) 범위에 정확히 안착했습니다.")
    elif bal_cr < 5.0:
        print("  ⚠️ [난이도 높음: 하향 필요]")
        print("     목표 골드 상승률이나 파괴 확률을 소폭 완화해야 합니다.")
    else:
        print("  ⚠️ [난이도 낮음: 상향 필요]")
        print("     목표 골드나 파괴 확률을 소폭 올려 긴장감을 부여해야 합니다.")

if __name__ == "__main__":
    run_simulation(5000)

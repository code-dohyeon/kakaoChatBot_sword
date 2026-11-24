from app.services.game_engine import GameEngine
from app.utils.image_helper import get_sword_image_url
from app.core.config import config
from types import SimpleNamespace

def test_engine_pure():
    print("=== [1] 설정 로드 테스트 ===")
    print(f"규칙 max_round: {config.rules.get('max_round')}")
    print(f"검 종류: {list(config.sword_types.keys())}")
    print(f"유물 개수: {len(config.relics)}")

    print("\n=== [2] 강화 확률 계산 테스트 ===")
    p0 = GameEngine.calculate_enhance_probabilities(0, [])
    p5 = GameEngine.calculate_enhance_probabilities(5, ["shield_charm"])
    print(f"0강 기본 확률: 성공 {p0['success']:.2%}, 대성공 {p0['great_success']:.2%}, 유지 {p0['keep']:.2%}, 파괴 {p0['destroy']:.2%}")
    print(f"5강(방패부적) 확률: 성공 {p5['success']:.2%}, 대성공 {p5['great_success']:.2%}, 유지 {p5['keep']:.2%}, 파괴 {p5['destroy']:.2%}")

    print("\n=== [3] 가상 Run 강화 시뮬레이션 ===")
    mock_run = SimpleNamespace(
        swords=[{"id": 1, "type": "normal", "level": 0}],
        relics=[],
        items=[],
        shield=0,
        boost=0,
        destroyed_count=0,
        last_destroyed_sword=None
    )
    for i in range(5):
        if not mock_run.swords:
            print("검이 파괴되었습니다.")
            break
        res, details = GameEngine.enhance_sword(mock_run, 0)
        print(f"시도 {i+1}: 결과={res}, {details['from_level']}강 -> {details['to_level']}강")

    print("\n=== [4] 판매가 & 변환 포인트 & 목표 골드 테스트 ===")
    dummy_sword = {"type": "normal", "level": 5}
    sell_price = GameEngine.calculate_sell_price(dummy_sword, [])
    relic_pts = GameEngine.calculate_relic_points(dummy_sword)
    r1_goal = GameEngine.get_target_gold_for_round(1)
    r2_goal = GameEngine.get_target_gold_for_round(2)
    print(f"+5강 기본 검 판매가: {sell_price:,}G")
    print(f"+5강 변환 포인트: {relic_pts}pt")
    print(f"R1 목표: {r1_goal:,}G | R2 목표: {r2_goal:,}G")

    print("\n=== [5] 이미지 파일 매핑 검증 ===")
    print(f"0강 이미지 URL: {get_sword_image_url(0)}")
    print(f"10강 나뭇가지 URL: {get_sword_image_url(10, 'stick')}")
    print("\n>>> 순수 로직 테스트 성공 완료! <<<")

if __name__ == "__main__":
    test_engine_pure()

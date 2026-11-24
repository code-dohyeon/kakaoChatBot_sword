import asyncio
from app.db.session import engine, Base, AsyncSessionLocal
from app.services.run_service import RunService
from app.services.game_engine import GameEngine
from app.utils.image_helper import get_sword_image_url

async def test_game_flow():
    print("=== 1. DB 테이블 초기화 테스트 ===")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("DB 테이블 생성 성공!")

    async with AsyncSessionLocal() as session:
        print("\n=== 2. 유저 생성 및 런 시작 ===")
        user = await RunService.get_or_create_user(session, "test_kakao_user_123")
        print(f"User 생성: id={user.id}, friend_code={user.friend_code}")

        run = await RunService.start_new_run(session, user.id)
        print(f"Run 시작: round={run.round}, swords_count={len(run.swords)}, gold={run.gold}")

        print("\n=== 3. 강화 시뮬레이션 ===")
        for i in range(5):
            if not run.swords:
                print("검이 모두 파괴되었습니다.")
                break
            res, details = GameEngine.enhance_sword(run, 0)
            print(f"강화 시도 {i+1}: 결과={res}, {details['from_level']}강 -> {details['to_level']}강")

        print("\n=== 4. 이미지 URL 매핑 검증 ===")
        url_0 = get_sword_image_url(0)
        url_5 = get_sword_image_url(5)
        print(f"0강 이미지 URL: {url_0}")
        print(f"5강 이미지 URL: {url_5}")

        print("\n=== 5. 납품 및 라운드 전환 테스트 ===")
        run.gold = 1000 # R1 목표(800G) 달성 가정
        success, msg = await RunService.advance_round(session, run)
        print(f"납품 결과: {success}, 메시지: {msg}")
        print(f"다음 라운드: {run.round}, 보유 검 수: {len(run.swords)}")

    await engine.dispose()
    print("\n=== 전체 테스트 성공 완료! ===")

if __name__ == "__main__":
    asyncio.run(test_game_flow())

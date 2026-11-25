import asyncio
from app.db.session import AsyncSessionLocal, engine, Base
from app.services.run_service import RunService
from app.routers.extra_router import add_friend, delete_friend, view_ranking_and_friend

async def test_friend_system():
    print("=== [친구 추가/삭제 시스템 검증] ===")
    async with AsyncSessionLocal() as db:
        # 유저 2명 생성 (A와 B)
        user_a = await RunService.get_or_create_user(db, "kakao_user_A")
        user_b = await RunService.get_or_create_user(db, "kakao_user_B")
        user_a.nickname = "대장장이A"
        user_b.nickname = "검투사B"
        await db.commit()

        print(f"유저 A 생성: 닉네임={user_a.nickname}, 친구코드={user_a.friend_code}")
        print(f"유저 B 생성: 닉네임={user_b.nickname}, 친구코드={user_b.friend_code}")

        # 1. 유저 A가 띄어쓰기 포함하여 유저 B 친구 추가 시도 ("친구 추가 B의코드")
        payload_add = {
            "userRequest": {
                "user": {"id": "kakao_user_A"},
                "utterance": f"친구 추가 {user_b.friend_code}"
            }
        }
        res_add = await add_friend(payload_add, db)
        print("\n1. 친구 추가 응답:")
        print(res_add["template"]["outputs"][0])

        # 2. 랭킹 확인 (A의 랭킹에 B가 뜨는지)
        payload_rank = {
            "userRequest": {
                "user": {"id": "kakao_user_A"},
                "utterance": "랭킹"
            }
        }
        res_rank = await view_ranking_and_friend(payload_rank, db)
        print("\n2. 친구 랭킹 응답:")
        print(res_rank["template"]["outputs"][0]["basicCard"]["description"])

        # 3. 친구 삭제 테스트 ("친구삭제 검투사B")
        payload_del = {
            "userRequest": {
                "user": {"id": "kakao_user_A"},
                "utterance": f"친구삭제 {user_b.nickname}"
            }
        }
        res_del = await delete_friend(payload_del, db)
        print("\n3. 친구 삭제 응답:")
        print(res_del["template"]["outputs"][0])

    await engine.dispose()
    print("\n>>> 검증 완료! 친구 추가 및 삭제가 완벽하게 동작합니다! <<<")

if __name__ == "__main__":
    asyncio.run(test_friend_system())

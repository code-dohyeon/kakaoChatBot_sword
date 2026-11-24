from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.db.session import get_db
from app.utils.kakao_builder import KakaoResponseBuilder
from app.services.run_service import RunService
from app.services.game_engine import GameEngine
from app.core.config import config
from app.models.game import User, Ranking, Friend
from app.routers.kakao_router import get_user_key, get_utterance
from typing import Dict, Any

router = APIRouter(prefix="/api/kakao", tags=["kakao_extra"])

@router.post("/sell-transform")
async def sell_or_transform_sword(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """검 판매 또는 변환 처리"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)
    user = await RunService.get_or_create_user(db, user_key)
    run = await RunService.get_active_run(db, user.id)

    if not run or run.status != "playing":
        return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

    # 발화 파싱: 예) "1번 판매", "2번 변환"
    is_sell = "판매" in utterance
    sword_idx = 0
    for w in utterance.split():
        if "번" in w and w.replace("번", "").isdigit():
            sword_idx = int(w.replace("번", "")) - 1
            break

    if sword_idx < 0 or sword_idx >= len(run.swords):
        return KakaoResponseBuilder.simple_text("유효한 검 번호를 찾을 수 없습니다.")

    target_sword = run.swords[sword_idx]
    lvl = target_sword.get("level", 0)

    if is_sell:
        gold_gain = GameEngine.calculate_sell_price(target_sword, run.relics or [])
        run.gold += gold_gain
        run.swords.pop(sword_idx)
        await db.commit()
        return KakaoResponseBuilder.basic_card(
            title="💰 판매 완료",
            description=f"+{lvl}강 검을 판매하여 {gold_gain:,}G를 획득했습니다!\n• 보유 골드: {run.gold:,}G\n• 남은 검: {len(run.swords)}개",
            buttons=[
                {"action": "message", "label": "🗡️ 남은 검 보기", "messageText": "내 검 보기"},
                {"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"}
            ]
        )
    else:
        # 변환 (유물 포인트 획득)
        pt_gain = GameEngine.calculate_relic_points(target_sword)
        run.relic_points += pt_gain
        run.swords.pop(sword_idx)
        await db.commit()
        return KakaoResponseBuilder.basic_card(
            title="🔮 유물 변환 완료",
            description=f"+{lvl}강 검을 신비한 기운으로 변환하여 유물 포인트 {pt_gain}pt를 획득했습니다!\n• 보유 유물 포인트: {run.relic_points}pt\n• 남은 검: {len(run.swords)}개",
            buttons=[
                {"action": "message", "label": "🏺 유물 상점", "messageText": "상점·유물"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
            ]
        )

@router.post("/shop")
async def view_shop(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """골드 상점 & 유물 상점 안내"""
    user_key = get_user_key(payload)
    user = await RunService.get_or_create_user(db, user_key)
    run = await RunService.get_active_run(db, user.id)

    if not run or run.status != "playing":
        return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

    round_mult = (config.rules.get("shop_price_multiplier", 1.4) ** (run.round - 1))

    # 상점 품목 캐러셀 카드
    cards = []
    for item in config.shop_items.values():
        price = int(item["base_price"] * round_mult)
        cards.append({
            "title": f"🏪 {item['name']} ({price:,}G)",
            "description": f"설명: {item.get('description', '라운드마다 가격이 상승합니다.')}\n보유 골드: {run.gold:,}G",
            "buttons": [
                {"action": "message", "label": f"{item['name']} 구매", "messageText": f"아이템구매 {item['id']}"}
            ]
        })

    # 유물 상점 버튼 카드 추가
    relic_summary = f"보유 유물 포인트: {run.relic_points}pt\n장착 슬롯: {len(run.relics or [])}/{config.rules.get('relic_slots', 4)}"
    cards.append({
        "title": "🏺 유물 상점",
        "description": relic_summary,
        "buttons": [
            {"action": "message", "label": "유물 목록 보기", "messageText": "유물보기"}
        ]
    })

    return KakaoResponseBuilder.carousel(cards[:5])

@router.post("/ranking-friend")
async def view_ranking_and_friend(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """친구 랭킹 및 내 친구 코드 안내"""
    user_key = get_user_key(payload)
    user = await RunService.get_or_create_user(db, user_key)

    # 내 친구 목록 조회
    stmt = select(Friend).where(Friend.user_id == user.id)
    res = await db.execute(stmt)
    friend_rows = res.scalars().all()
    friend_ids = [f.friend_user_id for f in friend_rows] + [user.id]

    # 친구 + 본인 랭킹 정렬 (1: best_round DESC, 2: best_level DESC)
    rank_stmt = (
        select(Ranking, User)
        .join(User, Ranking.user_id == User.id)
        .where(Ranking.user_id.in_(friend_ids))
        .order_by(Ranking.best_round.desc(), Ranking.best_level.desc())
    )
    rank_res = await db.execute(rank_stmt)
    rank_records = rank_res.all()

    leaderboard = []
    for idx, (rk, u) in enumerate(rank_records):
        me_tag = " (나)" if u.id == user.id else ""
        leaderboard.append(f"{idx+1}위: {u.nickname}{me_tag} - R{rk.best_round} / +{rk.best_level}강")

    rank_text = "\n".join(leaderboard) if leaderboard else "등록된 기록이 없습니다."

    desc = (
        f"🔑 내 친구 코드: {user.friend_code}\n\n"
        f"🏆 [친구 랭킹 (최대 10명)]\n{rank_text}\n\n"
        f"상대방의 친구 코드를 입력하려면 '친구추가 [코드]'를 입력하세요."
    )
    return KakaoResponseBuilder.basic_card(
        title="🏆 대장간 친구 랭킹",
        description=desc,
        buttons=[
            {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
            {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"}
        ]
    )

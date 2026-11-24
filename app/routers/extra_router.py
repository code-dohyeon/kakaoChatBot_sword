from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.utils.kakao_builder import KakaoResponseBuilder
from app.services.run_service import RunService
from app.services.game_engine import GameEngine
from app.core.config import config
from app.models.game import User, Ranking, Friend
from app.routers.kakao_router import get_user_key, get_utterance
from app.utils.lock_manager import UserLockManager
from sqlalchemy.orm.attributes import flag_modified
from typing import Dict, Any

router = APIRouter(prefix="/api/kakao", tags=["kakao_extra"])

@router.post("/sell-transform")
async def sell_or_transform_sword(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """검 판매 또는 변환 처리 (동시성 락 적용)"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.get_active_run(db, user.id)

        if not run or run.status != "playing":
            return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

        if not run.swords:
            return KakaoResponseBuilder.simple_text("판매하거나 변환할 검이 없습니다.")

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
            run.round_sales_gold = (getattr(run, 'round_sales_gold', 0) or 0) + gold_gain
            swords = list(run.swords)
            swords.pop(sword_idx)
            run.swords = swords
            flag_modified(run, "swords")
            db.add(run)
            await db.commit()
            await db.refresh(run)

            target_gold = GameEngine.get_target_gold_for_round(run.round)
            sales_gold = getattr(run, 'round_sales_gold', 0) or 0
            desc = (
                f"+{lvl}강 검을 판매하여 {gold_gain:,}G를 획득했습니다!\n"
                f"• 이번 라운드 판매 수익: {sales_gold:,}G / 목표: {target_gold:,}G\n"
                f"• 현재 소지금: {run.gold:,}G\n"
                f"• 남은 검: {len(run.swords)}개"
            )
            buttons = []
            if len(run.swords) > 0:
                buttons.append({"action": "message", "label": "🗡️ 남은 검 보기", "messageText": "내 검 보기"})
                buttons.append({"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"})
            else:
                if sales_gold >= target_gold:
                    buttons.append({"action": "message", "label": "📦 납품·마감", "messageText": "납품·마감"})
                buttons.append({"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"})

            return KakaoResponseBuilder.basic_card(
                title="💰 판매 완료",
                description=desc,
                buttons=buttons[:3]
            )
        else:
            # 변환 (유물 포인트 획득)
            pt_gain = GameEngine.calculate_relic_points(target_sword)
            run.relic_points += pt_gain
            swords = list(run.swords)
            swords.pop(sword_idx)
            run.swords = swords
            flag_modified(run, "swords")
            db.add(run)
            await db.commit()
            await db.refresh(run)

            desc = (
                f"+{lvl}강 검을 신비한 기운으로 변환하여 유물 포인트 {pt_gain}pt를 획득했습니다!\n"
                f"• 보유 유물 포인트: {run.relic_points}pt\n"
                f"• 장착 유물: {len(run.relics or [])}/{config.rules.get('relic_slots', 4)}개\n"
                f"• 남은 검: {len(run.swords)}개"
            )
            buttons = [
                {"action": "message", "label": "🏺 유물 상점", "messageText": "유물보기"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
            ]
            return KakaoResponseBuilder.basic_card(
                title="🔮 유물 변환 완료",
                description=desc,
                buttons=buttons
            )

@router.post("/shop")
async def view_shop(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """골드 상점 & 유물 상점 안내 및 통합 발화 디스패처"""
    utterance = get_utterance(payload)

    # 발화 디스패치
    if utterance.startswith("아이템구매"):
        return await buy_item(payload, db)
    elif utterance in ["유물보기", "유물상점", "유물", "유물 상점"]:
        return await view_relics(payload, db)
    elif utterance.startswith("유물구매"):
        return await buy_relic(payload, db)

    user_key = get_user_key(payload)
    user = await RunService.get_or_create_user(db, user_key)
    run = await RunService.get_active_run(db, user.id)

    if not run or run.status != "playing":
        return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다. [새 게임]을 눌러 시작해주세요.")

    round_mult = (config.rules.get("shop_price_multiplier", 1.4) ** (run.round - 1))

    # [일반 상점]: 골드로 구매하는 소모품 및 검 품목들만 깔끔하게 노출
    cards = []
    for item in config.shop_items.values():
        price = int(item["base_price"] * round_mult)
        item_desc = item.get("description", "추가 검을 구매합니다.")
        desc = f"가격: {price:,}G (보유 골드: {run.gold:,}G)\n효과: {item_desc}"
        cards.append({
            "title": f"🏪 {item['name']}",
            "description": desc,
            "buttons": [
                {"action": "message", "label": f"{price:,}G로 구매", "messageText": f"아이템구매 {item['id']}"}
            ]
        })

    return KakaoResponseBuilder.carousel(cards[:5])

@router.post("/buy-item")
async def buy_item(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """상점 아이템 구매 처리 (동시성 락 적용)"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.get_active_run(db, user.id)

        if not run or run.status != "playing":
            return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

        # 파싱: "아이템구매 sword_normal" 등
        item_id = utterance.replace("아이템구매", "").strip()
        item = config.shop_items.get(item_id)
        if not item:
            return KakaoResponseBuilder.simple_text("존재하지 않는 상점 품목입니다.")

        round_mult = (config.rules.get("shop_price_multiplier", 1.4) ** (run.round - 1))
        price = int(item["base_price"] * round_mult)

        if run.gold < price:
            return KakaoResponseBuilder.basic_card(
                title="💸 골드 부족",
                description=f"골드가 부족하여 [{item['name']}]을(를) 구매할 수 없습니다.\n• 필요 골드: {price:,}G\n• 보유 골드: {run.gold:,}G",
                buttons=[
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                    {"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"}
                ]
            )

        run.gold -= price

        # 검 구매인 경우
        if item.get("type") == "sword":
            swords = list(run.swords or [])
            new_id = max([s.get("id", 0) for s in swords], default=0) + 1
            swords.append({
                "id": new_id,
                "type": item.get("target_id", "normal"),
                "level": 0
            })
            run.swords = swords
            await db.commit()

            return KakaoResponseBuilder.basic_card(
                title=f"🗡️ {item['name']} 구매 완료!",
                description=f"{price:,}G를 지불하고 새로운 검을 획득했습니다.\n• 보유 골드: {run.gold:,}G\n• 보유 검: {len(run.swords)}개",
                buttons=[
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                    {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"},
                    {"action": "message", "label": "🏪 계속 쇼핑", "messageText": "상점·유물"}
                ]
            )
        else:
            # 소비성 아이템 구매 (protect_destroy, revert_destroy 등)
            items = list(run.items or [])
            items.append(item_id)
            run.items = items
            await db.commit()

            return KakaoResponseBuilder.basic_card(
                title=f"📦 {item['name']} 구매 완료!",
                description=f"{price:,}G를 지불하고 [{item['name']}]을(를) 인벤토리에 보관했습니다.\n• 효과: {item.get('description', '')}\n• 보유 골드: {run.gold:,}G",
                buttons=[
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                    {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"},
                    {"action": "message", "label": "🏪 계속 쇼핑", "messageText": "상점·유물"}
                ]
            )

@router.post("/relics")
async def view_relics(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """유물 상점 목록 (캐러셀)"""
    user_key = get_user_key(payload)
    user = await RunService.get_or_create_user(db, user_key)
    run = await RunService.get_active_run(db, user.id)

    if not run or run.status != "playing":
        return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

    owned_relics = run.relics or []
    slots_used = len(owned_relics)
    max_slots = config.rules.get("relic_slots", 4)

    cards = []
    for r in config.relics.values():
        is_owned = r["id"] in owned_relics
        status_tag = " [장착중]" if is_owned else ""
        desc = (
            f"비용: {r['point_cost']}pt (보유: {run.relic_points}pt)\n"
            f"효과: {r['description']}\n"
            f"슬롯: {slots_used}/{max_slots}개"
        )
        if is_owned:
            btn = {"action": "message", "label": "✅ 이미 장착됨", "messageText": "유물보기"}
        else:
            btn = {"action": "message", "label": f"{r['point_cost']}pt로 장착", "messageText": f"유물구매 {r['id']}"}

        cards.append({
            "title": f"🏺 {r['name']}{status_tag}",
            "description": desc,
            "buttons": [btn]
        })

    # 카카오 캐러셀은 5개 제한이므로 상위 5개 또는 2개 카드 묶음 제공
    return KakaoResponseBuilder.carousel(cards[:5])

@router.post("/buy-relic")
async def buy_relic(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """유물 구매/장착 처리 (동시성 락 적용)"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.get_active_run(db, user.id)

        if not run or run.status != "playing":
            return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

        relic_id = utterance.replace("유물구매", "").strip()
        relic = config.relics.get(relic_id)
        if not relic:
            return KakaoResponseBuilder.simple_text("존재하지 않는 유물입니다.")

        owned = list(run.relics or [])
        if relic_id in owned:
            return KakaoResponseBuilder.simple_text(f"이미 장착 중인 유물입니다: [{relic['name']}]")

        max_slots = config.rules.get("relic_slots", 4)
        if len(owned) >= max_slots:
            return KakaoResponseBuilder.basic_card(
                title="🏺 유물 슬롯 초과",
                description=f"유물 슬롯이 꽉 찼습니다! (최대 {max_slots}개)\n새 유물을 장착하려면 기존 유물을 교체해야 합니다.",
                buttons=[
                    {"action": "message", "label": "🏺 유물 목록", "messageText": "유물보기"},
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
                ]
            )

        cost = relic.get("point_cost", 1)
        if run.relic_points < cost:
            return KakaoResponseBuilder.basic_card(
                title="🔮 유물 포인트 부족",
                description=f"포인트가 부족하여 [{relic['name']}]을(를) 구매할 수 없습니다.\n• 필요 포인트: {cost}pt\n• 보유 포인트: {run.relic_points}pt\n\n불필요한 검을 [변환]하여 포인트를 얻으세요!",
                buttons=[
                    {"action": "message", "label": "🗡️ 검 변환하러 가기", "messageText": "내 검 보기"},
                    {"action": "message", "label": "🏺 유물 목록", "messageText": "유물보기"}
                ]
            )

        run.relic_points -= cost
        owned.append(relic_id)
        run.relics = owned

        # 수호의 가호 즉시 1회 방어막 충전
        if relic_id == "guardians_grace":
            run.shield = 1

        await db.commit()

        return KakaoResponseBuilder.basic_card(
            title=f"✨ {relic['name']} 장착 완료!",
            description=f"신비한 유물이 활성화되었습니다!\n• 효과: {relic['description']}\n• 남은 포인트: {run.relic_points}pt\n• 장착 슬롯: {len(owned)}/{max_slots}개",
            buttons=[
                {"action": "message", "label": "⚔️ 강화하러 가기", "messageText": "강화하기"},
                {"action": "message", "label": "🏺 유물 목록", "messageText": "유물보기"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
            ]
        )

@router.post("/ranking-friend")
async def view_ranking_and_friend(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """친구 랭킹 및 내 친구 코드 안내 & 친구추가 발화 처리"""
    utterance = get_utterance(payload)
    if utterance.startswith("친구추가"):
        return await add_friend(payload, db)

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
        f"🔑 내 친구 코드: {user.friend_code}\n"
        f"(친구 수: {len(friend_rows)}/10명)\n\n"
        f"🏆 [친구 랭킹 순위표]\n{rank_text}\n\n"
        f"친구를 등록하려면 '친구추가 [코드]'를 채팅창에 입력해주세요!"
    )
    return KakaoResponseBuilder.basic_card(
        title="🏆 대장간 친구 랭킹",
        description=desc,
        buttons=[
            {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
            {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"}
        ]
    )

@router.post("/add-friend")
async def add_friend(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """친구 코드 등록 처리 (동시성 락 적용)"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)

        code = utterance.replace("친구추가", "").strip().upper()
        if not code:
            return KakaoResponseBuilder.simple_text("친구 코드를 입력해주세요. (예: 친구추가 A1B2C3D4)")

        if code == user.friend_code:
            return KakaoResponseBuilder.simple_text("자신의 친구 코드는 등록할 수 없습니다.")

        # 대상 유저 검색
        stmt = select(User).where(User.friend_code == code)
        res = await db.execute(stmt)
        target_user = res.scalar_one_or_none()
        if not target_user:
            return KakaoResponseBuilder.simple_text(f"해당 친구 코드({code})의 유저를 찾을 수 없습니다.")

        # 현재 친구 수 체크
        friend_stmt = select(Friend).where(Friend.user_id == user.id)
        f_res = await db.execute(friend_stmt)
        current_friends = f_res.scalars().all()
        if len(current_friends) >= 10:
            return KakaoResponseBuilder.simple_text("친구는 최대 10명까지만 등록할 수 있습니다.")

        # 이미 등록된 친구인지 체크
        if any(f.friend_user_id == target_user.id for f in current_friends):
            return KakaoResponseBuilder.simple_text(f"이미 친구로 등록된 유저입니다: {target_user.nickname}")

        new_friend = Friend(user_id=user.id, friend_user_id=target_user.id)
        db.add(new_friend)
        await db.commit()

        return KakaoResponseBuilder.basic_card(
            title="🤝 친구 등록 성공!",
            description=f"[{target_user.nickname}] 님이 친구 목록에 추가되었습니다!\n이제 랭킹에서 함께 기록을 겨뤄보세요.",
            buttons=[
                {"action": "message", "label": "🏆 랭킹 확인하기", "messageText": "자랑·랭킹"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
            ]
        )

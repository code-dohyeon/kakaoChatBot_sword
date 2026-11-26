from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.utils.kakao_builder import KakaoResponseBuilder
from app.services.run_service import RunService
from app.services.game_engine import GameEngine
from app.services.collection_service import CollectionService
from app.core.config import config
from app.models.game import User, Ranking, Friend, UserMeta
from app.routers.kakao_router import get_user_key, get_utterance
from app.utils.lock_manager import UserLockManager
from sqlalchemy.orm.attributes import flag_modified
from typing import Dict, Any
from app.services.achievement_service import AchievementService

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
            return KakaoResponseBuilder.no_active_game()

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
        s_type = target_sword.get("type", "normal")

        if is_sell:
            from app.utils.image_helper import get_sword_image_url
            sell_img_url = get_sword_image_url(lvl, s_type)
            gold_gain = GameEngine.calculate_sell_price(target_sword, run.relics or [], getattr(run, "round_event", None))
            run.gold += gold_gain
            run.round_sales_gold = (getattr(run, 'round_sales_gold', 0) or 0) + gold_gain
            swords = list(run.swords)
            swords.pop(sword_idx)
            run.swords = swords
            flag_modified(run, "swords")
            db.add(run)
            ach_titles = await AchievementService.on_sell_sword(db, user.id, run)
            await db.commit()
            await db.refresh(run)

            target_gold = GameEngine.get_target_gold_for_round(run.round)
            sales_gold = getattr(run, 'round_sales_gold', 0) or 0
            ach_note = f"\n🏅 칭호 해금: {', '.join(ach_titles)}" if ach_titles else ""
            desc = (
                f"+{lvl}강 검을 판매하여 {gold_gain:,}G를 획득했습니다!\n"
                f"• 이번 라운드 판매 수익: {sales_gold:,}G / 목표: {target_gold:,}G\n"
                f"• 현재 소지금: {run.gold:,}G\n"
                f"• 남은 검: {len(run.swords)}개{ach_note}"
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
                thumbnail_url=sell_img_url,
                buttons=buttons[:3]
            )
        else:
            # 변환 (유물 포인트 획득)
            pt_gain = GameEngine.calculate_relic_points(target_sword, run.relics or [])
            run.relic_points += pt_gain
            swords = list(run.swords)
            swords.pop(sword_idx)
            run.swords = swords
            flag_modified(run, "swords")
            db.add(run)
            ach_titles = await AchievementService.on_transform_sword(db, user.id, run, pt_gain)
            await db.commit()
            await db.refresh(run)

            ach_note = f"\n🏅 칭호 해금: {', '.join(ach_titles)}" if ach_titles else ""
            desc = (
                f"+{lvl}강 검을 신비한 기운으로 변환하여 유물 포인트 {pt_gain}pt를 획득했습니다!\n"
                f"• 보유 유물 포인트: {run.relic_points}pt\n"
                f"• 장착 유물: {len(run.relics or [])}/{config.rules.get('relic_slots', 4)}개\n"
                f"• 남은 검: {len(run.swords)}개{ach_note}"
            )
            buttons = [
                {"action": "message", "label": "🏺 유물 상점", "messageText": "유물보기"},
                {"action": "message", "label": "🔮 다른 검 변환", "messageText": "검변환"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
            ]
            return KakaoResponseBuilder.basic_card(
                title="🔮 유물 변환 완료",
                description=desc,
                buttons=buttons
            )

@router.post("/transform-menu")
async def transform_menu(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """검 변환 전용 선택 메뉴 ('검변환', '변환', '유물변환')"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    # 특정 검 변환 명령어인 경우 바로 실행 (예: "1번 변환", "2번변환")
    if "번" in utterance and "변환" in utterance:
        return await sell_or_transform_sword(payload, db)

    user = await RunService.get_or_create_user(db, user_key)
    run = await RunService.get_active_run(db, user.id)

    if not run or run.status != "playing":
        return KakaoResponseBuilder.no_active_game()

    if not run.swords:
        return KakaoResponseBuilder.basic_card(
            title="🔮 변환할 검이 없습니다!",
            description="보유한 검이 모두 소진되었습니다.\n[일반 상점]에서 검을 구매하거나 새 게임을 시작하세요.",
            buttons=[
                {"action": "message", "label": "🏪 일반 상점", "messageText": "일반 상점"},
                {"action": "message", "label": "🔄 새 게임", "messageText": "새 게임"}
            ]
        )

    cards = []
    for idx, sword in enumerate(run.swords):
        lvl = sword.get("level", 0)
        s_type = sword.get("type", "normal")
        type_name = config.sword_types.get(s_type, {}).get("name", "기본 검")
        relic_pts = GameEngine.calculate_relic_points(sword, run.relics or [])
        sell_p = GameEngine.calculate_sell_price(sword, run.relics or [])

        from app.utils.image_helper import get_sword_image_url
        img_url = get_sword_image_url(lvl, s_type)

        desc = (
            f"등급: +{lvl}강 ({type_name})\n"
            f"🔮 변환 획득: +{relic_pts}pt 유물 포인트\n"
            f"(참고: 판매 시 {sell_p:,}G)\n\n"
            f"이 검을 분해하여 유물 포인트로 변환하시겠습니까?"
        )
        card_item = {
            "title": f"[{idx+1}번 검] +{lvl} {type_name}",
            "description": desc,
            "buttons": [
                {"action": "message", "label": f"🔮 {idx+1}번 검 변환하기", "messageText": f"{idx+1}번 변환"},
                {"action": "message", "label": "🏺 유물 상점 가기", "messageText": "유물보기"}
            ]
        }
        if img_url:
            card_item["thumbnail"] = {
                "imageUrl": img_url,
                "fixedRatio": True,
                "width": 800,
                "height": 800
            }
        cards.append(card_item)

    return KakaoResponseBuilder.carousel(cards[:5])

@router.post("/shop")
async def view_shop(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """골드 상점 & 유물 상점 안내 및 통합 발화 디스패처"""
    utterance = get_utterance(payload)

    # 발화 디스패치
    if utterance.startswith("아이템구매"):
        return await buy_item(payload, db)
    elif utterance in ["유물보기", "유물상점", "유물", "유물 상점"] or utterance.startswith("유물상점"):
        return await view_relics(payload, db)
    elif utterance.startswith("유물구매"):
        return await buy_relic(payload, db)

    user_key = get_user_key(payload)
    user = await RunService.get_or_create_user(db, user_key)
    run = await RunService.get_active_run(db, user.id)

    if not run or run.status != "playing":
        return KakaoResponseBuilder.no_active_game()

    # 일반 상점 / 유물 상점 선택 화면
    if utterance not in ["일반 상점", "일반상점", "골드 상점", "골드상점"]:
        return KakaoResponseBuilder.basic_card(
            title="🏪 대장간 상점",
            description=(
                f"어느 상점으로 이동하시겠습니까?\n\n"
                f"• 보유 골드: {run.gold:,}G\n"
                f"• 보유 유물 포인트: {run.relic_points}pt"
            ),
            buttons=[
                {"action": "message", "label": "💰 일반 상점 (골드)", "messageText": "일반 상점"},
                {"action": "message", "label": "🏺 유물 상점 (포인트)", "messageText": "유물 상점"}
            ]
        )

    round_mult = (config.rules.get("shop_price_multiplier", 1.4) ** (run.round - 1))
    ev_state = getattr(run, "round_event", None) or {}
    shop_discount = (ev_state.get("effect") or {}).get("shop_discount", 0.0) if ev_state.get("chosen") else 0.0

    # [일반 상점]: 골드로 구매하는 소모품 및 검 품목들만 깔끔하게 노출
    cards = []
    run_items = run.items or []
    for item in config.shop_items.values():
        price = int(item["base_price"] * round_mult * (1.0 - shop_discount))
        item_desc = item.get("description", "추가 검을 구매합니다.")
        max_per_round = item.get("max_per_round")
        limit_str = ""
        btn_label = f"{price:,}G로 구매"

        if max_per_round is not None:
            marker = f"_bought_r{run.round}_{item['id']}"
            bought_cnt = run_items.count(marker)
            limit_str = f"\n(이번 라운드 구매: {bought_cnt}/{max_per_round}회)"
            if bought_cnt >= max_per_round:
                btn_label = "🚫 이번 라운드 품절"

        desc = f"가격: {price:,}G (보유 골드: {run.gold:,}G)\n효과: {item_desc}{limit_str}"
        # 검 품목이면 해당 타입의 0강 이미지, 그 외는 normal 0강
        item_sword_type = item.get("target_id", "normal") if item.get("type") == "sword" else "normal"
        cards.append({
            "title": f"🏪 {item['name']}",
            "description": desc,
            "_sword_type": item_sword_type,
            "_sword_level": 0,
            "buttons": [
                {"action": "message", "label": btn_label, "messageText": f"아이템구매 {item['id']}"}
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
            return KakaoResponseBuilder.no_active_game()

        # 파싱: "아이템구매 sword_normal" 등
        item_id = utterance.replace("아이템구매", "").strip()
        item = config.shop_items.get(item_id)
        if not item:
            return KakaoResponseBuilder.simple_text("존재하지 않는 상점 품목입니다.")

        # 라운드당 구매 횟수 제한 체크
        max_per_round = item.get("max_per_round")
        if max_per_round is not None:
            marker = f"_bought_r{run.round}_{item_id}"
            bought_cnt = (run.items or []).count(marker)
            if bought_cnt >= max_per_round:
                return KakaoResponseBuilder.basic_card(
                    title="🚫 구매 횟수 제한",
                    description=f"[{item['name']}]은(는) 라운드당 최대 {max_per_round}회까지만 구매할 수 있습니다!\n다음 라운드에 다시 구매해주세요.",
                    buttons=[
                        {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                        {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"},
                        {"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"}
                    ]
                )

        round_mult = (config.rules.get("shop_price_multiplier", 1.4) ** (run.round - 1))
        ev_state = getattr(run, "round_event", None) or {}
        shop_discount = (ev_state.get("effect") or {}).get("shop_discount", 0.0) if ev_state.get("chosen") else 0.0
        price = int(item["base_price"] * round_mult * (1.0 - shop_discount))

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
            new_sword_type = item.get("target_id", "normal")
            swords = list(run.swords or [])
            new_id = max([s.get("id", 0) for s in swords], default=0) + 1
            swords.append({
                "id": new_id,
                "type": new_sword_type,
                "level": 0
            })
            run.swords = swords
            is_new_sw, new_titles = await CollectionService.register_sword(db, user.id, new_sword_type, 0)
            ach_titles = await AchievementService.on_buy_shop_item(db, user.id, run)
            new_titles.extend(ach_titles)
            await db.commit()

            from app.utils.image_helper import get_sword_image_url
            buy_img_url = get_sword_image_url(0, new_sword_type)

            new_note = ""
            if is_new_sw:
                new_note += f"\n🆕 NEW! [{item['name']} +0강] 도감 등록!"
            if new_titles:
                new_note += f"\n🏅 칭호 해금: {', '.join(new_titles)}"

            return KakaoResponseBuilder.basic_card(
                title=f"🗡️ {item['name']} 구매 완료!",
                description=f"{price:,}G를 지불하고 새로운 검을 획득했습니다.\n• 보유 골드: {run.gold:,}G\n• 보유 검: {len(run.swords)}개{new_note}",
                thumbnail_url=buy_img_url,
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
            if max_per_round is not None:
                items.append(f"_bought_r{run.round}_{item_id}")
            run.items = items
            flag_modified(run, "items")
            ach_titles = await AchievementService.on_buy_shop_item(db, user.id, run)
            await db.commit()

            ach_note = f"\n🏅 칭호 해금: {', '.join(ach_titles)}" if ach_titles else ""
            return KakaoResponseBuilder.basic_card(
                title=f"📦 {item['name']} 구매 완료!",
                description=f"{price:,}G를 지불하고 [{item['name']}]을(를) 인벤토리에 보관했습니다.\n• 효과: {item.get('description', '')}\n• 보유 골드: {run.gold:,}G{ach_note}",
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
        return KakaoResponseBuilder.no_active_game()

    utterance = get_utterance(payload)
    page = 2 if "2" in utterance else 1

    owned_relics = run.relics or []
    slots_used = len(owned_relics)
    max_slots = config.rules.get("relic_slots", 4)

    all_relics = list(config.relics.values())
    per_page = 8
    start_idx = (page - 1) * per_page
    page_relics = all_relics[start_idx:start_idx + per_page]

    cards = []

    # 첫 번째 카드: 유물 상점 안내 & 페이지 이동/검 변환 숏컷
    header_desc = (
        f"• 보유 포인트: {run.relic_points}pt\n"
        f"• 장착 유물: {slots_used}/{max_slots}개\n"
        f"• 페이지: {page}/2\n\n"
        f"불필요한 검을 [변환]하면 유물 포인트를 얻을 수 있습니다!"
    )
    header_buttons = [
        {"action": "message", "label": "🔮 검 변환하러 가기", "messageText": "검변환"}
    ]
    if page == 1 and len(all_relics) > per_page:
        header_buttons.append({"action": "message", "label": "➡️ 다음 유물 보기 (2/2)", "messageText": "유물상점 2"})
    elif page == 2:
        header_buttons.append({"action": "message", "label": "⬅️ 이전 유물 보기 (1/2)", "messageText": "유물상점"})

    cards.append({
        "title": f"🏺 유물 보관소 & 상점 ({page}/2)",
        "description": header_desc,
        "buttons": header_buttons
    })

    for r in page_relics:
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

    return KakaoResponseBuilder.carousel(cards[:10])

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
            return KakaoResponseBuilder.no_active_game()

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

        is_new_rel, new_titles = await CollectionService.register_relic(db, user.id, relic_id)
        ach_titles = await AchievementService.on_buy_relic(db, user.id, run)
        new_titles.extend(ach_titles)
        await db.commit()

        new_note = ""
        if is_new_rel:
            new_note += f"\n🆕 NEW! [{relic['name']}] 유물 도감 등록!"
        if new_titles:
            new_note += f"\n🏅 칭호 해금: {', '.join(new_titles)}"

        return KakaoResponseBuilder.basic_card(
            title=f"✨ {relic['name']} 장착 완료!",
            description=f"신비한 유물이 활성화되었습니다!\n• 효과: {relic['description']}\n• 남은 포인트: {run.relic_points}pt\n• 장착 슬롯: {len(owned)}/{max_slots}개{new_note}",
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

    # 장착 칭호 일괄 조회
    meta_stmt = select(UserMeta).where(UserMeta.user_id.in_(friend_ids))
    meta_res = await db.execute(meta_stmt)
    meta_map = {m.user_id: m for m in meta_res.scalars().all()}

    if rank_records and len(friend_rows) >= 1 and rank_records[0][1].id == user.id:
        await AchievementService.on_rank_first(db, user.id)
        await db.commit()

    leaderboard = []
    for idx, (rk, u) in enumerate(rank_records):
        me_tag = " (나)" if u.id == user.id else ""
        u_meta = meta_map.get(u.id)
        title_prefix = ""
        if u_meta and u_meta.equipped_title and u_meta.equipped_title in config.achievements:
            title_prefix = f"[{config.achievements[u_meta.equipped_title]['title']}] "
        leaderboard.append(f"{idx+1}위: {title_prefix}{u.nickname}{me_tag} - R{rk.best_round} / +{rk.best_level}강")

    rank_text = "\n".join(leaderboard) if leaderboard else "등록된 기록이 없습니다."
    my_meta = meta_map.get(user.id)
    my_title_str = config.achievements[my_meta.equipped_title]["title"] if (my_meta and my_meta.equipped_title in config.achievements) else "없음"

    desc = (
        f"👤 내 닉네임: {user.nickname} (칭호: {my_title_str})\n"
        f"🔑 내 친구 코드: {user.friend_code} ({len(friend_rows)}/10명)\n\n"
        f"🏆 [친구 랭킹 순위표]\n{rank_text}\n\n"
        f"• 닉네임 변경: '이름 [변경할이름]'\n"
        f"• 친구 등록: '친구추가 [코드]'"
    )
    return KakaoResponseBuilder.basic_card(
        title="🏆 대장간 친구 랭킹",
        description=desc,
        buttons=[
            {"action": "message", "label": "🏅 칭호 관리", "messageText": "칭호"},
            {"action": "message", "label": "✏️ 닉네임 변경 방법", "messageText": "이름변경"},
            {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"}
        ]
    )

@router.post("/set-nickname")
async def set_nickname(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """닉네임 변경 처리 (예: '이름 홍길동' 또는 '닉네임 홍길동')"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)

        # 발화에서 새 닉네임 추출
        clean_text = utterance
        for prefix in ["이름변경", "닉네임변경", "이름", "닉네임"]:
            if clean_text.startswith(prefix):
                clean_text = clean_text[len(prefix):].strip()
                break

        if not clean_text:
            return KakaoResponseBuilder.basic_card(
                title="✏️ 닉네임 변경 안내",
                description=(
                    f"현재 닉네임: [{user.nickname}]\n\n"
                    f"변경하시려면 채팅창에 다음과 같이 입력해주세요:\n"
                    f"👉 '이름 [원하는닉네임]'\n"
                    f"(예: 이름 전설의대장장이)\n\n"
                    f"※ 2~12자 이내로 설정 가능합니다."
                ),
                buttons=[
                    {"action": "message", "label": "🏆 랭킹 보기", "messageText": "자랑·랭킹"},
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
                ]
            )

        new_name = clean_text.replace(" ", "")
        if len(new_name) < 2 or len(new_name) > 12:
            return KakaoResponseBuilder.simple_text("닉네임은 2자 이상 12자 이하로 입력해주세요.")

        old_name = user.nickname
        user.nickname = new_name
        db.add(user)
        await db.commit()
        await db.refresh(user)

        return KakaoResponseBuilder.basic_card(
            title="✨ 닉네임 변경 완료!",
            description=f"닉네임이 성공적으로 변경되었습니다.\n• 이전: {old_name}\n• 변경: {new_name}\n\n이제 랭킹 순위표에 새로운 이름으로 표시됩니다!",
            buttons=[
                {"action": "message", "label": "🏆 랭킹 확인하기", "messageText": "자랑·랭킹"},
                {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"}
            ]
        )

@router.post("/add-friend")
async def add_friend(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """친구 코드 등록 처리 (유연한 발화 및 8자리 코드 자동 추출 지원)"""
    import re
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)

        # 1. 영문+숫자 8자리 코드 패턴 정규식으로 자동 탐색
        code = None
        match = re.search(r'\b[A-Za-z0-9]{8}\b', utterance)
        if match:
            code = match.group(0).upper()
        else:
            # 보조 파싱: '친구추가', '친구 추가' 뒷부분 추출
            clean = utterance
            for p in ["친구추가", "친구 추가", "친구", "코드", ":"]:
                clean = clean.replace(p, " ")
            clean = clean.strip().upper()
            if clean:
                code = clean.split()[0]

        if not code:
            return KakaoResponseBuilder.basic_card(
                title="🤝 친구 등록 안내",
                description=(
                    f"친구의 8자리 코드를 입력해주세요!\n\n"
                    f"👉 입력 예시:\n"
                    f"• '친구추가 A1B2C3D4'\n"
                    f"• 또는 그냥 8자리 코드만 입력\n\n"
                    f"🔑 나의 친구 코드: [{user.friend_code}]"
                ),
                buttons=[
                    {"action": "message", "label": "🏆 랭킹 보기", "messageText": "자랑·랭킹"},
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
                ]
            )

        if code == user.friend_code:
            return KakaoResponseBuilder.simple_text("자신의 친구 코드는 등록할 수 없습니다. 😅")

        # 대상 유저 검색
        stmt = select(User).where(User.friend_code == code)
        res = await db.execute(stmt)
        target_user = res.scalar_one_or_none()
        if not target_user:
            return KakaoResponseBuilder.simple_text(f"해당 친구 코드({code})의 유저를 찾을 수 없습니다. 코드를 다시 확인해주세요.")

        # 현재 친구 수 체크
        friend_stmt = select(Friend).where(Friend.user_id == user.id)
        f_res = await db.execute(friend_stmt)
        current_friends = f_res.scalars().all()
        if len(current_friends) >= 10:
            return KakaoResponseBuilder.simple_text("친구는 최대 10명까지만 등록할 수 있습니다.")

        # 이미 등록된 친구인지 체크
        if any(f.friend_user_id == target_user.id for f in current_friends):
            return KakaoResponseBuilder.simple_text(f"이미 친구로 등록된 유저입니다: [{target_user.nickname}]")

        # 쌍방 등록: 상대방 친구 목록에도 나를 자동 추가 (상호 친구 관계 형성)
        new_friend = Friend(user_id=user.id, friend_user_id=target_user.id)
        db.add(new_friend)

        # 상대방의 친구 목록 체크 후 상대방에게도 나를 친구로 추가
        target_friend_stmt = select(Friend).where(Friend.user_id == target_user.id)
        tf_res = await db.execute(target_friend_stmt)
        target_friends = tf_res.scalars().all()
        if len(target_friends) < 10 and not any(tf.friend_user_id == user.id for tf in target_friends):
            reciprocal_friend = Friend(user_id=target_user.id, friend_user_id=user.id)
            db.add(reciprocal_friend)

        ach_titles = await AchievementService.on_friend_added(db, user.id, len(current_friends) + 1)
        await db.commit()

        ach_note = f"\n🏅 칭호 해금: {', '.join(ach_titles)}" if ach_titles else ""
        return KakaoResponseBuilder.basic_card(
            title="🤝 친구 등록 성공!",
            description=(
                f"[{target_user.nickname}] 님과 친구가 되었습니다!\n\n"
                f"이제 친구 랭킹 순위표에서 서로의 최고 기록을 함께 확인할 수 있습니다.{ach_note}"
            ),
            buttons=[
                {"action": "message", "label": "🏆 랭킹 확인하기", "messageText": "자랑·랭킹"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
            ]
        )

@router.post("/delete-friend")
async def delete_friend(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """친구 삭제 처리 ('친구삭제 [이름/코드]' 또는 친구목록 조회)"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)

        # 내 친구 목록 조회
        stmt = (
            select(Friend, User)
            .join(User, Friend.friend_user_id == User.id)
            .where(Friend.user_id == user.id)
        )
        res = await db.execute(stmt)
        friend_rows = res.all()

        target_str = utterance
        for p in ["친구삭제", "친구 삭제", "삭제"]:
            target_str = target_str.replace(p, " ")
        target_str = target_str.strip()

        # 삭제 대상 입력이 없는 경우 -> 현재 친구 목록과 삭제 방법 안내
        if not target_str:
            if not friend_rows:
                return KakaoResponseBuilder.basic_card(
                    title="👥 등록된 친구 없음",
                    description="현재 등록된 친구가 없습니다.\n새로운 친구를 추가해보세요!",
                    buttons=[
                        {"action": "message", "label": "🏆 랭킹 보기", "messageText": "자랑·랭킹"},
                        {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
                    ]
                )

            friend_list_txt = "\n".join([f"• {u.nickname} (코드: {u.friend_code})" for f, u in friend_rows])
            return KakaoResponseBuilder.basic_card(
                title="🗑️ 친구 삭제 안내",
                description=(
                    f"현재 친구 목록 ({len(friend_rows)}/10명):\n{friend_list_txt}\n\n"
                    f"삭제할 친구의 닉네임이나 코드를 다음과 같이 입력하세요:\n"
                    f"👉 '친구삭제 [닉네임 또는 코드]'"
                ),
                buttons=[
                    {"action": "message", "label": "🏆 랭킹 보기", "messageText": "자랑·랭킹"},
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
                ]
            )

        # 대상 찾기 (닉네임 또는 친구코드로 매칭)
        target_friend_rel = None
        target_user = None
        for f, u in friend_rows:
            if target_str.upper() == u.friend_code.upper() or target_str == u.nickname:
                target_friend_rel = f
                target_user = u
                break

        if not target_friend_rel:
            return KakaoResponseBuilder.simple_text(f"내 친구 목록에서 [{target_str}] 님을 찾을 수 없습니다.")

        # 삭제 진행
        await db.delete(target_friend_rel)
        await db.commit()

        return KakaoResponseBuilder.basic_card(
            title="🗑️ 친구 삭제 완료",
            description=f"[{target_user.nickname}] 님이 친구 목록에서 삭제되었습니다.\n(남은 친구: {len(friend_rows)-1}/10명)",
            buttons=[
                {"action": "message", "label": "🏆 랭킹 순위표", "messageText": "자랑·랭킹"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
            ]
        )

@router.post("/event-choice")
async def handle_event_choice(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """라운드 이벤트 선택지 처리"""
    import random
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.get_active_run(db, user.id)

        if not run or run.status != "playing":
            return KakaoResponseBuilder.no_active_game()

        ev_state = dict(getattr(run, "round_event", None) or {})
        ev_id = ev_state.get("event_id")
        if not ev_id or ev_id not in config.round_events:
            return KakaoResponseBuilder.simple_text("현재 진행 중인 라운드 이벤트가 없습니다.")

        if ev_state.get("chosen"):
            return KakaoResponseBuilder.simple_text("이미 이번 라운드 이벤트를 선택했습니다!")

        choice_id = utterance.replace("이벤트선택", "").strip()
        ev_conf = config.round_events[ev_id]
        choice_conf = next((c for c in ev_conf.get("choices", []) if c["id"] == choice_id), None)
        if not choice_conf:
            return KakaoResponseBuilder.simple_text("유효하지 않은 이벤트 선택지입니다.")

        eff = choice_conf.get("effect") or {}
        counters = dict(getattr(run, "meta_counters", None) or {})
        result_desc = f"[{ev_conf['name']}] 선택: {choice_conf['label']}\n\n"

        # 1. 유물 포인트 -> 골드 교환 (떠돌이 상인)
        if "relic_points_cost" in eff:
            cost = eff["relic_points_cost"]
            if (run.relic_points or 0) < cost:
                return KakaoResponseBuilder.basic_card(
                    title="🔮 유물 포인트 부족",
                    description=f"유물 포인트가 부족합니다! (필요: {cost}pt / 보유: {run.relic_points or 0}pt)\n다른 선택지를 고르거나 검을 변환해 포인트를 모으세요.",
                    buttons=[
                        {"action": "message", "label": c["label"][:14], "messageText": f"이벤트선택 {c['id']}"}
                        for c in ev_conf.get("choices", []) if c["id"] != choice_id
                    ][:3]
                )
            run.relic_points -= cost
            gain = eff.get("gold_gain", 1000)
            run.gold = (run.gold or 0) + gain
            result_desc += f"유물 포인트 {cost}pt를 내고 {gain:,}G를 획득했습니다! (보유 골드: {run.gold:,}G)"

        # 2. 신비한 샘 (가장 높은 검 +1)
        elif "upgrade_best_sword" in eff:
            swords = list(run.swords or [])
            if not swords:
                result_desc += "보유한 검이 없어 샘물의 축복을 받을 수 없었습니다."
            else:
                best_idx = max(range(len(swords)), key=lambda i: swords[i].get("level", 0))
                swords[best_idx]["level"] = swords[best_idx].get("level", 0) + eff["upgrade_best_sword"]
                run.swords = [dict(s) for s in swords]
                flag_modified(run, "swords")
                result_desc += f"💧 {best_idx+1}번 검이 신비한 힘으로 +{swords[best_idx]['level']}강이 되었습니다!"

        # 3. 수상한 도박꾼 (1번 검 걸고 50% +2강 / 소멸)
        elif eff.get("gamble_sword"):
            swords = list(run.swords or [])
            if not swords:
                result_desc += "걸 수 있는 검이 없어 도박이 성립하지 않았습니다."
            else:
                target = swords[0]
                if random.random() < 0.5:
                    target["level"] = target.get("level", 0) + 2
                    run.swords = [dict(s) for s in swords]
                    flag_modified(run, "swords")
                    counters["gamble_streak"] = counters.get("gamble_streak", 0) + 1
                    result_desc += f"🎉 도박 대성공!! 1번 검이 +{target['level']}강으로 뛰어올랐습니다!"
                else:
                    swords.pop(0)
                    run.swords = [dict(s) for s in swords]
                    flag_modified(run, "swords")
                    counters["gamble_streak"] = 0
                    counters["gamble_lost"] = True
                    result_desc += "💀 도박 실패... 1번 검이 흔적도 없이 소멸했습니다!"

        # 4. 기타 라운드 지속 효과 / 무시
        elif eff:
            effects_txt = []
            if "great_success_add" in eff:
                effects_txt.append(f"대성공 확률 +{int(eff['great_success_add']*100)}%p")
            if "destroy_add" in eff:
                effects_txt.append(f"파괴 확률 +{int(eff['destroy_add']*100)}%p")
            if "sell_multiplier" in eff:
                effects_txt.append(f"검 판매가 +{int((eff['sell_multiplier']-1)*100)}%")
            if "shop_discount" in eff:
                effects_txt.append(f"상점 아이템 {int(eff['shop_discount']*100)}% 할인")
            if eff.get("guaranteed_first_success"):
                effects_txt.append("이번 라운드 첫 강화 100% 성공")
            result_desc += "이번 라운드에 효과가 적용됩니다:\n• " + "\n• ".join(effects_txt)
        else:
            result_desc += "아무 일도 일어나지 않았습니다. 평온하게 강화를 시작합니다."

        ev_state["chosen"] = True
        ev_state["choice_id"] = choice_id
        ev_state["effect"] = eff
        run.round_event = ev_state
        run.meta_counters = counters
        flag_modified(run, "round_event")
        flag_modified(run, "meta_counters")

        # 도감 등록 (이벤트 + 혹시 레벨업된 검)
        is_new_ev, new_titles_ev = await CollectionService.register_event(db, user.id, ev_id)
        if is_new_ev:
            result_desc += f"\n🆕 NEW! [{ev_conf['name']}] 이벤트 도감 등록!"
        for sw in (run.swords or []):
            is_new_sw, nt = await CollectionService.register_sword(db, user.id, sw.get("type", "normal"), sw.get("level", 0))
            if is_new_sw:
                result_desc += f"\n🆕 NEW! [+{sw.get('level', 0)}강] 도감 등록!"
            new_titles_ev.extend(nt)
        if eff.get("gamble_sword"):
            new_titles_ev.extend(await AchievementService.on_gamble_event(db, user.id, counters))
        if new_titles_ev:
            result_desc += f"\n🏅 칭호 해금: {', '.join(dict.fromkeys(new_titles_ev))}"

        await db.commit()

        return KakaoResponseBuilder.basic_card(
            title=f"🎲 {ev_conf['name']} 결과",
            description=result_desc,
            buttons=[
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"},
                {"action": "message", "label": "🏪 상점 가기", "messageText": "상점 가기"}
            ]
        )


@router.post("/collection")
async def view_collection(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """도감 조회 (검 / 유물 / 이벤트 / 전체 완성도)"""
    from app.services.collection_service import MAX_CATALOG_SWORD_LEVEL
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    user = await RunService.get_or_create_user(db, user_key)
    meta = await CollectionService.get_or_create_meta(db, user.id)
    await db.commit()

    collected_cnt, total_cnt, pct = CollectionService.calculate_completion(meta)

    if "검" in utterance:
        collected_swords = set(meta.collected_swords or [])
        lines = []
        for stype, sconf in config.sword_types.items():
            name = sconf.get("name", stype)
            marks = []
            found = 0
            for lvl in range(MAX_CATALOG_SWORD_LEVEL + 1):
                if f"{stype}:{lvl}" in collected_swords:
                    marks.append(f"+{lvl}")
                    found += 1
                else:
                    marks.append("?")
            lines.append(f"[{name}] ({found}/{MAX_CATALOG_SWORD_LEVEL + 1})\n" + " ".join(marks))
        desc = "\n\n".join(lines)
        return KakaoResponseBuilder.basic_card(
            title=f"🗡️ 검 도감 (전체 {pct}%)",
            description=desc[:390],
            buttons=[
                {"action": "message", "label": "🏺 유물 도감", "messageText": "유물 도감"},
                {"action": "message", "label": "🎲 이벤트 도감", "messageText": "이벤트 도감"},
                {"action": "message", "label": "📚 도감 요약", "messageText": "도감"}
            ]
        )

    if "유물" in utterance:
        collected_relics = set(meta.collected_relics or [])
        lines = []
        for rid, rconf in config.relics.items():
            if rid in collected_relics:
                lines.append(f"✅ {rconf['name']} — {rconf['description']}")
            else:
                lines.append("⬛ ??? (미발견 유물)")
        return KakaoResponseBuilder.basic_card(
            title=f"🏺 유물 도감 ({len(collected_relics & set(config.relics.keys()))}/{len(config.relics)})",
            description="\n".join(lines)[:390],
            buttons=[
                {"action": "message", "label": "🗡️ 검 도감", "messageText": "검 도감"},
                {"action": "message", "label": "🎲 이벤트 도감", "messageText": "이벤트 도감"},
                {"action": "message", "label": "📚 도감 요약", "messageText": "도감"}
            ]
        )

    if "이벤트" in utterance:
        collected_events = set(meta.collected_events or [])
        lines = []
        for eid, econf in config.round_events.items():
            if eid in collected_events:
                lines.append(f"✅ {econf['name']} ({econf['category']})")
            else:
                lines.append("⬛ ??? (미발견 이벤트)")
        return KakaoResponseBuilder.basic_card(
            title=f"🎲 이벤트 도감 ({len(collected_events & set(config.round_events.keys()))}/{len(config.round_events)})",
            description="\n".join(lines)[:390],
            buttons=[
                {"action": "message", "label": "🗡️ 검 도감", "messageText": "검 도감"},
                {"action": "message", "label": "🏺 유물 도감", "messageText": "유물 도감"},
                {"action": "message", "label": "📚 도감 요약", "messageText": "도감"}
            ]
        )

    # 기본: 도감 전체 요약
    sw_cnt = sum(
        1 for k in set(meta.collected_swords or [])
        if ":" in k and k.split(":")[0] in config.sword_types and 0 <= int(k.split(":")[1]) <= MAX_CATALOG_SWORD_LEVEL
    )
    sw_total = len(config.sword_types) * (MAX_CATALOG_SWORD_LEVEL + 1)
    rel_cnt = len(set(meta.collected_relics or []) & set(config.relics.keys()))
    ev_cnt = len(set(meta.collected_events or []) & set(config.round_events.keys()))

    desc = (
        f"📊 전체 도감 완성도: {pct}% ({collected_cnt}/{total_cnt})\n\n"
        f"• 🗡️ 검 도감: {sw_cnt}/{sw_total}\n"
        f"• 🏺 유물 도감: {rel_cnt}/{len(config.relics)}\n"
        f"• 🎲 이벤트 도감: {ev_cnt}/{len(config.round_events)}\n\n"
        f"완성도 25% / 50% / 100% 달성 시 특별 칭호가 지급됩니다!"
    )
    return KakaoResponseBuilder.basic_card(
        title="📚 대장간 도감",
        description=desc,
        buttons=[
            {"action": "message", "label": "🗡️ 검 도감", "messageText": "도감:검"},
            {"action": "message", "label": "🏺 유물 도감", "messageText": "도감:유물"},
            {"action": "message", "label": "🎲 이벤트 도감", "messageText": "도감:이벤트"}
        ]
    )


@router.post("/titles")
async def manage_titles(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """칭호 / 업적 조회 및 칭호 장착/해제"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    user = await RunService.get_or_create_user(db, user_key)
    meta = await CollectionService.get_or_create_meta(db, user.id)

    # 칭호 장착 처리: "칭호장착 ach_01" 또는 "칭호장착 운 좋은 대장장이"
    if utterance.startswith("칭호장착"):
        target = utterance.replace("칭호장착", "").strip()
        unlocked = set(meta.unlocked_titles or [])
        matched_id = None
        if target in unlocked and target in config.achievements:
            matched_id = target
        else:
            for aid in unlocked:
                if aid in config.achievements and config.achievements[aid]["title"] == target:
                    matched_id = aid
                    break
        if not matched_id:
            return KakaoResponseBuilder.simple_text("해금되지 않았거나 존재하지 않는 칭호입니다.")
        meta.equipped_title = matched_id
        await db.commit()
        title_name = config.achievements[matched_id]["title"]
        return KakaoResponseBuilder.basic_card(
            title="🏅 칭호 장착 완료!",
            description=f"[{title_name}] 칭호를 장착했습니다!\n이제 친구 랭킹에서 [{title_name}] {user.nickname} 으로 표시됩니다.",
            buttons=[
                {"action": "message", "label": "🏆 랭킹 확인", "messageText": "자랑·랭킹"},
                {"action": "message", "label": "🏅 칭호 목록", "messageText": "칭호"}
            ]
        )

    if utterance in ["칭호해제", "칭호 해제"]:
        meta.equipped_title = None
        await db.commit()
        return KakaoResponseBuilder.basic_card(
            title="🏅 칭호 해제 완료",
            description="장착 중인 칭호를 해제했습니다.",
            buttons=[{"action": "message", "label": "🏅 칭호 목록", "messageText": "칭호"}]
        )

    await db.commit()

    unlocked = list(meta.unlocked_titles or [])
    unlocked_set = set(unlocked)
    equipped_name = config.achievements[meta.equipped_title]["title"] if (meta.equipped_title in config.achievements) else "없음"

    # 페이지 처리 ("업적 2", "칭호 2" 등)
    page = 1
    for p_num in ["2", "3", "4", "5"]:
        if p_num in utterance:
            page = int(p_num)
            break

    all_achs = list(config.achievements.values())
    per_page = 8
    total_pages = max(1, (len(all_achs) + per_page - 1) // per_page)
    page = min(page, total_pages)
    slice_achs = all_achs[(page - 1) * per_page : page * per_page]

    lines = [f"현재 장착: [{equipped_name}] ({len(unlocked_set)}/{len(all_achs)} 달성)\n"]
    for a in slice_achs:
        is_ok = a["id"] in unlocked_set
        if is_ok:
            eq_mark = " ★장착중" if meta.equipped_title == a["id"] else ""
            lines.append(f"✅ [{a['title']}]{eq_mark} - {a['condition']}")
        elif a.get("hidden"):
            lines.append("🔒 [???] - ??? (숨김 업적)")
        else:
            lines.append(f"⬜ [{a['title']}] - {a['condition']}")

    lines.append("\n💡 장착 방법: '칭호장착 [칭호이름]' 입력")

    buttons = []
    # 보유 중인 칭호 중 아직 미장착된 칭호 1개를 바로 장착 버튼으로 제공
    for aid in unlocked:
        if aid != meta.equipped_title and aid in config.achievements:
            tname = config.achievements[aid]["title"]
            buttons.append({"action": "message", "label": f"🏅 [{tname}] 장착", "messageText": f"칭호장착 {aid}"})
            break
    if page < total_pages:
        buttons.append({"action": "message", "label": f"➡️ 다음 ({page+1}/{total_pages})", "messageText": f"칭호 {page+1}"})
    elif page > 1:
        buttons.append({"action": "message", "label": f"⬅️ 이전 ({page-1}/{total_pages})", "messageText": f"칭호 {page-1}"})
    buttons.append({"action": "message", "label": "🏆 친구 랭킹", "messageText": "자랑·랭킹"})

    return KakaoResponseBuilder.basic_card(
        title=f"🏅 칭호 & 업적 ({page}/{total_pages})",
        description="\n".join(lines)[:395],
        buttons=buttons[:3]
    )


@router.post("/menu")
async def show_more_menu(payload: Dict[str, Any] = None):
    """더보기 / 전체 메뉴 안내 카드"""
    return KakaoResponseBuilder.basic_card(
        title="📋 대장간 더보기 메뉴",
        description="원하시는 기능을 선택해주세요!",
        buttons=[
            {"action": "message", "label": "📚 도감 보기", "messageText": "도감"},
            {"action": "message", "label": "🏅 칭호 & 업적", "messageText": "칭호"},
            {"action": "message", "label": "📖 게임 규칙", "messageText": "규칙"}
        ]
    )


@router.post("/fallback")
async def fallback_handler(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """
    카카오 오픈빌더 폴백 블록 전용 만능 인터셉터
    사용자가 오픈빌더 미인식 발화를 입력했을 때 서버가 낚아채서 처리
    """
    try:
        utterance = get_utterance(payload)

        # 0. 더보기 메뉴 & 상점/구매 & 라운드 이벤트 선택 & 도감 & 칭호/업적 조회
        if utterance in ["더보기", "메뉴", "전체메뉴", "전체 메뉴"]:
            return await show_more_menu(payload)
        if utterance.startswith("아이템구매"):
            return await buy_item(payload, db)
        if utterance.startswith("유물구매"):
            return await buy_relic(payload, db)
        if utterance in ["상점 가기", "상점가기", "상점", "상점·유물", "일반 상점", "일반상점", "골드 상점", "골드상점", "유물 상점", "유물상점", "유물보기"]:
            return await view_shop(payload, db)
        if utterance.startswith("이벤트선택"):
            return await handle_event_choice(payload, db)
        if utterance.startswith("도감") or utterance in ["검 도감", "검도감", "유물 도감", "유물도감", "이벤트 도감", "이벤트도감"]:
            return await view_collection(payload, db)
        if utterance.startswith("칭호") or utterance.startswith("업적"):
            return await manage_titles(payload, db)

        # 1. 친구 추가 관련
        if "친구추가" in utterance or "친구 추가" in utterance:
            return await add_friend(payload, db)

        # 2. 친구 삭제 관련
        if "친구삭제" in utterance or "친구 삭제" in utterance or utterance in ["친구목록", "친구 목록"]:
            return await delete_friend(payload, db)

        # 3. 닉네임 변경 관련
        if utterance.startswith("이름") or utterance.startswith("닉네임"):
            return await set_nickname(payload, db)

        # 4. 8자리 영숫자 단독 입력인 경우 -> 친구추가로 처리
        import re
        if re.fullmatch(r'[A-Za-z0-9]{8}', utterance.strip()):
            return await add_friend(payload, db)

        # 5. 검 변환 관련
        if "변환" in utterance:
            return await transform_menu(payload, db)

        # 그 외 진짜 알 수 없는 발화
        return KakaoResponseBuilder.basic_card(
            title="🤔 대장장이가 이해하지 못했습니다",
            description=(
                f"입력하신 내용: '{utterance}'\n\n"
                f"아래 메뉴 중 원하시는 행동을 선택해주세요!"
            ),
            buttons=[
                {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                {"action": "message", "label": "📖 게임 규칙", "messageText": "규칙"}
            ]
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return KakaoResponseBuilder.simple_text("일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

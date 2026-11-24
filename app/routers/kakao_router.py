from pathlib import Path
from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.utils.kakao_builder import KakaoResponseBuilder
from app.services.run_service import RunService
from app.services.game_engine import GameEngine
from app.core.config import config
from app.utils.image_helper import get_sword_image_url
from app.models.game import EnhanceLog
from app.utils.lock_manager import UserLockManager
from typing import Dict, Any

router = APIRouter(prefix="/api/kakao", tags=["kakao"])

def get_user_key(payload: Dict[str, Any]) -> str:
    user_req = payload.get("userRequest", {})
    user = user_req.get("user", {})
    return user.get("id", "anonymous_user")

def get_utterance(payload: Dict[str, Any]) -> str:
    return payload.get("userRequest", {}).get("utterance", "").strip()

@router.post("/start")
async def start_game(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """게임 시작 / 새 게임 블록"""
    user_key = get_user_key(payload)
    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.start_new_run(db, user.id)

        target_gold = GameEngine.get_target_gold_for_round(run.round)
        title = f"⚔️ 검 강화 대장간 (R{run.round}/{config.rules.get('max_round', 10)})"
        desc = (
            f"새로운 모험이 시작되었습니다!\n"
            f"• 기본 검 {len(run.swords)}개 지급\n"
            f"• 현재 골드: {run.gold:,}G\n"
            f"• 이번 라운드 목표: {target_gold:,}G\n\n"
            f"하단의 [강화하기] 또는 [내 검 보기]를 눌러 검을 골라보세요!"
        )
        return KakaoResponseBuilder.basic_card(
            title=title,
            description=desc,
            buttons=[
                {"action": "message", "label": "🗡️ 강화할 검 고르기", "messageText": "강화하기"},
                {"action": "message", "label": "📖 게임 규칙", "messageText": "규칙"}
            ]
        )

@router.post("/my-swords")
async def view_my_swords(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """보유 검 목록 보기"""
    user_key = get_user_key(payload)
    user = await RunService.get_or_create_user(db, user_key)
    run = await RunService.get_active_run(db, user.id)

    if not run or run.status != "playing":
        return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다. [새 게임]을 눌러 시작해주세요.")

    if not run.swords:
        target_gold = GameEngine.get_target_gold_for_round(run.round)
        can_advance = run.gold >= target_gold
        desc = "모든 검이 파괴되었거나 판매되었습니다.\n\n"
        buttons = []
        if "revert_destroy" in (run.items or []) and run.last_destroyed_sword:
            lvl = run.last_destroyed_sword.get("level", 0)
            buttons.append({"action": "message", "label": f"🔮 +{lvl}강 복구하기", "messageText": "되돌리기 사용"})

        if can_advance:
            desc += f"현재 보유 골드({run.gold:,}G)가 목표({target_gold:,}G)를 달성했습니다!\n[납품·마감]하여 다음 라운드로 진행할 수 있습니다."
            buttons.append({"action": "message", "label": "📦 납품·마감", "messageText": "납품·마감"})
            buttons.append({"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"})
        else:
            desc += f"목표 골드: {target_gold:,}G (보유: {run.gold:,}G)\n상점에서 검을 추가로 구매하거나 새 게임을 시작하세요."
            buttons.append({"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"})
            buttons.append({"action": "message", "label": "🔄 새 게임", "messageText": "새 게임"})

        return KakaoResponseBuilder.basic_card(
            title="🗡️ 보유한 검이 없습니다!",
            description=desc,
            buttons=buttons[:3]
        )

    cards = []
    for idx, sword in enumerate(run.swords):
        lvl = sword.get("level", 0)
        s_type = sword.get("type", "normal")
        type_name = config.sword_types.get(s_type, {}).get("name", "기본 검")
        sell_p = GameEngine.calculate_sell_price(sword, run.relics or [])
        relic_pts = GameEngine.calculate_relic_points(sword)
        probs = GameEngine.calculate_enhance_probabilities(lvl, run.relics or [], run.boost or 0)

        desc = (
            f"등급: +{lvl}강 ({type_name})\n"
            f"판매가: {sell_p:,}G | 변환: {relic_pts}pt\n"
            f"확률: 성 {int(probs['success']*100)}% / 대성 {int(probs['great_success']*100)}% / "
            f"유지 {int(probs['keep']*100)}% / 파괴 {int(probs['destroy']*100)}%"
        )
        img_url = get_sword_image_url(lvl, s_type)
        cards.append({
            "title": f"[{idx+1}번 검] +{lvl} {type_name}",
            "description": desc,
            "thumbnail": {"imageUrl": img_url} if img_url else None,
            "buttons": [
                {"action": "message", "label": f"{idx+1}번 검 강화", "messageText": f"{idx+1}번 강화"},
                {"action": "message", "label": f"{idx+1}번 판매", "messageText": f"{idx+1}번 판매"},
                {"action": "message", "label": f"{idx+1}번 변환", "messageText": f"{idx+1}번 변환"}
            ]
        })

    return KakaoResponseBuilder.carousel(cards[:5]) # 카카오 캐러셀 최대 5개

@router.post("/enhance")
async def enhance_sword(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """검 강화 엔드포인트 (동시성 락 & 0개 검 예외 처리 & 되돌리기 지원)"""
    user_key = get_user_key(payload)
    utterance = get_utterance(payload)

    # 규칙 발화 체크
    if utterance == "규칙":
        return await show_rules()

    # 되돌리기 발화 체크
    if utterance == "되돌리기 사용":
        return await revert_destroyed_sword(payload, db)

    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.get_active_run(db, user.id)

        if not run or run.status != "playing":
            return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다. [새 게임]을 눌러 시작해주세요.")

        # 보유 검 0개 예외 처리
        if not run.swords:
            target_gold = GameEngine.get_target_gold_for_round(run.round)
            can_advance = run.gold >= target_gold
            desc = "현재 강화할 수 있는 검이 없습니다!\n모든 검이 파괴되었거나 판매되었습니다.\n\n"
            buttons = []
            if "revert_destroy" in (run.items or []) and run.last_destroyed_sword:
                buttons.append({"action": "message", "label": "🔮 되돌리기 사용", "messageText": "되돌리기 사용"})

            if can_advance:
                desc += f"현재 골드({run.gold:,}G)가 라운드 목표({target_gold:,}G)를 달성했습니다!\n[납품·마감]하여 다음 라운드로 넘어가세요."
                buttons.append({"action": "message", "label": "📦 납품·마감", "messageText": "납품·마감"})
                buttons.append({"action": "message", "label": "🏪 상점에서 검 구매", "messageText": "상점·유물"})
            else:
                desc += f"목표 골드: {target_gold:,}G (보유: {run.gold:,}G)\n상점에서 검을 추가로 구매하거나 새 게임을 시작하세요."
                buttons.append({"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"})
                buttons.append({"action": "message", "label": "🔄 새 게임", "messageText": "새 게임"})

            return KakaoResponseBuilder.basic_card(
                title="🗡️ 강화할 검이 없습니다!",
                description=desc,
                buttons=buttons[:3]
            )

        # 검 번호 파싱 (예: "1번 강화", 없으면 기본 1번 검)
        sword_idx = 0
        words = utterance.split()
        for w in words:
            if "번" in w and w.replace("번", "").isdigit():
                sword_idx = int(w.replace("번", "")) - 1
                break

        if sword_idx < 0 or sword_idx >= len(run.swords):
            sword_idx = 0

        try:
            prev_level = run.swords[sword_idx].get("level", 0)
            s_type = run.swords[sword_idx].get("type", "normal")
            result, details = GameEngine.enhance_sword(run, sword_idx)

            # 로그 저장
            log = EnhanceLog(
                user_id=user.id,
                run_id=run.id,
                sword_type=s_type,
                from_level=prev_level,
                to_level=details["to_level"],
                result=result
            )
            db.add(log)
            await db.commit()

            # 결과 카드 문구
            if result == "success":
                title = f"✨ 강화 성공! (+{details['to_level']}강)"
                desc = f"+{prev_level}강에서 +{details['to_level']}강으로 상승했습니다!"
            elif result == "great_success":
                title = f"💥 대성공 폭발! (+{details['to_level']}강)"
                desc = f"엄청난 기운으로 레벨이 대폭 상승했습니다! (+{prev_level} → +{details['to_level']})"
            elif result == "keep":
                title = "🛡️ 강화 유지"
                if details.get("protected_by"):
                    desc = f"파괴 위험이었으나 [{details['protected_by']}] 효과로 검을 지켰습니다!"
                else:
                    desc = f"아쉽게도 레벨에 변화가 없습니다. (+{prev_level}강 유지)"
            else: # destroy
                if len(run.swords) == 0:
                    title = "💥 콰앙! 마지막 검이 파괴되었습니다..."
                    target_gold = GameEngine.get_target_gold_for_round(run.round)
                    if run.gold >= target_gold:
                        desc = f"+{prev_level}강 검이 파괴되었습니다. (남은 검: 0개)\n\n다행히 보유 골드({run.gold:,}G)가 목표({target_gold:,}G)를 충족합니다! [납품·마감]이 가능합니다."
                    else:
                        desc = f"+{prev_level}강 검이 파괴되었습니다. (남은 검: 0개)\n\n모든 검을 잃었습니다. 상점에서 검을 구매하거나 새 게임을 시작해주세요."
                else:
                    title = "💨 콰앙! 검이 파괴되었습니다..."
                    desc = f"+{prev_level}강 검이 산산조각 났습니다. (남은 검: {len(run.swords)}개)"

            buttons = []
            if result != "destroy":
                buttons.append({"action": "message", "label": f"{sword_idx+1}번 계속 강화", "messageText": f"{sword_idx+1}번 강화"})
                buttons.append({"action": "message", "label": f"{sword_idx+1}번 판매", "messageText": f"{sword_idx+1}번 판매"})
                buttons.append({"action": "message", "label": f"{sword_idx+1}번 변환", "messageText": f"{sword_idx+1}번 변환"})
            else:
                if "revert_destroy" in (run.items or []):
                    buttons.append({"action": "message", "label": "🔮 되돌리기 사용", "messageText": "되돌리기 사용"})

                if len(run.swords) == 0:
                    target_gold = GameEngine.get_target_gold_for_round(run.round)
                    if run.gold >= target_gold:
                        buttons.append({"action": "message", "label": "📦 납품·마감", "messageText": "납품·마감"})
                    buttons.append({"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"})
                    if run.gold < target_gold and len(buttons) < 3:
                        buttons.append({"action": "message", "label": "🔄 새 게임", "messageText": "새 게임"})
                else:
                    buttons.append({"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"})
                    buttons.append({"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"})

            result_img_url = get_sword_image_url(details["to_level"], s_type) if result != "destroy" else None
            return KakaoResponseBuilder.basic_card(
                title=title,
                description=desc,
                thumbnail_url=result_img_url,
                buttons=buttons[:3]
            )

        except Exception as e:
            return KakaoResponseBuilder.simple_text(f"강화 중 오류가 발생했습니다: {str(e)}")

@router.post("/revert")
async def revert_destroyed_sword(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """파괴된 검 복구(되돌리기) 엔드포인트"""
    user_key = get_user_key(payload)
    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.get_active_run(db, user.id)

        if not run or run.status != "playing":
            return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

        items = list(run.items or [])
        if "revert_destroy" not in items:
            return KakaoResponseBuilder.basic_card(
                title="🔮 복구 실패",
                description="보유 중인 [파괴 되돌리기 주문서]가 없습니다!\n상점에서 구매 후 이용해주세요.",
                buttons=[{"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"}]
            )

        if not run.last_destroyed_sword:
            return KakaoResponseBuilder.basic_card(
                title="🔮 복구 실패",
                description="복구할 수 있는 파괴된 검 기록이 없습니다.",
                buttons=[{"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}]
            )

        destroyed = run.last_destroyed_sword
        lvl = destroyed.get("level", 0)
        s_type = destroyed.get("type", "normal")
        type_name = config.sword_types.get(s_type, {}).get("name", "기본 검")

        # 검 복원
        swords = list(run.swords or [])
        new_id = max([s.get("id", 0) for s in swords], default=0) + 1
        swords.append({"id": new_id, "type": s_type, "level": lvl})
        run.swords = swords

        # 주문서 소모 & 마지막 파괴 검 리셋
        items.remove("revert_destroy")
        run.items = items
        run.last_destroyed_sword = None
        if run.destroyed_count and run.destroyed_count > 0:
            run.destroyed_count -= 1
        await db.commit()

        restored_idx = len(swords)
        img_url = get_sword_image_url(lvl, s_type)
        return KakaoResponseBuilder.basic_card(
            title="🔮 기적의 검 복구 성공!",
            description=f"신비한 주문서의 힘으로 +{lvl}강 {type_name}이(가) 완벽히 복원되었습니다!\n(보유 검: {len(swords)}개)",
            thumbnail_url=img_url,
            buttons=[
                {"action": "message", "label": f"{restored_idx}번 계속 강화", "messageText": f"{restored_idx}번 강화"},
                {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                {"action": "message", "label": "🏪 상점 가기", "messageText": "상점·유물"}
            ]
        )

@router.post("/round-finish")
async def finish_round(payload: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    """납품 및 라운드 마감"""
    user_key = get_user_key(payload)
    async with UserLockManager.acquire(user_key, timeout=0.3) as acquired:
        if not acquired:
            return KakaoResponseBuilder.simple_text("⚡ 이전 요청을 처리 중입니다! 잠시 후 다시 시도해주세요.")

        user = await RunService.get_or_create_user(db, user_key)
        run = await RunService.get_active_run(db, user.id)

        if not run or run.status != "playing":
            return KakaoResponseBuilder.simple_text("진행 중인 게임이 없습니다.")

        success, msg = await RunService.advance_round(db, run)
        if not success:
            return KakaoResponseBuilder.basic_card(
                title="💀 납품 실패 (게임 오버)",
                description=msg,
                buttons=[{"action": "message", "label": "🔄 다시 도전하기", "messageText": "새 게임"}]
            )
        elif run.status == "cleared":
            return KakaoResponseBuilder.basic_card(
                title="🎉 게임 클리어!",
                description=msg,
                buttons=[
                    {"action": "message", "label": "🏆 자랑하기", "messageText": "자랑·랭킹"},
                    {"action": "message", "label": "🔄 새 게임 시작", "messageText": "새 게임"}
                ]
            )
        else:
            target_gold = GameEngine.get_target_gold_for_round(run.round)
            desc = f"{msg}\n• 보유 골드: {run.gold:,}G\n• R{run.round} 목표 골드: {target_gold:,}G"
            return KakaoResponseBuilder.basic_card(
                title=f"📦 R{run.round} 라운드 진입",
                description=desc,
                buttons=[
                    {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"},
                    {"action": "message", "label": "⚔️ 강화하기", "messageText": "강화하기"}
                ]
            )

@router.post("/rules")
async def show_rules(payload: Dict[str, Any] = None):
    """게임 규칙 안내"""
    desc = (
        "⚔️ [검 강화 대장간 가이드]\n\n"
        "1. 🎯 목표: 매 라운드 납품 목표 골드를 달성하고 총 10라운드를 완주하세요!\n"
        "2. 🔨 강화: 검을 강화할수록 판매가(100G × 1.6^강화수)가 기하급수적으로 폭증합니다.\n"
        "3. 💥 파괴 주의: 레벨이 오를수록 파괴 확률이 높아집니다. 안전하게 분산 판매하거나 유물로 대비하세요.\n"
        "4. 🔮 유물 변환: 불필요한 검을 분해해 유물 포인트를 얻고, 강력한 패시브 유물 7종을 장착할 수 있습니다.\n"
        "5. 🏪 상점: 파괴 방지 부적, 되돌리기 주문서, 추가 검을 구매해 위기를 극복하세요!"
    )
    return KakaoResponseBuilder.basic_card(
        title="📖 게임 규칙 안내",
        description=desc,
        buttons=[
            {"action": "message", "label": "🗡️ 강화하러 가기", "messageText": "강화하기"},
            {"action": "message", "label": "🗡️ 내 검 보기", "messageText": "내 검 보기"}
        ]
    )

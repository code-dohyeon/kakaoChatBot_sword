"""
이미지 반영 범위 검증 테스트
- kakao_builder carousel 폴백 (카드별 _sword_type/_sword_level 적용)
- 판매 완료 카드 (s_type 반영)
- 구매 완료 카드 (new_sword_type 반영)
"""
import os, sys
sys.path.insert(0, ".")

# SERVER_BASE_URL 주입
import app.utils.image_helper as ih
ih.SERVER_BASE_URL = "https://test.onrender.com"

from app.utils.kakao_builder import KakaoResponseBuilder

print("=" * 60)
print("1. 캐러셀 폴백 썸네일 — 타입별 이미지 반영")
print("=" * 60)

# thumbnail 없는 카드에 _sword_type/_sword_level 메타 필드 사용
cards = [
    {
        "title": "기본 검",
        "description": "normal 타입",
        "_sword_type": "normal",
        "_sword_level": 5,
        "buttons": [{"action": "message", "label": "강화", "messageText": "강화"}]
    },
    {
        "title": "나뭇가지",
        "description": "stick 타입 (branch_0.png 폴백)",
        "_sword_type": "stick",
        "_sword_level": 3,  # branch_3.png 없음 -> branch_0.png
        "buttons": [{"action": "message", "label": "강화", "messageText": "강화"}]
    },
    {
        "title": "꼬챙이",
        "description": "skewer 타입",
        "_sword_type": "skewer",
        "_sword_level": 0,
        "buttons": [{"action": "message", "label": "강화", "messageText": "강화"}]
    },
]

result = KakaoResponseBuilder.carousel(cards)
items = result["template"]["outputs"][0]["carousel"]["items"]

for item in items:
    thumb = item.get("thumbnail", {}).get("imageUrl", "MISSING")
    # _sword_type/_sword_level 이 최종 응답에 남아있으면 안됨
    has_meta = "_sword_type" in item or "_sword_level" in item
    print(f"  [{item['title']}]")
    print(f"    썸네일: {thumb}")
    print(f"    메타 필드 제거됨: {'❌ 아직 있음!' if has_meta else '✅'}")
    print()

print("=" * 60)
print("2. basic_card — s_type 있는 경우")
print("=" * 60)

sell_img = ih.get_sword_image_url(5, "stick")
card = KakaoResponseBuilder.basic_card(
    title="💰 판매 완료",
    description="+5강 나뭇가지 판매",
    thumbnail_url=sell_img,
    buttons=[{"action": "message", "label": "내 검 보기", "messageText": "내 검 보기"}]
)
out = card["template"]["outputs"][0]
card_type = "basicCard" if "basicCard" in out else "textCard"
thumb = out.get("basicCard", {}).get("thumbnail", {}).get("imageUrl", "없음(textCard)")
print(f"  카드 타입: {card_type}")
print(f"  썸네일: {thumb}")
print()

print("=" * 60)
print("3. 메타 필드 없는 카드는 normal 0강으로 폴백")
print("=" * 60)

cards_no_meta = [
    {
        "title": "유물 상점",
        "description": "상점 카드 (메타 필드 없음)",
        "buttons": [{"action": "message", "label": "구매", "messageText": "구매"}]
    }
]
result2 = KakaoResponseBuilder.carousel(cards_no_meta)
item2 = result2["template"]["outputs"][0]["carousel"]["items"][0]
print(f"  썸네일: {item2.get('thumbnail', {}).get('imageUrl', 'MISSING')}")
print()

print("모든 테스트 완료! ✅")

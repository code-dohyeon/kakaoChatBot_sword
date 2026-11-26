from typing import List, Dict, Any, Optional

DEFAULT_QUICK_REPLIES = [
    {"label": "⚔️ 강화하기", "action": "message", "messageText": "강화하기"},
    {"label": "🗡️ 내 검 보기", "action": "message", "messageText": "내 검 보기"},
    {"label": "🏪 상점 가기", "action": "message", "messageText": "상점 가기"},
    {"label": "📦 납품·마감", "action": "message", "messageText": "납품·마감"},
    {"label": "🏆 자랑·랭킹", "action": "message", "messageText": "자랑·랭킹"},
    {"label": "📋 더보기", "action": "message", "messageText": "더보기"}
]

class KakaoResponseBuilder:
    @staticmethod
    def simple_text(text: str, quick_replies: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        replies = quick_replies if quick_replies is not None else DEFAULT_QUICK_REPLIES
        return {
            "version": "2.0",
            "template": {
                "outputs": [{"simpleText": {"text": text}}],
                "quickReplies": replies
            }
        }

    @staticmethod
    def basic_card(
        title: str,
        description: str,
        thumbnail_url: Optional[str] = None,
        buttons: Optional[List[Dict[str, Any]]] = None,
        quick_replies: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        replies = quick_replies if quick_replies is not None else DEFAULT_QUICK_REPLIES

        # 썸네일이 있으면 800x800 규격의 basicCard, 없으면 카카오 규격 textCard
        if thumbnail_url:
            card: Dict[str, Any] = {
                "title": title,
                "description": description,
                "thumbnail": {
                    "imageUrl": thumbnail_url,
                    "fixedRatio": True,
                    "width": 800,
                    "height": 800
                }
            }
            if buttons:
                card["buttons"] = buttons
            output = {"basicCard": card}
        else:
            card: Dict[str, Any] = {
                "title": title,
                "description": description
            }
            if buttons:
                card["buttons"] = buttons
            output = {"textCard": card}

        return {
            "version": "2.0",
            "template": {
                "outputs": [output],
                "quickReplies": replies
            }
        }

    @staticmethod
    def carousel(
        card_items: List[Dict[str, Any]],
        quick_replies: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        replies = quick_replies if quick_replies is not None else DEFAULT_QUICK_REPLIES
        
        # [카카오 2461 에러 방지]: carousel의 basicCard는 thumbnail이 필수!
        # 카드에 _sword_type/_sword_level 임시 필드가 있으면 해당 타입 이미지로 썸네일 자동 채움
        from app.utils.image_helper import get_sword_image_url

        for item in card_items:
            # 카드에서 임시 메타 필드 꺼내기 (카카오 응답에 포함되면 안 되므로 pop)
            sword_type = item.pop("_sword_type", "normal")
            sword_level = item.pop("_sword_level", 0)

            if "thumbnail" not in item or not item["thumbnail"]:
                thumb_url = get_sword_image_url(sword_level, sword_type)
                if thumb_url:
                    item["thumbnail"] = {
                        "imageUrl": thumb_url,
                        "fixedRatio": True,
                        "width": 800,
                        "height": 800
                    }
                else:
                    # SERVER_BASE_URL 없는 경우 — 빈 썸네일 플레이스홀더
                    item["thumbnail"] = {
                        "imageUrl": "https://via.placeholder.com/800",
                        "fixedRatio": True,
                        "width": 800,
                        "height": 800
                    }
            else:
                item["thumbnail"]["fixedRatio"] = True
                item["thumbnail"]["width"] = 800
                item["thumbnail"]["height"] = 800

        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "carousel": {
                            "type": "basicCard",
                            "items": card_items
                        }
                    }
                ],
                "quickReplies": replies
            }
        }
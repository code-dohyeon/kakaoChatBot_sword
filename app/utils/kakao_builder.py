from typing import List, Dict, Any, Optional

DEFAULT_QUICK_REPLIES = [
    {"label": "⚔️ 강화하기", "action": "message", "messageText": "강화하기"},
    {"label": "🏪 상점·유물", "action": "message", "messageText": "상점·유물"},
    {"label": "🗡️ 내 검 보기", "action": "message", "messageText": "내 검 보기"},
    {"label": "📦 납품·마감", "action": "message", "messageText": "납품·마감"},
    {"label": "🏆 자랑·랭킹", "action": "message", "messageText": "자랑·랭킹"},
    {"label": "🔄 새 게임", "action": "message", "messageText": "새 게임"}
]

class KakaoResponseBuilder:
    @staticmethod
    def simple_text(text: str, quick_replies: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        replies = quick_replies if quick_replies is not None else DEFAULT_QUICK_REPLIES
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": text
                        }
                    }
                ],
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
        card: Dict[str, Any] = {
            "title": title,
            "description": description
        }
        if thumbnail_url:
            card["thumbnail"] = {"imageUrl": thumbnail_url}
        if buttons:
            card["buttons"] = buttons

        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "basicCard": card
                    }
                ],
                "quickReplies": replies
            }
        }

    @staticmethod
    def carousel(
        card_items: List[Dict[str, Any]],
        quick_replies: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        replies = quick_replies if quick_replies is not None else DEFAULT_QUICK_REPLIES
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

    @staticmethod
    def multi_card_response(
        outputs: List[Dict[str, Any]],
        quick_replies: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """말풍선 2~3개 분할 응답 지원"""
        replies = quick_replies if quick_replies is not None else DEFAULT_QUICK_REPLIES
        return {
            "version": "2.0",
            "template": {
                "outputs": outputs,
                "quickReplies": replies
            }
        }

import os
from pathlib import Path
from typing import Optional

# Render 배포 시 환경 변수 SERVER_BASE_URL (예: https://sword-upgrade.onrender.com)
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "").rstrip("/")
ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"

# 검 타입별 파일 접두사
TYPE_PREFIX = {
    "normal": "upgrade",
    "stick": "branch",
    "skewer": "skewer",
}

def get_sword_image_url(level: int, sword_type: str = "normal") -> Optional[str]:
    """
    검 타입과 강화 레벨에 맞는 이미지 URL 반환.
    - normal  → upgrade_{level}.png
    - stick   → branch_{level}.png
    - skewer  → skewer_{level}.png
    파일이 없으면 같은 타입의 더 낮은 레벨 파일로 폴백.
    SERVER_BASE_URL 미설정 시 None 반환 (카카오 스키마 오류 방지).
    """
    if not SERVER_BASE_URL:
        return None

    prefix = TYPE_PREFIX.get(sword_type, "upgrade")
    filename = f"{prefix}_{level}.png"

    # 정확한 파일이 없으면 같은 타입 중 가장 가까운 낮은 레벨로 폴백
    if not (ASSETS_DIR / filename).exists():
        fallback = None
        for lvl in range(level - 1, -1, -1):
            candidate = f"{prefix}_{lvl}.png"
            if (ASSETS_DIR / candidate).exists():
                fallback = candidate
                break
        if fallback is None:
            # 타입 전용 이미지가 아예 없으면 normal 기본 이미지로 최종 폴백
            for lvl in range(level, -1, -1):
                candidate = f"upgrade_{lvl}.png"
                if (ASSETS_DIR / candidate).exists():
                    fallback = candidate
                    break
        if fallback:
            filename = fallback
        else:
            return None

    return f"{SERVER_BASE_URL}/assets/{filename}"

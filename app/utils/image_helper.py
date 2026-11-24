import os
from pathlib import Path
from typing import Optional

# Render 배포 시 환경 변수 SERVER_BASE_URL (예: https://sword-upgrade.onrender.com)
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "").rstrip("/")
ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"

def get_sword_image_url(level: int) -> Optional[str]:
    """
    upgrade_{level}.png 또는 upgrade_{type}_{level}.png 형식 매핑
    실제 파일이 존재하거나 기본 URL 형식으로 반환
    """
    filename = f"upgrade_{level}.png"

    # 로컬 경로 체크
    file_path = ASSETS_DIR / filename
    if not file_path.exists():
        # 등급별 폴백 (예: 15 초과 시 15, 파일 미존재 시 레벨별 최대 파일 탐색)
        alt_filename = f"upgrade_{min(level, 15)}.png"
        if (ASSETS_DIR / alt_filename).exists():
            filename = alt_filename

    if SERVER_BASE_URL:
        return f"{SERVER_BASE_URL}/assets/{filename}"
    return f"/assets/{filename}"

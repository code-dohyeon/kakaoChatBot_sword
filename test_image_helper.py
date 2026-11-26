import os, sys
sys.path.insert(0, ".")

# SERVER_BASE_URL 없는 상태 테스트
from app.utils.image_helper import get_sword_image_url, ASSETS_DIR
print("ASSETS_DIR:", ASSETS_DIR)
print("Assets files:", [f for f in os.listdir(ASSETS_DIR) if not f.startswith(".")])
print()

result = get_sword_image_url(0, "stick")
print(f"stick 0 (no SERVER_BASE_URL) -> {result!r}  [예상: None]")
print()

# SERVER_BASE_URL 주입 후 재테스트
import app.utils.image_helper as ih
ih.SERVER_BASE_URL = "https://test.onrender.com"

cases = [
    (0,  "stick",   "branch_0.png 존재"),
    (5,  "stick",   "branch_5.png 없음 -> branch_0.png 폴백"),
    (0,  "skewer",  "skewer_0.png 존재"),
    (5,  "skewer",  "skewer_5.png 없음 -> skewer_0.png 폴백"),
    (0,  "normal",  "upgrade_0.png 존재"),
    (10, "normal",  "upgrade_10.png (있으면 그대로)"),
    (3,  "unknown", "알 수 없는 타입 -> upgrade prefix 사용"),
]

for lvl, stype, note in cases:
    url = ih.get_sword_image_url(lvl, stype)
    print(f"get_sword_image_url({lvl!r}, {stype!r})  [{note}]")
    print(f"  -> {url!r}")
    print()

print("테스트 완료!")

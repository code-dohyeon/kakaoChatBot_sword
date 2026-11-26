# 검 강화 대장간 — 메타 진행(도감·업적·칭호) & 라운드 이벤트 구현 계획

> 한 판이 끝나도 남는 **도감 · 업적 · 칭호**와 매 라운드 변수를 만드는 **라운드 이벤트** 구현 완료.

---

## Step 1. 데이터 모델 및 설정 파일 설계
- [x] `game_config.json` 확장
  - [x] `achievements` (업적/칭호 42종 정의: id, category, title, condition, hidden)
  - [x] `round_events` (라운드 이벤트 6종 정의: id, name, category, weight, description, choices/effects)
- [x] DB 모델 확장 (`app/models/game.py`)
  - [x] `UserMeta` 테이블에 영구 데이터 저장
  - [x] `Run` 테이블 확장 (`round_event`, `meta_counters`)
  - [x] DB 자동 마이그레이션 (`app/main.py`)

---

## Step 2. 라운드 이벤트 시스템 구현
- [x] 이벤트 정의 (`game_config.json`) — 6종
- [x] `GameEngine` 및 `RunService` 연동
  - [x] 라운드 시작(`start_new_run`, `advance_round`) 시 랜덤 이벤트 1종 추첨 및 선택지 카드 반환
  - [x] 이벤트 선택 엔드포인트 구현 (`/api/kakao/event-choice` + `/fallback`)
  - [x] 강화 확률, 판매가, 상점 가격 계산 시 현재 라운드 이벤트 효과 반영

---

## Step 3. 도감 시스템 구현 (검 / 유물 / 이벤트)
- [x] 도감 수집 트리거 연동 (`CollectionService`)
  - [x] **검 도감**, **유물 도감**, **이벤트 도감** 자동 등록 및 `"NEW"` 알림 표시
- [x] 도감 완성도 계산 로직 (25% / 50% / 100% 칭호 자동 해금)
- [x] 도감 조회 UI (`/api/kakao/collection` + `/fallback`, 미수집 실루엣 처리)

---

## Step 4. 업적 & 칭호 시스템 구현
- [x] 업적 판정 엔진 (`app/services/achievement_service.py`)
- [x] 칭호 조회 & 장착 기능 (`/api/kakao/titles` + `/fallback`, 숨김 칭호 `???` 처리)
- [x] 친구 랭킹(`자랑·랭킹`) 닉네임 옆에 장착 칭호 표시

---

## Step 5. 통합 테스트 및 밸런스 점검
- [x] 라운드 이벤트 6종 동작 테스트
- [x] 도감 수집 및 `"NEW"` 알림 테스트
- [x] 업적 해금 및 칭호 장착/랭킹 표시 테스트

# Oracle

일상을 사진·텍스트·음성으로 던지면 LLM이 계속 반응하며 알려주는, **채팅 동반자이자 비서**.

> 구 코드네임 'Oracle'(인벤토리 앱)에서 분기 — 그쪽은 **finder**(`~/projects/finder`).

## 아키텍처 — 3 레이어

1. **Layer 1 — 인입(canonical)**: 캡처 → VLM 캡션 + LLM 즉답 인사이트 → Record로 정본 평문(vault)에 append. *⬅ 현재 슬라이스*
2. **Layer 2 — 인덱스 메타**: Record + tags + thread_ids (자정에 부착) — MongoDB.
3. **Layer 3 — 자정 다이제스트**: 어제 하루치 닫힌 다이제스트 + 누적 상위 인덱스 + 펜딩 thread 점검 + "오늘의 발견".

## 디렉토리

```
corpus/                # 정본 vault — append-only 평문 마크다운 + 이미지
digest/                # 자정 산출물 (닫힌 블록)
index/                 # 사람용 자연어 목차
backend/
  config.py            # 환경/라우팅
  nest_client.py       # Nest HTTP 클라이언트
  db.py                # MongoDB (records/threads/index_meta)
  corpus.py            # vault read/append
  ingest.py            # 캡처 → VLM + 즉답 → Record + vault
  api.py               # FastAPI routes
  main.py              # 앱 진입
app/                   # Flutter (예정)
```

## LLM 호출 — Nest 게이트웨이

`~/projects/nest` (chocolat:7780, 토큰 인증). 모든 LLM 호출은 Nest를 통과. provider/effort/account 셋업은 Nest admin (`/admin`)에서.

**Task → alias 매핑 디폴트**:
- `vlm_caption` = `claude` (Opus max, vision)
- `insight` = `claude`
- 자정 task들도 동일 (자정 슬라이스 구현 후 노출)

`.env`에서 `ORACLE_VLM`, `ORACLE_INSIGHT` 등으로 override.

## 실행 (개발 = bert, 배포 = chocolat 예정)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --port 8765 --reload
```

MongoDB도 필요:
```bash
brew tap mongodb/brew && brew install mongodb-community
brew services start mongodb-community
```

`.env`는 `.env.example` 복사 후 토큰 채울 것 (커밋 금지).

## 인입 호출 (테스트)

```bash
# 사진 + 코멘트
curl -X POST http://localhost:8001/ingest \
  -F "file=@/abs/photo.jpg" -F "comment=야채 양 보소"

# 텍스트만
curl -X POST http://localhost:8001/ingest -F "comment=오늘 점심 뭐 먹지"

# Nest 도달 여부
curl http://localhost:8001/nest/health
```

응답: `{record_id, ts, insight, vlm_caption, vault_path, image_paths}`.

## 상태

**Layer 1 슬라이스 진행 중 (2026-06-02)**. 다음: 자정 배치(digest/threads/index) → 질의/Flutter 채팅 UI.

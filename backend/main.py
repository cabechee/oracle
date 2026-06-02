"""Oracle backend — FastAPI 엔트리.

엔드포인트:
- GET  /health              oracle 자체 상태
- GET  /nest/health         Nest 게이트웨이 도달 여부
- POST /ingest              캡처 인입 (file/comment) → VLM + 즉답 → Record
- GET  /records             최근 Record 목록 (채팅 무한스크롤)
- GET  /records/{id}        단건
- POST /records/{id}/reaction  이모지 피드백

엔드포인트는 def(동기) — FastAPI가 threadpool에서 실행, Nest HTTP 호출이 이벤트루프 차단 안 함.
"""

from fastapi import FastAPI

import api
from db import ensure_indexes
from config import HOST, PORT


app = FastAPI(title="Oracle backend", version="0.1.0")

ensure_indexes()
app.include_router(api.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)

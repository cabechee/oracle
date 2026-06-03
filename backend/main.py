"""Oracle backend — FastAPI 엔트리.

엔드포인트:
- GET  /health              oracle 자체 상태
- GET  /nest/health         Nest 게이트웨이 도달 여부
- POST /ingest              캡처 인입 (file/comment) → VLM + 즉답 → Record
- GET  /records             최근 Record 목록 (채팅 무한스크롤)
- GET  /records/{id}        단건
- GET  /photos/<rel>        vault 사진 서빙
- POST /records/{id}/reaction  이모지 피드백

엔드포인트는 def(동기) — FastAPI가 threadpool에서 실행, Nest HTTP 호출이 이벤트루프 차단 안 함.
"""

import time
from fastapi import FastAPI, Request

import api
from db import ensure_indexes
from config import HOST, PORT


app = FastAPI(title="Oracle backend", version="0.1.0")

ensure_indexes()


# 요청 도달/완료 진단 미들웨어 — uvicorn access log는 응답 완료 시만 찍혀
# "도달은 했는데 응답 미완"인지 구분이 안 됨. 이걸 잡아준다.
@app.middleware("http")
async def trace_requests(request: Request, call_next):
    client = request.client.host if request.client else "?"
    print(f">> {request.method} {request.url.path} from {client}", flush=True)
    t0 = time.time()
    try:
        response = await call_next(request)
        dt = int((time.time() - t0) * 1000)
        print(f"<< {request.method} {request.url.path} → {response.status_code} ({dt}ms)", flush=True)
        return response
    except Exception as e:
        dt = int((time.time() - t0) * 1000)
        print(f"!! {request.method} {request.url.path} EXC after {dt}ms: {e!r}", flush=True)
        raise


app.include_router(api.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)

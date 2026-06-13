"""Oracle backend — FastAPI 엔트리.

엔드포인트는 api/ 라우터 패키지에 도메인별로 분리:
ingest(인입·LLM 목록) · records(목록·단건·리액션·편집·사진) · journal(자정 배치·일/주/월 저널·다이제스트)
· threads(활성·silent·타임라인) · query(자연어 질의·임베딩 backfill) · index(상위 인덱스) · nest(상태).

엔드포인트는 def(동기) — FastAPI가 threadpool에서 실행, Nest HTTP 호출이 이벤트루프 차단 안 함.
"""

import os
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import api
from db import ensure_indexes
from config import HOST, PORT, ORACLE_TOKEN


app = FastAPI(title="Oracle backend", version="0.1.0")

ensure_indexes()

# Flutter 웹 빌드 디렉토리 (bert에서 rsync 배포). 있으면 /app 에 same-origin 서빙.
_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


# 토큰 인증 (opt-in) — ORACLE_TOKEN 설정 시에만 활성.
# loopback(자정 cron curl·로컬 운영)과 /health 는 면제. 폰은 Tailscale 위에서 헤더로.
@app.middleware("http")
async def auth_token(request: Request, call_next):
    if ORACLE_TOKEN:
        client = request.client.host if request.client else ""
        if request.url.path != "/health" and client not in ("127.0.0.1", "::1"):
            if request.headers.get("x-oracle-token") != ORACLE_TOKEN:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


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


# 어드민 UI — 데이터 조회·관리 (개인 운영툴). /admin/api/* 는 라우터가 처리.
_ADMIN_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html")


@app.get("/admin")
def admin_page():
    return FileResponse(_ADMIN_HTML)


# ── Flutter 웹앱 서빙 (/app) — API 라우터 뒤에 마운트해 경로 충돌 없음 ──
if os.path.isdir(_WEB_DIR):
    # SPA: 새로고침·딥링크가 index.html로 떨어지게 (Flutter 라우팅이 처리)
    @app.get("/app")
    @app.get("/app/")
    def _web_index():
        return FileResponse(os.path.join(_WEB_DIR, "index.html"))

    app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="webapp")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)

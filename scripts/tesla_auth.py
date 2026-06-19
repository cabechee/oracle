#!/usr/bin/env python3
"""Tesla Fleet API OAuth 동의 — 최초 1회 (authorization_code).

전제(순서):
  1) developer.tesla.com 앱 생성 — 부여유형 '인증 코드 및 사물 통신',
     허용 출처 URL = https://oraclecar.pages.dev,
     허용 리디렉션 URI = http://localhost:8080/callback
  2) 공개키를 https://{TESLA_DOMAIN}/.well-known/appspecific/com.tesla.3p.public-key.pem 에 호스팅(CF Pages)
  3) `python scripts/tesla_register.py` 로 파트너 등록(도메인+공개키)
  4) .env에 TESLA_CLIENT_ID·TESLA_CLIENT_SECRET 채움

실행: backend venv로 `python scripts/tesla_auth.py`
  → 브라우저 동의 → 프로젝트 루트에 tesla_token.json 저장(이후 백엔드가 자동 갱신).
  브라우저 되는 곳(랩탑)에서 돌리고, 생성된 tesla_token.json 을 chocolat ~/projects/oracle/ 로 복사.
"""

import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser

import httpx

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
import config  # noqa: E402

AUTH = "https://auth.tesla.com/oauth2/v3"
PORT = 8080
_result: dict = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        _result["code"] = (q.get("code") or [None])[0]
        _result["state"] = (q.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("인증 완료. 이 창을 닫아도 됩니다.".encode("utf-8"))

    def log_message(self, *args):
        pass


def main() -> int:
    if not (config.TESLA_CLIENT_ID and config.TESLA_CLIENT_SECRET):
        print("❌ .env에 TESLA_CLIENT_ID·TESLA_CLIENT_SECRET가 없습니다.")
        return 1
    state = secrets.token_urlsafe(16)
    url = f"{AUTH}/authorize?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": config.TESLA_CLIENT_ID,
        "redirect_uri": config.TESLA_REDIRECT_URI,
        "scope": config.TESLA_SCOPES,
        "state": state,
    })
    srv = http.server.HTTPServer(("localhost", PORT), _Handler)
    t = threading.Thread(target=srv.handle_request)
    t.start()
    print("브라우저에서 테슬라 로그인·동의:\n ", url)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    t.join(timeout=300)
    srv.server_close()

    if not _result.get("code"):
        print("❌ 인증 코드를 못 받았습니다(타임아웃 또는 거부).")
        return 1
    if _result.get("state") != state:
        print("❌ state 불일치 — 보안상 중단.")
        return 1
    try:
        r = httpx.post(f"{AUTH}/token", data={
            "grant_type": "authorization_code",
            "client_id": config.TESLA_CLIENT_ID,
            "client_secret": config.TESLA_CLIENT_SECRET,
            "code": _result["code"],
            "redirect_uri": config.TESLA_REDIRECT_URI,
            "audience": config.TESLA_API_BASE,
        }, timeout=30)
    except Exception as e:
        print(f"❌ 토큰 교환 요청 실패: {e}")
        return 1
    if r.status_code != 200:
        print(f"❌ 토큰 교환 실패: {r.status_code} {r.text[:300]}")
        return 1
    tok = r.json()
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 28800))
    with open(config.TESLA_TOKEN_PATH, "w") as f:
        json.dump(tok, f)
    print(f"✅ 인증 완료 → {config.TESLA_TOKEN_PATH}")
    print("   chocolat이면 이 파일을 ~/projects/oracle/ 로 복사하면 백엔드가 바로 사용합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

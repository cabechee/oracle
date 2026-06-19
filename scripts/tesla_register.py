#!/usr/bin/env python3
"""Tesla 파트너 등록 — 도메인+공개키를 테슬라에 등록 (최초 1회, 공개키 호스팅 후).

전제: 공개키가 https://{TESLA_DOMAIN}/.well-known/appspecific/com.tesla.3p.public-key.pem
에 떠 있어야 함(CF Pages 배포). .env에 TESLA_CLIENT_ID·TESLA_CLIENT_SECRET 필요.

실행: backend venv로 `python scripts/tesla_register.py`
"""

import os
import sys

import httpx

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
import config  # noqa: E402
import tesla   # noqa: E402


def main() -> int:
    # 0) 공개키 공개 도달 확인(테슬라 서버가 가져갈 수 있는지 선검사)
    pk_url = (f"https://{config.TESLA_DOMAIN}"
              "/.well-known/appspecific/com.tesla.3p.public-key.pem")
    try:
        r = httpx.get(pk_url, timeout=15, follow_redirects=True)
        if r.status_code != 200 or "BEGIN PUBLIC KEY" not in r.text:
            print(f"❌ 공개키 미도달/형식 이상: {pk_url} (HTTP {r.status_code})")
            print("   CF Pages 배포·커스텀 도메인 연결을 먼저 확인하세요.")
            return 1
        print(f"✓ 공개키 확인: {pk_url}")
    except Exception as e:
        print(f"❌ 공개키 fetch 실패: {e}")
        return 1

    # 1) 파트너 토큰(client_credentials)
    pt = tesla.partner_token()
    if not pt:
        print("❌ 파트너 토큰 발급 실패 — .env의 TESLA_CLIENT_ID·SECRET 확인.")
        return 1
    print("✓ 파트너 토큰 발급됨")

    # 2) 파트너 계정 등록(도메인)
    try:
        r = httpx.post(f"{config.TESLA_API_BASE}/api/1/partner_accounts",
                       headers={"Authorization": f"Bearer {pt}"},
                       json={"domain": config.TESLA_DOMAIN}, timeout=30)
    except Exception as e:
        print(f"❌ 등록 요청 실패: {e}")
        return 1
    print(f"등록 응답: HTTP {r.status_code}\n{r.text[:500]}")
    if r.status_code in (200, 201):
        print("✅ 파트너 등록 완료 — 이제 scripts/tesla_auth.py 로 사용자 인증.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

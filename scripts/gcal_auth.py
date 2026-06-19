#!/usr/bin/env python3
"""구글 캘린더 OAuth 동의 — 최초 1회.

준비:
  1) Google Cloud Console → 프로젝트 → 'Google Calendar API' 사용 설정
  2) OAuth 동의 화면 구성(테스트 사용자에 본인 계정 추가) + OAuth 클라이언트 ID
     생성(애플리케이션 유형 = **데스크톱 앱**) → JSON 다운로드
  3) 받은 파일을 프로젝트 루트에 `gcal_credentials.json` 으로 저장
     (또는 GCAL_CREDS_PATH 환경변수로 경로 지정)

실행:
  backend venv로  `python scripts/gcal_auth.py`
  → 브라우저 동의 → 프로젝트 루트에 `gcal_token.json` 저장(이후 자동 갱신).

  랩탑/chocolat 어디서 돌려도 됨(브라우저 되는 곳). 랩탑에서 만들었으면 생성된
  gcal_token.json 을 chocolat `~/projects/oracle/` 로 복사하면 백엔드가 바로 사용.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDS = os.environ.get("GCAL_CREDS_PATH",
                       os.path.join(_ROOT, "gcal_credentials.json"))
TOKEN = os.environ.get("GCAL_TOKEN_PATH",
                       os.path.join(_ROOT, "gcal_token.json"))


def main() -> int:
    if not os.path.exists(CREDS):
        print(f"❌ 클라이언트 파일이 없습니다: {CREDS}")
        print("   Google Cloud에서 데스크톱 OAuth 클라이언트 JSON을 받아 위 경로에 두세요.")
        return 1
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌ google-auth-oauthlib 미설치. `pip install -r backend/requirements.txt`")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(CREDS, SCOPES)
    # 로컬 서버로 리다이렉트 받기(데스크톱 앱 표준). 브라우저가 자동으로 열림.
    creds = flow.run_local_server(port=0, prompt="consent")
    with open(TOKEN, "w") as f:
        f.write(creds.to_json())
    print(f"✅ 인증 완료 → {TOKEN}")
    print("   이제 백엔드가 캘린더를 읽고 쓸 수 있습니다. (chocolat이면 재시작 불필요)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

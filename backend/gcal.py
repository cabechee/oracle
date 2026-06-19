"""구글 캘린더 연동 — 다가오는 일정 읽기 + 이벤트 생성.

인증(OAuth2, Installed/Desktop 앱): 최초 1회 `python scripts/gcal_auth.py`로 동의 →
GCAL_TOKEN_PATH(gcal_token.json) 저장 → 이후 refresh_token으로 자동 갱신.

설계 원칙 — **Oracle은 캘린더 때문에 절대 죽지 않는다**: 라이브러리 미설치·토큰 없음·
네트워크/권한 실패를 전부 graceful 처리(빈 결과 / authed=False). 캘린더는 부가 평면.
"""

import os
from datetime import date as _date, datetime, timedelta
from typing import Any, Dict, List, Optional

import config

# 읽기+쓰기(일정 보기 + 이벤트 생성). 읽기만 원하면 calendar.readonly로 좁힐 수 있음.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# upcoming 캐시 — 데스크 피드가 매번 구글을 때리지 않게(느림). 생성 시 무효화.
_CACHE: Dict[str, Any] = {"events": None, "at": None}
_CACHE_TTL = 300  # 초


def _load_creds():
    """저장된 토큰 로드 + 만료 시 refresh. 라이브러리/토큰 없으면 None(graceful)."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None
    if not os.path.exists(config.GCAL_TOKEN_PATH):
        return None
    try:
        creds = Credentials.from_authorized_user_file(
            config.GCAL_TOKEN_PATH, SCOPES)
    except Exception:
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_creds(creds)
        except Exception:
            return None
    return creds if (creds and creds.valid) else None


def _save_creds(creds) -> None:
    try:
        with open(config.GCAL_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    except Exception:
        pass


def _service():
    """캘린더 v3 서비스 — 미인증/실패면 None."""
    creds = _load_creds()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds,
                     cache_discovery=False)
    except Exception:
        return None


def is_authed() -> bool:
    return _load_creds() is not None


def status() -> Dict[str, Any]:
    """인증 상태 — 어드민 표시용. authed면 연결된 캘린더(계정)도 시도."""
    if not is_authed():
        return {
            "authed": False,
            "has_client": os.path.exists(config.GCAL_CREDS_PATH),
            "calendar_id": config.GCAL_CALENDAR_ID,
        }
    account = ""
    try:
        svc = _service()
        cal = svc.calendarList().get(
            calendarId=config.GCAL_CALENDAR_ID).execute()
        account = cal.get("id", "") or cal.get("summary", "")
    except Exception:
        pass
    return {"authed": True, "has_client": True,
            "calendar_id": config.GCAL_CALENDAR_ID, "account": account}


def _ev_view(e: Dict[str, Any]) -> Dict[str, Any]:
    """구글 이벤트 → 앱/어드민용 평탄 dict. 종일/시각 일정 모두 정규화."""
    start, end = e.get("start", {}), e.get("end", {})
    all_day = "date" in start
    return {
        "id": e.get("id"),
        "title": (e.get("summary") or "(제목 없음)").strip(),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": all_day,
        "location": (e.get("location") or "").strip(),
        "url": e.get("htmlLink"),
        "description": (e.get("description") or "").strip(),
    }


def upcoming(days: int = 7, max_results: int = 25,
             use_cache: bool = True) -> List[Dict[str, Any]]:
    """지금부터 days일 안의 일정(시작순). 미인증/실패면 []."""
    now = datetime.now()
    if (use_cache and _CACHE["events"] is not None
            and isinstance(_CACHE["at"], datetime)
            and (now - _CACHE["at"]).total_seconds() < _CACHE_TTL):
        return _CACHE["events"]
    svc = _service()
    if not svc:
        return []
    try:
        time_min = now.astimezone().isoformat()
        time_max = (now + timedelta(days=days)).astimezone().isoformat()
        res = svc.events().list(
            calendarId=config.GCAL_CALENDAR_ID,
            timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy="startTime",
            maxResults=max_results).execute()
        out = [_ev_view(e) for e in res.get("items", [])]
        _CACHE["events"], _CACHE["at"] = out, now
        return out
    except Exception as e:
        print(f"[gcal] upcoming 실패: {e}", flush=True)
        return []


def _start_date(ev: Dict[str, Any]) -> Optional[_date]:
    s = ev.get("start") or ""
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return _date.fromisoformat(s[:10])
    except Exception:
        return None


def today_events(target: Optional[_date] = None) -> List[Dict[str, Any]]:
    """오늘(또는 target) 일정 — 동반자 맥락·일기 배경. upcoming서 그날치 필터."""
    target = target or _date.today()
    return [e for e in upcoming(days=2, max_results=50)
            if _start_date(e) == target]


def day_lines(target: Optional[_date] = None) -> List[str]:
    """오늘 일정 → 사람이 읽는 짧은 줄 (예: '14:00 치과 예약', '종일 워크숍')."""
    out: List[str] = []
    for e in today_events(target):
        if e["all_day"]:
            out.append(f"종일 {e['title']}")
        else:
            try:
                t = datetime.fromisoformat(e["start"].replace("Z", "+00:00"))
                out.append(f"{t.strftime('%H:%M')} {e['title']}")
            except Exception:
                out.append(e["title"])
    return out


def create_event(title: str, start: str, end: Optional[str] = None,
                 description: str = "", location: str = "",
                 all_day: bool = False) -> Optional[Dict[str, Any]]:
    """이벤트 생성. start/end = ISO8601(시각, 오프셋 포함 권장) 또는 YYYY-MM-DD(종일).

    미인증/실패면 None. 종일이면 end는 종료 '다음날'(구글 규약) — 생략 시 start+1일.
    """
    svc = _service()
    if not svc:
        return None
    try:
        if all_day:
            s = start[:10]
            if end:
                e = end[:10]
            else:
                e = (_date.fromisoformat(s) + timedelta(days=1)).isoformat()
            body: Dict[str, Any] = {"summary": title,
                                    "start": {"date": s}, "end": {"date": e}}
        else:
            body = {"summary": title, "start": {"dateTime": start},
                    "end": {"dateTime": end or start}}
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        ev = svc.events().insert(
            calendarId=config.GCAL_CALENDAR_ID, body=body).execute()
        _CACHE["events"] = None  # 캐시 무효화
        return _ev_view(ev)
    except Exception as e:
        print(f"[gcal] create 실패: {e}", flush=True)
        return None

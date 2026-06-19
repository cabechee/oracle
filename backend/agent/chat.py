"""agent.chat — 대화 모드 (MVP 엔진).

히스토리 탭 하단 입력 → 동반자와의 자유 대화. 검색(/query)이 1회성 Q&A라면
이건 멀티턴: 최근 대화 + 워킹메모리(지난 며칠) + 3요소 검색 후보를 모아 응답.

⚠️ 설계 경계 (호문쿨루스 연동 계획):
- 이 모듈은 **교체 가능한 임시 엔진**이다. 인터페이스는 conversations 컬렉션
  스키마({role, text, ts, referenced})와 /chat API뿐 — 추후 대화 런타임을
  Homunculus(chocolat :18900)로 옮길 때 이 파일의 LLM 호출부만 어댑터로 바꾼다.
- Oracle은 "기억 평면"(검색·워킹메모리·record)을 제공하고, 인격/대화 정책은
  호문쿨루스 쪽이 가져가는 분리가 목표. 여기에 페르소나 로직을 깊게 쌓지 말 것.
"""

import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

import db
import query as query_mod
from . import llm
from . import memory as memory_mod
from . import quick as quick_mod
from . import personas   # 베르 페르소나 — 어드민(/admin)에서 수정
from config import task_alias


def _msg_doc(role: str, text: str, ts: datetime,
             referenced: Optional[List[str]] = None,
             mentions: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "_id": f"msg-{ts.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "role": role,                    # user | assistant
        "text": text,
        "ts": ts,
        "referenced": referenced or [],  # 응답이 근거로 댄 record (assistant)
        "mentions": mentions or [],       # 유저가 콕 집어 언급한 record (user)
    }


def _normalize(m: Dict[str, Any]) -> Dict[str, Any]:
    if hasattr(m.get("ts"), "isoformat"):
        m["ts"] = m["ts"].isoformat()
    return m


def _mention_view(r: Dict[str, Any]) -> Dict[str, Any]:
    """아빠가 콕 집어 언급한 record의 요약 — 대화 컨텍스트용."""
    return {
        "id": r["_id"],
        "when": r["ts"].strftime("%m/%d %H:%M") if hasattr(r.get("ts"), "strftime") else "",
        "comment": (r.get("user_comment") or "").strip(),
        "analysis": ((r.get("vlm") or {}).get("caption") or "").strip(),
        "insight": ((r.get("insight") or {}).get("text") or "").strip(),
        "has_photo": bool(r.get("image_paths")),
    }


def chat(message: str, mention_ids: Optional[List[str]] = None,
         candidate_limit: int = 6) -> Dict[str, Any]:
    """대화 한 턴 — 유저 메시지 저장 → 컨텍스트 조립 → LLM → 응답 저장.

    mention_ids: 아빠가 흐름에서 콕 집어 언급한 과거 record id들 — 이걸 중심으로 답하게.
    Returns: {"messages": [userMsg, assistantMsg], "alias": str}
    (둘 다 ts/id 포함 — 앱이 타임라인에 그대로 merge.)
    """
    alias = task_alias("chat") or task_alias("query") or llm.default_alias()
    now = datetime.now()
    user_msg = _msg_doc("user", message, now, mentions=mention_ids or [])
    db.conversations().insert_one(user_msg)

    # 액션 감지 — '일정 넣어줘' 류면 일반 응답 대신 '제안+확인' 메시지. 생성은 confirm 때.
    from . import actions
    proposal = actions.detect_calendar(message, now)
    if proposal:
        asst = _msg_doc(
            "assistant", f"「{proposal['preview']}」 — 캘린더에 넣을까요?",
            datetime.now())
        asst["action"] = proposal
        db.conversations().insert_one(asst)
        return {"messages": [_normalize(dict(user_msg)), _normalize(dict(asst))],
                "alias": ""}

    if not alias:
        reply = "(chat alias 미설정 — Nest에 enabled 모델 없음)"
        referenced: List[str] = []
    else:
        # 컨텍스트 = 최근 대화 + 워킹메모리(지난 1주일 일기 + 오늘 흐름).
        # 검색 candidate 주입은 의도적으로 제거(2026-06-13): "관련 기록"이라 골라 주면
        # 모델이 억지로 갖다 붙인다. 채팅처럼 1주일을 통째 흐름으로 두면 자연히 기억만 하고
        # 필요할 때만 참조 → 억지 연결이 사라진다.
        history = list(
            db.conversations().find({"_id": {"$ne": user_msg["_id"]}})
            .sort("ts", -1).limit(30)
        )
        history.reverse()   # 시간순
        hist_lines = [
            f"{'유저' if m.get('role') == 'user' else '나'}: {(m.get('text') or '')[:400]}"
            for m in history if (m.get("text") or "").strip()
        ]
        working = memory_mod.working_memory(now)
        mentions = []
        if mention_ids:
            by_id = {r["_id"]: r for r in
                     db.records().find({"_id": {"$in": mention_ids}})}
            mentions = [_mention_view(by_id[i]) for i in mention_ids if i in by_id]

        parts: List[str] = []
        if working:
            parts.append(f"[기억 — 지난 1주일 일기 + 오늘 흐름]\n{working}")
        if mentions:
            parts.append(
                "[아빠가 지금 콕 집어 말하는 과거 기록 — 이걸 중심으로 답해]\n"
                + json.dumps(mentions, ensure_ascii=False))
        if hist_lines:
            parts.append("[최근 대화]\n" + "\n".join(hist_lines))
        parts.append(f"[유저]\n{message}")
        prompt = "\n\n".join(parts)

        try:
            r = llm.call(alias, prompt, system=personas.chat_system())
            reply = (r.get("text") or "").strip() or "(빈 응답)"
        except Exception as e:
            reply = f"(응답 실패: {e})"
        reply, referenced = query_mod.extract_referenced(reply)

    asst_msg = _msg_doc("assistant", reply, datetime.now(), referenced)
    # 쿠키 첨언 — 베르 답에 한마디 거듦 (대화에도 동일). 실패/미설정이면 생략.
    asst_msg["quick"] = _chat_quick(message, reply, now)
    db.conversations().insert_one(asst_msg)

    return {
        "messages": [_normalize(dict(user_msg)), _normalize(dict(asst_msg))],
        "alias": alias or "",
    }


def _chat_quick(message: str, reply: str,
                now: Optional[datetime] = None) -> Optional[Dict[str, str]]:
    """대화에 쿠키 한마디 — 베르 답을 보고 거듦. 베르와 동일한 맥락(워킹메모리)도 받음."""
    alias = task_alias("quick") or ""
    if not alias or not reply or reply.startswith("("):
        return None
    try:
        context = memory_mod.working_memory(now or datetime.now())
        text = quick_mod.say(
            alias, user_input=f"오빠: {message}\n[베르의 답] {reply}",
            context=context)
        return {"alias": alias, "text": text} if text else None
    except Exception:
        return None


def history(limit: int = 200) -> List[Dict[str, Any]]:
    """최근 대화 메시지 (최신순) — 앱이 record 타임라인과 merge."""
    cur = db.conversations().find().sort("ts", -1).limit(limit)
    return [_normalize(m) for m in cur]


def confirm_action(message_id: str) -> Dict[str, Any]:
    """제안된 액션 확인 → 실행(캘린더 생성). 메시지의 action.status를 done으로 갱신.

    멱등: 이미 done/취소면 다시 실행하지 않음(중복 일정 방지).
    """
    from . import actions
    msg = db.conversations().find_one({"_id": message_id})
    if not msg or not isinstance(msg.get("action"), dict):
        return {"ok": False, "reason": "액션 없음"}
    action = msg["action"]
    if action.get("status") != "proposed":
        return {"ok": False, "reason": f"이미 {action.get('status')}"}
    res = actions.run(action)
    if not res.get("ok"):
        return res
    db.conversations().update_one(
        {"_id": message_id},
        {"$set": {"action.status": "done", "action.created": res["event"]}})
    return {"ok": True, "event": res["event"]}


def cancel_action(message_id: str) -> Dict[str, Any]:
    """제안된 액션 취소 — 생성 안 하고 status를 cancelled로."""
    res = db.conversations().update_one(
        {"_id": message_id, "action.status": "proposed"},
        {"$set": {"action.status": "cancelled"}})
    return {"ok": res.matched_count > 0}

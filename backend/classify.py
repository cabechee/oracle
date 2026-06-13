"""자정 분류 — record에 thread_ids(정체성 닻) + type_hint/tags 부착.

순수 JSON 분류 LLM 호출. ingest 시점엔 안 붙이고 자정에 일괄 판정.
"""

import json
from typing import List, Dict, Any

import threads as threads_mod
from agent import llm
from nightly_common import records_brief, resolve_alias, parse_json_safe


THREAD_JUDGE_SYSTEM = """순수 JSON 분류 작업. 파일·코드·도구 접근 금지 — 오직 user 메시지의 records 텍스트만 보고 판정.

규칙 1: user 메시지의 모든 record가 assignments에 등장.

규칙 2: 같은 주제·물건·인물의 시리즈는 같은 thread.
  ✓ 마우스 사진 3장 (첫 등장 → 잘못 식별 → "이건 MX Master 4야" 정정) → 모두 같은 새 thread "MX Master 4"
  ✓ "여권 어디 있더라" → 며칠 후 "찾았다 서랍에" → 같은 thread "여권 찾기"
  ✓ 옷·SD카드 같은 진짜 일회성 단발 → thread_ids: []
  ✗ 보수적으로 다 빈 배열 두지 말 것. 묶일 가능성 보이면 thread 만들기.

규칙 3: 한 record가 여러 thread에 동시 소속 OK. thread name은 짧은 한국어.

규칙 4: 상태(완료·펜딩) 판단 X — 정체성(연결)만.

출력 = JSON 객체 하나, 그 외 텍스트 절대 없음:
{"assignments":[{"record_id":"rec-...","thread_ids":[17]},{"record_id":"rec-...","thread_ids":[]}],"new_threads":[{"id":17,"name":"MX Master 4","lineage_from":null}]}"""


TYPE_TAG_SYSTEM = """순수 JSON 분류 작업. 파일·코드·도구 접근 금지 — 오직 user 메시지의 records 텍스트만 보고 판정.

규칙 1: user 메시지의 모든 record가 assignments에 등장.

규칙 2: type 필드는 정확히 아래 4개 한국어 단어 중 1개. 그 외 모든 값(영어·새 카테고리·snake_case) 거부됨.
  ✓ "상황" — 현재 일어나는 일·관찰 (식사·풍경·만남·물건 보여주기)
  ✓ "의도" — 하고 싶은 일·계획·고민·결정 대기
  ✓ "맥락" — 정보·자료·메모·링크·영수증·아이디어
  ✓ "산출물" — 만든 것·결과·완료된 일
  ✗ "correction_note" → "상황" 으로 변환
  ✗ "item_photo" → "상황" 으로 변환
  ✗ "user_input" → "맥락" 으로 변환

규칙 3: tags 필드는 한국어 단어 3~5개. 영어·snake_case 거부됨.
  ✓ ["비빔밥", "점심", "야채"]
  ✓ ["마우스", "MX마스터4", "데스크"]
  ✗ ["mouse", "MX_Master_4", "desk_setup"] — 모두 한국어로 변환

출력 = JSON 객체 하나, 그 외 텍스트 절대 없음:
{"assignments":[{"record_id":"rec-...","type":"상황","tags":["비빔밥","점심","야채"]}]}"""


def judge_threads(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    alias = resolve_alias("thread_judge")
    if not alias:
        return {}
    active = threads_mod.list_active_threads(within_days=60)
    next_id = threads_mod.next_thread_id()
    brief = records_brief(records)
    prompt = (
        f"## Active threads (최근 60일)\n"
        f"{json.dumps(active, ensure_ascii=False, default=str)}\n\n"
        f"## 오늘 records (총 {len(brief)}건 — 모두 assignments에 등장해야 함)\n"
        f"{json.dumps(brief, ensure_ascii=False)}\n\n"
        f"새 thread는 id={next_id}부터 순차 할당.\n\n"
        f"**위 {len(brief)}개 record_id 전부 assignments에 포함. JSON 객체 하나만, 첫 글자 `{{`.**"
    )
    try:
        r = llm.call(alias, prompt, system=THREAD_JUDGE_SYSTEM)
        raw = r.get("text") or ""
        parsed = parse_json_safe(raw)
        if not parsed:
            print(f"[classify] judge_threads JSON parse 실패. raw 앞 1500자:\n{raw[:1500]}",
                  flush=True)
        else:
            print(f"[classify] judge_threads OK — assignments={len(parsed.get('assignments', []) or [])}, "
                  f"new={len(parsed.get('new_threads', []) or [])}", flush=True)
        return parsed
    except Exception as e:
        print(f"[classify] judge_threads 호출 실패: {e}", flush=True)
        return {}


def classify_type_tags(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    alias = resolve_alias("type_classify")
    if not alias:
        return {}
    brief = records_brief(records)
    prompt = (
        f"## records (총 {len(brief)}건 — 모두 assignments에 등장해야 함)\n"
        f"{json.dumps(brief, ensure_ascii=False)}\n\n"
        f"각 record에 type + tags 부착.\n\n"
        f"**위 {len(brief)}개 record_id 전부 assignments에 포함. JSON 객체 하나만, 첫 글자 `{{`.**"
    )
    try:
        r = llm.call(alias, prompt, system=TYPE_TAG_SYSTEM)
        raw = r.get("text") or ""
        parsed = parse_json_safe(raw)
        if not parsed:
            print(f"[classify] classify_type_tags JSON parse 실패. raw 앞 1500자:\n{raw[:1500]}",
                  flush=True)
        else:
            print(f"[classify] classify_type_tags OK — assignments={len(parsed.get('assignments', []) or [])}",
                  flush=True)
        return parsed
    except Exception as e:
        print(f"[classify] classify_type_tags 호출 실패: {e}", flush=True)
        return {}

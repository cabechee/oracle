"""자정 배치 공용 헬퍼 — classify/journal 이 공유하는 LLM 호출 유틸.

순환 import 방지를 위해 alias 결정·record 직렬화·JSON 파싱만 모아둔 얇은 모듈.
"""

import json
import re
from typing import List, Dict, Any, Optional

import nest_client
from config import TASK_ALIAS


def records_brief(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LLM 호출용 — record를 짧게 요약 (각 필드 길이 제한)."""
    brief: List[Dict[str, Any]] = []
    for r in records:
        ts = r.get("ts")
        brief.append({
            "id": r["_id"],
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
            "user_comment": (r.get("user_comment") or "")[:300],
            "vlm": ((r.get("vlm") or {}).get("caption") or "")[:300],
            "insight": ((r.get("insight") or {}).get("text") or "")[:300],
            "suggestion": (r.get("suggestion") or "")[:200],
        })
    return brief


def resolve_alias(task_key: str) -> Optional[str]:
    """alias 동적 chain: env(TASK_ALIAS) → Nest enabled 첫 모델."""
    env_alias = TASK_ALIAS.get(task_key) or ""
    if env_alias:
        return env_alias
    return nest_client.default_alias()


def parse_json_safe(text: str) -> Dict[str, Any]:
    """LLM 응답에서 JSON 추출. 코드블록 또는 raw 둘 다 처리."""
    if not text:
        return {}
    # ```json ... ``` 추출
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    # 첫 { ~ 마지막 } 슬라이스
    if "{" in candidate and "}" in candidate:
        candidate = candidate[candidate.index("{"):candidate.rindex("}") + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return {}

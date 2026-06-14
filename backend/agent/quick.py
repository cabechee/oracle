"""agent.quick — 쿠키(오목눈이)의 빠른 1차 반응 (한마디).

모든 캡처(텍스트·사진)가 메인 디스커버리(베르) 전에 이걸 먼저 거친다.
짧은 한마디 → record.quick. 폰은 폴링으로 이걸 먼저 본다.
"""

from typing import Optional, List, Dict

from . import llm
from . import personas   # 쿠키 페르소나 — 어드민(/admin)에서 수정


def say(alias: str, user_input: str = "",
        media: Optional[List[Dict[str, str]]] = None) -> str:
    """쿠키의 짧은 한마디 (페르소나). 멀티모달 전제."""
    body = user_input.strip() or "(미디어만 있고 글은 없음)"
    r = llm.call(alias, f"[방금 들어온 것]\n{body}\n\n쿠키답게 짧게 한마디.",
                 images=media or None, system=personas.quick_system())
    return (r.get("text") or "").strip()

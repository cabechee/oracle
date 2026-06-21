"""agent.quick — 쿠키(오목눈이)의 빠른 1차 반응 (한마디).

모든 캡처(텍스트·사진)가 메인 디스커버리(베르) 전에 이걸 먼저 거친다.
짧은 한마디 → record.quick. 폰은 폴링으로 이걸 먼저 본다.
"""

from typing import Optional, List, Dict

from . import llm
from . import personas   # 쿠키 페르소나 — 어드민(/admin)에서 수정


def say(alias: str, user_input: str = "",
        media: Optional[List[Dict[str, str]]] = None,
        context: str = "") -> str:
    """쿠키의 짧은 한마디 (페르소나). 멀티모달 전제.

    유저 프롬프트는 **데이터만**(캡처 + 오늘 흐름 배경). '어떻게 반응할지'(캡처에·짧게)는
    quick_role(시스템)에 있으니 중복 지시 안 함. context는 배경 참고일 뿐 — 캡처가 맨 앞,
    배경은 '꽂히지 마'로 눌러 1차 반응이 옛 시간대(예: '새벽')에 쏠리지 않게.
    """
    if user_input.strip():
        body = user_input.strip()
    elif media:
        body = "(사진/미디어만 — 그 안에 보이는 것)"
    else:
        body = "(들어온 게 없음)"
    ctx_block = (
        f"\n\n[오늘 흐름 — 배경 참고만. 눈앞의 것과 자연스레 이어질 때만 슬쩍, "
        f"시간대·옛일에 꽂히지 마]\n{context.strip()}"
        if (context or "").strip() else "")
    prompt = f"[방금 들어온 것]\n{body}{ctx_block}"
    r = llm.call(alias, prompt, images=media or None, system=personas.quick_system())
    return (r.get("text") or "").strip()

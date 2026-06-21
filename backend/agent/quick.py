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

    **눈앞의 캡처(사진/글)에 먼저 반응**하게 — context는 배경 참고일 뿐.
    (예전엔 맥락을 프롬프트 앞에 둬서, 사진은 두고 맥락 속 시간대·옛일—예: '새벽'—에
    꽂히는 일이 있었음. 베르는 분석 JSON으로 사진에 고정되지만 쿠키는 1차 반응이라 안 그래서.)
    """
    if user_input.strip():
        body = user_input.strip()
    elif media:
        body = "(글 없이 사진/미디어만 — 그 안에 보이는 걸 보고 첫인상)"
    else:
        body = "(들어온 게 없음)"
    ctx_block = (
        f"\n\n[참고용 배경 — 최근 흐름. 눈앞의 것과 자연스레 이어질 때만 슬쩍, "
        f"억지로 끌어오지 말고 시간대·옛일에 꽂히지 마]\n{context.strip()}"
        if (context or "").strip() else "")
    prompt = (
        f"[방금 들어온 것]\n{body}\n\n"
        f"바로 이 **방금 들어온 것**(사진이 있으면 그 사진 속에 보이는 것)에 쿠키답게 "
        f"짧게 첫인상 한마디. 눈앞의 것에 먼저 반응해.{ctx_block}")
    r = llm.call(alias, prompt, images=media or None, system=personas.quick_system())
    return (r.get("text") or "").strip()

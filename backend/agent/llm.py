"""agent.llm — 모든 LLM 호출의 단일 통로 (Nest 게이트웨이 래퍼).

여기로 일원화하는 이유:
- 캐싱·로깅·재시도·모델 선택 hook을 한 곳에 둔다.
- cache_prefix: 고정 prefix(예: 30일 워킹메모리)를 prompt 본문과 분리해서 넘기면,
  Nest가 provider별로 캐싱을 적용한다
  (anthropic = cache_control, openai/compat = prefix 정렬, 로컬/CLI = 그냥 합침).
  Nest가 아직 미지원이면 graceful — extra로 흘러가 무시될 뿐 동작은 한다.

모델 선택은 설정(TASK_ALIAS / 폰 LLM picker). 캐싱은 anthropic API일 때 자동 이득.
"""

from typing import Optional, List, Dict, Any

import nest_client


def call(
    alias: str,
    prompt: str,
    *,
    cache_prefix: Optional[str] = None,
    images: Optional[List[Dict[str, str]]] = None,
    audio: Optional[List[Dict[str, str]]] = None,
    system: Optional[str] = None,
    effort: Optional[str] = None,
    expect_json: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Nest 호출. cache_prefix 는 캐싱 대상 고정 prefix (provider별 처리, 미지원이면 무시)."""
    if cache_prefix:
        extra["cache_prefix"] = cache_prefix
    return nest_client.call(
        alias,
        prompt,
        images=images,
        audio=audio,
        system=system,
        effort=effort,
        expect_json=expect_json,
        **extra,
    )


def call_text(alias: str, prompt: str, **kw: Any) -> str:
    return (call(alias, prompt, **kw).get("text") or "").strip()


def embed(alias: str, inputs, **kw: Any) -> Dict[str, Any]:
    return nest_client.embed(alias, inputs, **kw)


def embed_one(alias: str, text: str, **kw: Any) -> List[float]:
    return nest_client.embed_one(alias, text, **kw)


def default_alias(prefer_vision: bool = False) -> Optional[str]:
    return nest_client.default_alias(prefer_vision=prefer_vision)

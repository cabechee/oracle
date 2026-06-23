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
    timeout: Optional[float] = None,   # per-call (일기·회고처럼 긴 생성용)
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
        timeout=timeout,
        **extra,
    )


# 생성 호출 재시도 — 일시적 실패만 다시 시도. 인증(401)·권한 같은 영구 오류는
# 재시도해도 같으니 즉시 포기 → 호출자가 결과를 저장하지 않고 슬롯을 비운다.
_TRANSIENT_HINTS = (
    "overloaded", "529", "500", "502", "503", "504",
    "timeout", "timed out", "temporarily", "rate limit", "429", "connection",
)


def _is_transient(err: Exception) -> bool:
    """재시도할 가치가 있는 일시적 오류인가. 인증·권한 등 영구 오류면 False."""
    import httpx
    if isinstance(err, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError,
                        httpx.WriteError, httpx.RemoteProtocolError, httpx.PoolTimeout)):
        return True
    msg = str(err).lower()
    return any(h in msg for h in _TRANSIENT_HINTS)


def call_retry(alias: str, prompt: str, *, tries: int = 3,
               base_delay: float = 2.0, **kw: Any) -> Dict[str, Any]:
    """긴 생성(일기·회고·조간)용 call — 일시적 실패는 지수 백오프로 재시도.

    인증(401)·권한 같은 영구 오류, 또는 마지막 시도까지 실패하면 raise한다 →
    호출자가 결과를 저장하지 않고 슬롯을 비운다(실패 문자열을 본문으로 남기지 않음).
    """
    import time
    last: Optional[Exception] = None
    for attempt in range(max(1, tries)):
        try:
            return call(alias, prompt, **kw)
        except Exception as e:   # 분류 후 재시도하거나 전파
            last = e
            if attempt == tries - 1 or not _is_transient(e):
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise last   # 루프가 항상 return/raise — 도달하지 않음


def call_text(alias: str, prompt: str, **kw: Any) -> str:
    return (call(alias, prompt, **kw).get("text") or "").strip()


def embed(alias: str, inputs, **kw: Any) -> Dict[str, Any]:
    """임베딩 — 기본은 Nest /api/embed. ORACLE_EMBED_URL 설정 시 로컬 서버 직결.

    (chocolat 라이브 Nest가 /api/embed 미배포라 임시 우회 — Nest 갱신 후
    env에서 ORACLE_EMBED_URL 지우면 원래 경로로 복귀.)
    """
    from config import EMBED_DIRECT_URL
    if EMBED_DIRECT_URL:
        return _embed_direct(EMBED_DIRECT_URL, inputs)
    return nest_client.embed(alias, inputs, **kw)


# 임베딩 입력 길이 캡 — llama-server는 입력이 ubatch(4096토큰)를 넘으면 거부.
# 한국어 ~1.5자/토큰 기준 안전 마진. 검색 품질은 앞부분 수천 자로 충분 — 정본은 그대로.
_EMBED_MAX_CHARS = 3500


def _embed_direct(url: str, inputs) -> Dict[str, Any]:
    """OpenAI 호환 /v1/embeddings 직접 호출 → Nest embed 응답 shape로 변환."""
    import httpx
    if isinstance(inputs, str):
        inputs = [inputs]
    inputs = [t[:_EMBED_MAX_CHARS] for t in inputs]
    r = httpx.post(url, json={"input": inputs}, timeout=60)
    r.raise_for_status()
    data = r.json()
    vecs = [item["embedding"] for item in data.get("data", [])]
    if not vecs:
        raise RuntimeError(f"임베딩 빈 결과: {data}")
    return {
        "ok": True,
        "provider": "local-direct",
        "model": data.get("model") or "local-embed",
        "embeddings": vecs,
        "dims": len(vecs[0]),
        "count": len(vecs),
    }


def embed_one(alias: str, text: str, **kw: Any) -> List[float]:
    return nest_client.embed_one(alias, text, **kw)


def default_alias(prefer_vision: bool = False) -> Optional[str]:
    return nest_client.default_alias(prefer_vision=prefer_vision)

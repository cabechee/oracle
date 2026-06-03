"""Nest LLM 게이트웨이 HTTP 클라이언트.

모든 LLM 호출은 이걸 통한다. Nest가 provider/model/effort/account 셋업을 다 처리하므로
oracle은 task → alias 매핑만 가지면 끝.

핵심 호출: nest_client.call(alias, prompt, images=[...], system=..., effort=...).

이미지 인자 = Nest가 받는 형식: `[{"b64": "...", "mime": "image/jpeg"}]` 또는
`[{"path": "/abs/..."}]`. path 는 Nest 머신(chocolat) 로컬에서 해석되므로
oracle처럼 다른 머신에서 호출할 땐 base64 권장. `images_from_paths()` 헬퍼 사용.
"""

import base64
import os
from typing import Optional, List, Dict, Any

import httpx

from config import NEST_BASE_URL, NEST_TOKEN, NEST_TIMEOUT


_MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "webp": "image/webp",
    "gif": "image/gif", "heic": "image/heic",
}


_client: Optional[httpx.Client] = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        if not NEST_TOKEN:
            raise RuntimeError(
                "NEST_TOKEN 미설정 — .env에 채울 것 (또는 환경변수로)."
            )
        _client = httpx.Client(
            base_url=NEST_BASE_URL,
            headers={"X-Nest-Token": NEST_TOKEN},
            timeout=NEST_TIMEOUT,
        )
    return _client


def call(
    alias: str,
    prompt: str,
    *,
    images: Optional[List[Dict[str, str]]] = None,
    system: Optional[str] = None,
    effort: Optional[str] = None,
    expect_json: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Nest /api/call. 반환: {ok, provider, model, text, duration_ms, ...}.

    images: [{"path": "/abs/path.jpg"}] — Nest가 절대경로 요구.
    """
    payload: Dict[str, Any] = {"alias": alias, "prompt": prompt}
    if images:
        payload["images"] = images
    if system is not None:
        payload["system"] = system
    if effort is not None:
        payload["effort"] = effort
    if expect_json:
        payload["expect_json"] = True
    payload.update(extra)

    r = _http().post("/api/call", json=payload)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Nest call 실패: {data}")
    return data


def call_text(alias: str, prompt: str, **kwargs: Any) -> str:
    """편의 — text 필드만 strip해서 반환."""
    return (call(alias, prompt, **kwargs).get("text") or "").strip()


def images_from_paths(paths: List[str]) -> List[Dict[str, str]]:
    """로컬 파일 경로 리스트 → Nest용 base64 이미지 리스트.

    oracle(bert) ↔ Nest(chocolat)가 다른 머신이라 path 직접 전달 불가 →
    파일 읽어서 base64로 인라인 전송. Nest가 cli 백엔드용으로 tmp에 떨궈줌.
    """
    out: List[Dict[str, str]] = []
    for p in paths:
        ext = p.rsplit(".", 1)[-1].lower() if "." in p else "jpg"
        mime = _MIME_BY_EXT.get(ext, "image/jpeg")
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        out.append({"b64": b64, "mime": mime})
    return out


def list_models() -> List[Dict[str, Any]]:
    """Nest에 등록된 모델 alias 목록. 폰 LLM 선택 UI용."""
    r = _http().get("/api/models")
    r.raise_for_status()
    return r.json()


def list_councils() -> List[Dict[str, Any]]:
    """Nest에 등록된 council(다중 모델 합성) alias 목록."""
    r = _http().get("/api/councils")
    r.raise_for_status()
    return r.json()


def default_alias(prefer_vision: bool = False) -> Optional[str]:
    """Nest에 등록된 enabled 모델 중 첫 alias 반환 — 매 호출 시 fresh fetch.

    prefer_vision=True면 vision 지원 모델만 후보. 없으면 None.
    Nest 도달 실패도 None — 호출자가 에러 처리.

    *동적*: Nest registry에 모델 추가/제거하면 즉시 반영(캐시 없음).
    """
    try:
        models = list_models()
    except Exception:
        return None
    enabled = [m for m in models if m.get("enabled")]
    if prefer_vision:
        v = [m for m in enabled if m.get("vision")]
        if v:
            return v[0].get("alias")
    if enabled:
        return enabled[0].get("alias")
    return None


def health() -> Dict[str, Any]:
    """Nest health (토큰 불필요)."""
    return httpx.get(f"{NEST_BASE_URL}/api/health", timeout=5).json()

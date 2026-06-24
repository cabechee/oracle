"""공유 이미지 라우터 — 수집기/앱이 공유한 이미지를 분류해 적절한 곳으로 라우팅.

분류기(vision)가 앞단에서 종류를 판별한다 — '무조건 영수증으로' 보내던 것 교체:
  receipt → 가계부(영수증) · calendar → 캘린더(일정) · note → 흐름 기록.
실패/애매하면 note(흐름 기록)로 폴백. 타입은 vision.classify_share_image에서 확장.
"""

import base64

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

router = APIRouter()


@router.post("/share/image")
def ep_share_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """공유 이미지 1장 → 분류 → 라우팅. 반환 {kind: receipt|calendar|note, ...처리결과}."""
    data = file.file.read()
    if not data:
        raise HTTPException(400, "빈 파일")
    import corpus
    import ingest
    import embedding as embedding_mod
    from agent import vision
    from .ledger import process_receipt_image
    from .calendar import process_calendar_image

    fname = file.filename or ""
    low = fname.lower()
    is_pdf = low.endswith(".pdf") or data[:5] == b"%PDF-"
    alias = ingest._resolve_alias("vision", None, prefer_vision=True, fallback_key="insight")

    # PDF는 영수증 전용(일정/메모 PDF는 드묾) — 분류 없이 영수증 경로.
    if is_pdf:
        return {"kind": "receipt", **process_receipt_image(data, fname)}

    # 1) 분류 — base64 in-memory(저장은 각 경로가 함). 실패/애매하면 note.
    try:
        b64 = base64.b64encode(corpus._bake_orientation(data)).decode("ascii")
        kind = vision.classify_share_image(alias, [{"b64": b64, "mime": "image/jpeg"}])
    except Exception:
        kind = "note"

    # 2) 라우팅 — 영수증/일정은 처리 실패 시 note로 폴백.
    if kind == "receipt":
        r = process_receipt_image(data, fname)
        if r.get("ok"):
            return {"kind": "receipt", **r}
        kind = "note"

    if kind == "calendar":
        import gcal
        if gcal.is_authed():
            r = process_calendar_image(data, fname)
            if r.get("ok"):
                return {"kind": "calendar", **r}
        kind = "note"

    # 3) note — 흐름 기록(ingest). 검색 임베딩은 응답 후 백그라운드.
    ext = "jpg"
    if "." in low:
        e = low.rsplit(".", 1)[-1]
        if e in ("jpg", "jpeg", "png", "webp", "heic"):
            ext = "jpg" if e == "jpeg" else e
    result = ingest.ingest(None, [(data, ext)])
    rid = result.get("record_id")
    if rid:
        background_tasks.add_task(embedding_mod.embed_record, rid)
    return {"kind": "note", "ok": True, "record_id": rid}

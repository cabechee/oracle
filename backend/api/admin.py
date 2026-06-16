"""어드민 라우터 — 데이터 조회·삭제·신호 강제 요약 (개인 운영툴)."""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

import admin as admin_mod

router = APIRouter(prefix="/admin/api")


@router.get("/stats")
def ep_stats():
    try:
        return admin_mod.stats()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/collection/{name}")
def ep_list(name: str, limit: int = 50, skip: int = 0, q: Optional[str] = None):
    try:
        return admin_mod.list_docs(name, limit=limit, skip=skip, q=q)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/collection/{name}/{doc_id}")
def ep_get(name: str, doc_id: str):
    try:
        d = admin_mod.get_doc(name, doc_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if d is None:
        raise HTTPException(404, "not found")
    return d


@router.delete("/collection/{name}/{doc_id}")
def ep_delete(name: str, doc_id: str):
    try:
        ok = admin_mod.delete_doc(name, doc_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if not ok:
        raise HTTPException(404, "not found")
    return {"ok": True}


@router.post("/signals/rebrief")
def ep_rebrief():
    try:
        return admin_mod.rebrief_signals()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/personas")
def ep_get_personas():
    try:
        return admin_mod.get_personas()
    except Exception as e:
        raise HTTPException(500, str(e))


class PersonaBody(BaseModel):
    key: str
    value: str = ""   # 비우면 디폴트 복귀


@router.post("/personas")
def ep_set_persona(body: PersonaBody):
    try:
        admin_mod.set_persona(body.key, body.value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/signal-excludes")
def ep_get_signal_excludes():
    try:
        return admin_mod.get_signal_excludes()
    except Exception as e:
        raise HTTPException(500, str(e))


class ExcludesBody(BaseModel):
    patterns: List[str] = []


@router.post("/signal-excludes")
def ep_set_signal_excludes(body: ExcludesBody):
    try:
        admin_mod.set_signal_excludes(body.patterns)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True}


@router.get("/task-aliases")
def ep_get_task_aliases():
    try:
        return admin_mod.get_task_aliases()
    except Exception as e:
        raise HTTPException(500, str(e))


class TaskAliasBody(BaseModel):
    key: str
    value: str = ""   # 비우면 env 디폴트 복귀


@router.post("/task-aliases")
def ep_set_task_alias(body: TaskAliasBody):
    try:
        admin_mod.set_task_alias(body.key, body.value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/companion-config")
def ep_get_companion_config():
    try:
        return admin_mod.get_companion_config()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/companion-config")
def ep_set_companion_config(patch: Dict[str, Any] = Body(...)):
    """말 걸기 설정 부분 갱신 — 보낸 키만 반영(알려진 키만 정규화)."""
    try:
        return admin_mod.set_companion_config(patch)
    except Exception as e:
        raise HTTPException(500, str(e))

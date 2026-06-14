"""리마인더 라우터 — 자체 할 일 CRUD + 신호 액션 승격 (외부 연동 없음)."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import reminders as reminders_mod

router = APIRouter()


class AddReminder(BaseModel):
    text: str
    due: Optional[str] = None          # ISO 또는 None
    source: str = "manual"             # manual | signal
    signal_id: Optional[str] = None    # action_needed 승격 시 멱등 키


@router.get("/reminders")
def ep_list(include_done: bool = False):
    return {"items": reminders_mod.list_items(include_done=include_done)}


@router.post("/reminders")
def ep_add(body: AddReminder):
    rid = reminders_mod.add(body.text, body.due, body.source, body.signal_id)
    if not rid:
        raise HTTPException(400, "text required")
    return {"id": rid}


class DoneBody(BaseModel):
    done: bool = True


@router.post("/reminders/{rid}/done")
def ep_done(rid: str, body: DoneBody):
    if not reminders_mod.set_done(rid, body.done):
        raise HTTPException(404, "not found")
    return {"ok": True}


@router.delete("/reminders/{rid}")
def ep_remove(rid: str):
    reminders_mod.remove(rid)
    return {"ok": True}

"""'Ask your org' chatbot endpoint — see ``api/org_chat.py`` for the
Groq-backed tool-calling implementation this wraps.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import OrgRecord
from companysim.api.org_chat import ask_org, is_chat_enabled
from companysim.api.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/orgs/{org_id}/chat", tags=["chat"])


def _get_org_or_404(db: Session, org_id: int) -> OrgRecord:
    org = db.get(OrgRecord, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    return org


@router.post("", response_model=ChatResponse)
def ask_org_chat(org_id: int, req: ChatRequest, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)

    if not is_chat_enabled():
        return ChatResponse(
            reply="Ask-your-org chat isn't configured on this server — it needs both "
                  "GROQ_API_KEY and COMPANYSIM_LLM_CHAT=1 set (see the README).",
            llm_available=False,
        )

    try:
        result = ask_org(
            db, org_id, req.message,
            [h.model_dump() for h in req.history],
        )
    except Exception:
        return ChatResponse(
            reply="The chat assistant is temporarily unavailable — please try again.",
            llm_available=True,
        )

    return ChatResponse(reply=result.reply, tools_used=result.tools_used, llm_available=True)

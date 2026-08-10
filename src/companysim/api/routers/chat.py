"""'Ask your org' chatbot endpoint — see ``api/org_chat.py`` for the
tool-calling implementation this wraps.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import OrgRecord
from companysim.api.llm_usage import record_llm_calls
from companysim.api.org_chat import ask_org, is_chat_enabled
from companysim.api.schemas import ChatRequest, ChatResponse
from companysim.llm import provider
from companysim.llm.usage import collect

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
        reason = provider.unavailable_reason("COMPANYSIM_LLM_CHAT") or ""
        return ChatResponse(
            reply=f"Ask-your-org chat isn't configured on this server. {reason}",
            llm_available=False,
        )

    # The collect block wraps the try, not the happy path: a question that
    # burns three tool-calling round trips and then fails on the fourth
    # still cost those tokens, and a usage counter that only logs successes
    # under-reports exactly when you most want the number.
    with collect() as calls:
        try:
            result = ask_org(
                db, org_id, req.message,
                [h.model_dump() for h in req.history],
            )
        except Exception:
            record_llm_calls(db, calls, org_id=org_id)
            return ChatResponse(
                reply="The chat assistant is temporarily unavailable — please try again.",
                llm_available=True,
            )
    record_llm_calls(db, calls, org_id=org_id)

    return ChatResponse(reply=result.reply, tools_used=result.tools_used, llm_available=True)

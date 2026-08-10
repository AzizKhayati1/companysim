"""companysim.llm — plumbing shared by every LLM-backed feature.

Three features call an LLM (``ml/llm_exit_notes.py``, ``api/org_chat.py``,
``ingest/llm_parser.py``) and each was independently reading
``GROQ_API_KEY`` and building its own client. This package holds what they
genuinely share: ``provider`` (which backend serves a call, and the
translation that makes Groq and AWS Bedrock interchangeable) and ``usage``
(token accounting).
"""

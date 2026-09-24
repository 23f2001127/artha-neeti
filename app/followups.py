"""Follow-up questions on a finished research job.

``ask`` answers synchronously with one LLM call. ``create_escalation_job``
creates the row for a new research run that continues the conversation;
app/main.py starts it the same way as POST /research.
"""

from __future__ import annotations

import asyncio

from agents.followup_agent import answer_followup
from app import db


class FollowupError(ValueError):
    """A bad request (not our fault to retry) - job not found/not done, etc."""


async def ask(job_id: str, query: str) -> dict:
    row = await asyncio.to_thread(db.get_job, job_id)
    if row is None:
        raise FollowupError("job not found.")
    if row["status"] != "done" or not row.get("report"):
        raise FollowupError(f"job is '{row['status']}' - follow-ups need a finished report.")

    conversation_id = row["conversation_id"] or job_id
    prior_turns = await asyncio.to_thread(db.get_followup_turns, conversation_id)

    result = await answer_followup(row["query"], row["report"], prior_turns, query)
    if "error" in result:
        return result

    await asyncio.to_thread(
        db.create_followup_turn,
        conversation_id=conversation_id,
        job_id=job_id,
        query=query,
        sufficient_data=result["sufficient_data"],
        answer=result.get("answer"),
        caveat=result.get("caveat"),
        missing_reason=result.get("missing_reason"),
        standalone_query=result.get("standalone_query"),
    )
    return result


def create_escalation_job(job_id: str, standalone_query: str) -> str:
    """Creates the new job row (conversation_id inherited, parent_job_id set)
    and returns its id. Starting the background task is the caller's job -
    see POST /research/{job_id}/followups/escalate in app/main.py, which
    dispatches it exactly like POST /research does."""
    row = db.get_job(job_id)
    if row is None:
        raise FollowupError("job not found.")
    if not standalone_query or not standalone_query.strip():
        raise FollowupError("standalone_query is empty.")

    conversation_id = row["conversation_id"] or job_id
    return db.create_job(standalone_query.strip(), conversation_id=conversation_id, parent_job_id=job_id)

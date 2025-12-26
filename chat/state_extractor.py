# chat/state_extractor.py

import logging
from typing import Dict, Any

logger = logging.getLogger("ask_paragraph.state")


def extract_state(session: Dict[str, Any]) -> Dict[str, Any]:
    dialogs = session.get("dialogs", [])
    concept = session.get("current_concept") or {}

    if not concept:
        logger.debug("[STATE] No concept metadata found → defaulting to MCQ mode")

    # Find last assistant message safely
    last_assistant = next(
        (d for d in reversed(dialogs) if d.get("role") == "assistant"),
        None
    )

    last_block = (
        detect_last_block(last_assistant["content"])
        if last_assistant and isinstance(last_assistant.get("content"), str)
        else "UNKNOWN"
    )

    state = {
        "phase": concept.get("status", "mcq_teaching"),
        "concept_index": concept.get("index", 0),
        "concept_title": concept.get("title", "MCQ Discussion"),
        "turns": len(dialogs),
        "last_block": last_block,
    }

    logger.debug(
        "[STATE] phase=%s last_block=%s turns=%s",
        state["phase"],
        state["last_block"],
        state["turns"],
    )

    return state


def detect_last_block(text: str) -> str:
    if not text or not isinstance(text, str):
        return "UNKNOWN"

    for block in [
        "[STUDENT_REPLY_REQUIRED]",
        "[FEEDBACK_CORRECT]",
        "[FEEDBACK_WRONG]",
        "[CLARIFICATION]",
        "[FINAL_ANSWER]",
    ]:
        if block in text:
            logger.debug("[STATE] Detected semantic block %s", block)
            return block

    return "UNKNOWN"

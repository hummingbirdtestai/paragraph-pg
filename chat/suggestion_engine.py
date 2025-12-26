# chat/suggestion_engine.py

import logging
from typing import Dict, Any, List

from gpt_utils import chat_with_gpt
from chat.suggestions_catalog import SUGGESTION_CATALOG

logger = logging.getLogger("ask_paragraph.suggestions")


def generate_suggestions(state: Dict[str, Any]) -> List[Dict[str, str]]:
    phase = state.get("phase")

    logger.debug(
        "[SUGGESTIONS] Generating suggestions | phase=%s last_block=%s turns=%s",
        phase,
        state.get("last_block"),
        state.get("turns"),
    )

    allowed = SUGGESTION_CATALOG.get(phase, [])

    if not allowed:
        logger.debug(
            "[SUGGESTIONS] No suggestions available for phase=%s", phase
        )
        return []

    logger.debug(
        "[SUGGESTIONS] Allowed actions count=%s", len(allowed)
    )

    allowed_text = "\n".join(
        f"- {a['id']}: {a['label']}" for a in allowed
    )

    prompt = f"""
You are deciding the NEXT BEST actions for a student.

Conversation state:
- Concept: {state.get('concept_title')}
- Concept index: {state.get('concept_index')}
- Phase: {state.get('phase')}
- Last mentor block: {state.get('last_block')}
- Turns so far: {state.get('turns')}

Choose up to 3 actions from the list below.
DO NOT invent new actions.
DO NOT explain.
Return ONLY action IDs, one per line.

Allowed actions:
{allowed_text}
"""

    reply = chat_with_gpt(
        [
            {"role": "system", "content": "You are a UX decision engine."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    chosen_ids = [
        line.strip()
        for line in reply.splitlines()
        if line.strip()
    ]

    logger.debug(
        "[SUGGESTIONS] GPT selected action IDs=%s", chosen_ids
    )

    final = [
        a for a in allowed
        if a["id"] in chosen_ids
    ]

    logger.debug(
        "[SUGGESTIONS] Final suggestions returned=%s",
        [f["id"] for f in final],
    )

    return final

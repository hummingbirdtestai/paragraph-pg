from gpt.client import client
from chat.suggestions_catalog import SUGGESTION_CATALOG

def generate_suggestions(state):
    phase = state["phase"]
    allowed = SUGGESTION_CATALOG.get(phase, [])

    if not allowed:
        return []

    allowed_text = "\n".join(
        f"- {a['id']}: {a['label']}" for a in allowed
    )

    prompt = f"""
You are deciding the NEXT BEST actions for a student.

Conversation state:
- Concept: {state['concept_title']}
- Concept index: {state['concept_index']}
- Phase: {state['phase']}
- Last mentor block: {state['last_block']}
- Turns so far: {state['turns']}

Choose up to 3 actions from the list below.
DO NOT invent new actions.
DO NOT explain.
Return ONLY action IDs, one per line.

Allowed actions:
{allowed_text}
"""

    res = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            { "role": "system", "content": "You are a UX decision engine." },
            { "role": "user", "content": prompt }
        ],
        temperature=0.2
    )

    chosen_ids = [
        line.strip()
        for line in res.choices[0].message.content.splitlines()
        if line.strip()
    ]

    # Map IDs back to labels
    return [
        a for a in allowed
        if a["id"] in chosen_ids
    ]

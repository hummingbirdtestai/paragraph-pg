def extract_state(session):
    dialogs = session["dialogs"]
    concept = session["current_concept"]

    last_assistant = next(
        (d for d in reversed(dialogs) if d["role"] == "assistant"),
        None
    )

    return {
        "phase": concept["status"],          # teaching / clarified / completed
        "concept_index": concept["index"],
        "concept_title": concept["title"],
        "turns": len(dialogs),
        "last_block": detect_last_block(last_assistant["content"])
    }


def detect_last_block(text: str) -> str:
    for block in [
        "[STUDENT_REPLY_REQUIRED]",
        "[FEEDBACK_CORRECT]",
        "[FEEDBACK_WRONG]",
        "[CLARIFICATION]",
        "[FINAL_ANSWER]"
    ]:
        if block in text:
            return block
    return "UNKNOWN"

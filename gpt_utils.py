# gpt_utils.py
import os
from typing import List, Dict, Generator, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# OpenAI Client (single instance)
# ------------------------------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DEFAULT_MODEL = "gpt-4o-mini"


# ------------------------------------------------------------------
# NON-STREAMING GPT CALL (USED FOR /start, summaries, tools)
# ------------------------------------------------------------------
def chat_with_gpt(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.4,
) -> str:
    """
    Standard (non-streaming) GPT call.
    Returns full assistant message.
    """

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )

    return response.choices[0].message.content


# ------------------------------------------------------------------
# STREAMING GPT CALL (USED FOR /chat)
# ------------------------------------------------------------------
def stream_chat_with_gpt(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.4,
) -> Generator[str, None, None]:
    """
    Streams GPT output token-by-token.
    Yields plain text chunks.
    """

    stream = client.chat.completions.stream(
        model=model,
        messages=messages,
        temperature=temperature,
    )

    for event in stream:
        # Text deltas only (ignore tool calls, metadata, etc.)
        if event.type == "response.output_text.delta":
            yield event.delta


# ------------------------------------------------------------------
# SAFE SUMMARIZATION HELPER (OPTIONAL, BACKEND USE)
# ------------------------------------------------------------------
def summarize_dialogs(
    dialogs: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Summarizes conversation state safely.
    """

    summary_prompt = [
        {
            "role": "system",
            "content": (
                "Summarize the learning state so far.\n"
                "- Current concept being taught\n"
                "- Student misconceptions\n"
                "- What has been clarified\n"
                "- What remains\n\n"
                "Do NOT add new teaching."
            ),
        },
        {
            "role": "user",
            "content": str(dialogs),
        },
    ]

    response = client.chat.completions.create(
        model=model,
        messages=summary_prompt,
        temperature=0.2,
    )

    return response.choices[0].message.content

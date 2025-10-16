# gpt_utils.py
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def chat_with_gpt(prompt: str, phase_json: dict, student_message: str = None):
    """
    Combines your system prompt + phase context + student's message,
    then calls GPT for a conversational mentor reply.
    """
    context = f"{prompt}\n\nPhase Context:\n{phase_json}"
    if student_message:
        context += f"\n\nStudent: {student_message}"

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a kind and knowledgeable medical mentor."},
            {"role": "user", "content": context},
        ],
        temperature=0.8
    )

    return completion.choices[0].message.content

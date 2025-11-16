from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import datetime
from openai import OpenAI
from supabase import create_client, Client


# -------------------------
# Setup
# -------------------------
app = FastAPI(title="Practice Progress Analysis API")

app = CORSMiddleware(
    app=app,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not SUPABASE_URL:
    raise Exception("❌ Missing SUPABASE_URL")
if not SUPABASE_SERVICE_ROLE:
    raise Exception("❌ Missing SUPABASE_SERVICE_ROLE_KEY")
if not OPENAI_API_KEY:
    raise Exception("❌ Missing OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------
# Request Model
# -------------------------
class ProgressRequest(BaseModel):
    student_id: str
    student_name: str


# -------------------------
# EXISTING PROMPTS (unchanged)
# -------------------------
def build_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru ...
STUDENT DATA:
{progress_json}
"""


def build_accuracy_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru ...
STUDENT DATA:
{progress_json}
"""


# -------------------------
# GPT Generators (existing)
# -------------------------
def generate_mentor_comment(progress_json, student_name):
    prompt = build_prompt(progress_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


def generate_accuracy_comment(progress_json, student_name):
    prompt = build_accuracy_prompt(progress_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


# -------------------------
# EXISTING ENDPOINTS UNCHANGED
# -------------------------
@app.post("/progress/analysis")
def get_practice_progress_analysis(request: ProgressRequest):
    ...
    # unchanged
    ...


@app.post("/accuracy/analysis")
def get_accuracy_analysis(request: ProgressRequest):
    ...
    # unchanged
    ...


# -------------------------
# HEALTH CHECK
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress API running 🚀"}



# ============================================================
# 🚀 LEARNING-GAP (existing) — unchanged
# ============================================================
def build_learning_gap_prompt(gap_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru ...
STUDENT DATA:
{gap_json}
"""


def generate_learning_gap_comment(gap_json, student_name):
    prompt = build_learning_gap_prompt(gap_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


@app.post("/learning-gap/analysis")
def get_learning_gap_analysis(request: ProgressRequest):
    ...
    # unchanged
    ...


# ============================================================
# 🚀 NEW FEATURE — FLASHCARD MASTERY PROGRESS
# ============================================================

def build_flashcard_mastery_prompt(flash_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru who trained a Million Doctors for NEETPG Exam and know the trajectory of NEETPG Aspirants at various levels of preparation—from the start of their journey to the day of exam when they have mastered all the High Yield topics, PYQs, integrated concepts, and perfected the high-yield facts. 

These are the Metrics of how they consumed the Flash cards across 19 Subjects for NEETPG.

Advise this Student based on the Active Recall and Spaced repetition Revision with Flash cards metrics.  
Address the student directly by Name: {student_name}.

Use these definitions based on flashcard mastery progress:  
• total_decks = number of flashcard decks in the subject  
• completed_decks = number of decks the student has finished  
• completion_percent = completed_decks ÷ total_decks × 100  
• average_time_per_deck_minutes = average minutes taken to complete a deck  
• estimated_time_to_complete_all_minutes = projected minutes needed to finish remaining decks  
• total_bookmarks = decks marked for revision  
• last_activity = timestamp of last revision attempt  

Your output:  
Write a **crisp, powerful, emotionally intelligent 500-word mentor message** that:  
• interprets Active Recall strength  
• evaluates spaced repetition consistency  
• analyses subject-wise mastery  
• evaluates memory curve & revision patterns  
• highlights strong vs weak subjects  
• gives actionable strategy  
• uses Unicode (α, β, γ, Δ, Na⁺/K⁺, x², etc.)  
• speaks directly and empathetically to {student_name}  
• does NOT repeat JSON  
• does NOT include headings  
• and must be a continuous mentor letter.

STUDENT DATA:
{flash_json}
"""


def generate_flashcard_mastery_comment(flash_json, student_name):
    prompt = build_flashcard_mastery_prompt(flash_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


# -------------------------
# NEW ENDPOINT — FLASHCARD MASTERY PROGRESS
# -------------------------
@app.post("/flashcards/mastery")
def get_flashcard_mastery_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # Check cached
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "flashcard_mastery")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last_time = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last_time) < datetime.timedelta(hours=24):
            rpc_res = supabase.rpc(
                "get_flashcard_mastery_progress",
                {"student_id": student_id}
            ).execute()

            flash_json = rpc_res.data

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": flash_json,
            }

    # Fresh RPC call
    rpc_res = supabase.rpc(
        "get_flashcard_mastery_progress",
        {"student_id": student_id}
    ).execute()

    if rpc_res.data is None:
        raise HTTPException(400, "RPC returned no data")

    flash_json = rpc_res.data

    # Generate mentor letter
    mentor_comment = generate_flashcard_mastery_comment(flash_json, student_name)

    # Save
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "flashcard_mastery"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": flash_json
    }

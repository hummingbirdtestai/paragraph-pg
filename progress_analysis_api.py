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

# ✅ CORRECT CORS MIDDLEWARE (do NOT overwrite app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------
# Environment Variables
# -------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not SUPABASE_URL:
    raise Exception("❌ Missing SUPABASE_URL")
if not SUPABASE_SERVICE_ROLE:
    raise Exception("❌ Missing SUPABASE_SERVICE_ROLE_KEY")
if not OPENAI_API_KEY:
    raise Exception("❌ Missing OPENAI_API_KEY")

# Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------
# Request Model
# -------------------------
class ProgressRequest(BaseModel):
    student_id: str
    student_name: str


# -------------------------
# PROMPTS — PROGRESS
# -------------------------
def build_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru who trained a Million Doctors...

STUDENT DATA:
{progress_json}
"""


# -------------------------
# PROMPTS — ACCURACY
# -------------------------
def build_accuracy_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru...

STUDENT DATA:
{progress_json}
"""


# -------------------------
# GENERATORS
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
# ENDPOINT — PROGRESS
# -------------------------
@app.post("/progress/analysis")
def get_practice_progress_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "practice_progress")
        .order("updated_at", desc=True)
        .execute()
    )

    # Return cached if < 24 hours old
    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_progress_mastery_with_time",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    # Fresh call
    rpc_res = supabase.rpc(
        "get_progress_mastery_with_time",
        {"student_id": student_id}
    ).execute()

    progress_json = rpc_res.data
    if progress_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_mentor_comment(progress_json, student_name)

    # Save
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "practice_progress"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": progress_json
    }


# -------------------------
# ENDPOINT — ACCURACY
# -------------------------
@app.post("/accuracy/analysis")
def get_accuracy_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "practice_accuracy")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]

        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_accuracy_performance_fast",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    rpc_res = supabase.rpc(
        "get_accuracy_performance_fast",
        {"student_id": student_id}
    ).execute()

    progress_json = rpc_res.data
    if progress_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_accuracy_comment(progress_json, student_name)

    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "practice_accuracy"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": progress_json
    }


# -------------------------
# HEALTH CHECK
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress API running 🚀"}


# ============================================================
# LEARNING-GAP
# ============================================================
def build_learning_gap_prompt(gap_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru...

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

    student_id = request.student_id
    student_name = request.student_name

    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "flashcard_learning_gap")
        .order("updated_at", desc=True)
        .execute()
    )

    # cached logic
    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_deep_learning_gap",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    rpc_res = supabase.rpc(
        "get_deep_learning_gap",
        {"student_id": student_id}
    ).execute()

    gap_json = rpc_res.data
    if gap_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_learning_gap_comment(gap_json, student_name)

    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "flashcard_learning_gap"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": gap_json
    }


# ============================================================
# FLASHCARD MASTERY PROGRESS
# ============================================================
def build_flashcard_mastery_prompt(flash_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru...

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


@app.post("/flashcards/mastery")
def get_flashcard_mastery_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

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
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_flashcard_mastery_progress",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    rpc_res = supabase.rpc(
        "get_flashcard_mastery_progress",
        {"student_id": student_id}
    ).execute()

    flash_json = rpc_res.data
    if flash_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_flashcard_mastery_comment(flash_json, student_name)

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

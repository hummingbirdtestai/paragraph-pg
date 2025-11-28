from fastapi import APIRouter, UploadFile, File, Form
from typing import List
from openai import OpenAI
from supabase import create_client, Client
import os
import uuid
import json

router = APIRouter()

# Initialize OpenAI + Supabase
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY"))

# -------------------------------------------------------------------
# 🔥 TOKEN-FRIENDLY PROMPT (Final Version)
# -------------------------------------------------------------------
def build_prompt(content_text: str):
    return f"""
Rewrite text for NEET-PG aspirants (clear, concise, exam-oriented). 
Extract 5–10 relevant medical hashtags. 
Classify the post into ONE of these 19 NEET-PG subjects:
["Anatomy","Physiology","Biochemistry","Pathology","Pharmacology",
"Microbiology","Forensic Medicine","PSM (Community Medicine)","Ophthalmology",
"ENT","Medicine","Surgery","ObGyn","Pediatrics","Orthopedics",
"Anesthesia","Dermatology","Psychiatry","Radiology"]

Return ONLY JSON:
{{
 "rewritten_text": "...",
 "hashtags": ["..."],
 "subject": "SubjectName"
}}

USER TEXT:
{content_text}
"""


# -------------------------------------------------------------------
# 🔥 ENDPOINT: Create AI-Processed Feed Post 
# -------------------------------------------------------------------
@router.post("/create_feed_post_ai")
async def create_feed_post_ai(
    user_id: str = Form(...),
    title: str = Form(""),
    content_text: str = Form(""),
    files: List[UploadFile] = File(None)
):

    # ---------------------------------------------------------------
    # 1️⃣ Upload Multiple Images to Supabase
    # ---------------------------------------------------------------
    media_urls = []

    if files:
        for f in files:
            ext = f.filename.split(".")[-1]
            file_name = f"{uuid.uuid4()}.{ext}"
            file_path = f"posts/{file_name}"

            file_bytes = await f.read()

            supabase.storage.from_("feed-posts").upload(
                file_path,
                file_bytes,
                {"content-type": f.content_type}
            )

            public = supabase.storage.from_("feed-posts").get_public_url(file_path)
            media_urls.append(public)

    # ---------------------------------------------------------------
    # 2️⃣ GPT: Rewrite + Hashtags + Subject
    # ---------------------------------------------------------------
    final_prompt = build_prompt(content_text)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": final_prompt}],
    )

    raw_output = response.choices[0].message["content"]
    ai = json.loads(raw_output)

    rewritten = ai["rewritten_text"]
    hashtags = ai["hashtags"]
    subject = ai["subject"]

    # Auto-map hashtags to subject/chapter/topic
    chapter = hashtags[1] if len(hashtags) > 1 else None
    topic   = hashtags[2] if len(hashtags) > 2 else None

    # ---------------------------------------------------------------
    # 3️⃣ CALL SUPABASE RPC: create_feed_post_v3
    # ---------------------------------------------------------------
    { 
        "user_id": "uuid",
        "title": "text",
        "content_text": "text",
        "media_url": ["text"],
        "media_type": "text",
        "subject": "text",
        "chapter": "text",
        "topic": "text"
    }

    rpc_payload = {
        "p_user_id": user_id,
        "p_title": title,
        "p_content_text": rewritten,
        "p_media_url": media_urls if len(media_urls) > 0 else None,
        "p_media_type": "image" if len(media_urls) > 0 else None,
        "p_subject": subject,
        "p_chapter": chapter,
        "p_topic": topic,
    }

    rpc = supabase.rpc("create_feed_post_v3", rpc_payload).execute()

    # ---------------------------------------------------------------
    # 4️⃣ Return Final AI-Processed Object to Frontend
    # ---------------------------------------------------------------
    return {
        "message": "Post created successfully",
        "rewritten_text": rewritten,
        "hashtags": hashtags,
        "subject": subject,
        "media_urls": media_urls,
        "db_response": rpc.data
    }

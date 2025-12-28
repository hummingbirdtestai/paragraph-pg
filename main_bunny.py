# ---------------- MAIN_BUNNY.PY ----------------

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ----------------

BUNNY_STORAGE_ZONE = os.getenv("BUNNY_STORAGE_ZONE")
BUNNY_API_KEY = os.getenv("BUNNY_STORAGE_API_KEY")
BUNNY_PULL_ZONE = os.getenv("BUNNY_PULL_ZONE")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not all([
    BUNNY_STORAGE_ZONE,
    BUNNY_API_KEY,
    BUNNY_PULL_ZONE,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY
]):
    raise RuntimeError("Missing required environment variables")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

BUNNY_STORAGE_BASE = f"https://storage.bunnycdn.com/{BUNNY_STORAGE_ZONE}"

# ---------------- APP ----------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- HELPERS ----------------

def upload_to_bunny(file_bytes: bytes, filename: str, content_type: str) -> str:
    upload_url = f"{BUNNY_STORAGE_BASE}/{filename}"

    r = requests.put(
        upload_url,
        headers={
            "AccessKey": BUNNY_API_KEY,
            "Content-Type": content_type,
        },
        data=file_bytes,
        timeout=30,
    )

    if r.status_code not in (200, 201):
        raise RuntimeError(f"Bunny upload failed: {r.status_code}")

    return f"{BUNNY_PULL_ZONE}/{filename}"

def update_supabase(row_id: str, bunny_url: str):
    res = (
        supabase
        .table("image_concept_phase_final")
        .update({"supabase_image_url": bunny_url})
        .eq("id", row_id)
        .execute()
    )

    if not res.data:
        raise RuntimeError("Supabase update failed")

# ---------------- ENDPOINT ----------------

@app.post("/upload-image-to-bunny")
async def upload_image_to_bunny(
    file: UploadFile = File(...),
    row_id: str = Form(...)
):
    """
    Receives:
    - image file
    - row_id (uuid)

    Does:
    - uploads image to Bunny as <row_id>.<ext>
    - stores Bunny URL in supabase_image_url
    """

    try:
        # Read image
        contents = await file.read()

        # Determine extension safely
        ext = file.filename.split(".")[-1].lower()
        if ext not in ["jpg", "jpeg", "png", "webp"]:
            raise HTTPException(status_code=400, detail="Unsupported image type")

        filename = f"{row_id}.{ext}"

        # Upload to Bunny
        bunny_url = upload_to_bunny(
            contents,
            filename,
            file.content_type or "image/jpeg"
        )

        # Update Supabase
        update_supabase(row_id, bunny_url)

        return {
            "status": "ok",
            "url": bunny_url
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

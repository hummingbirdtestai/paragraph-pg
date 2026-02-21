# ---------------- BUCKET_IMAGE_BUNNY_API.PY ----------------

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime
import uuid

load_dotenv()

# ---------------- LOGGER ----------------

def log(tag: str, data=None):
    ts = datetime.utcnow().isoformat()
    if data is not None:
        print(f"[{ts}][BUCKET_BUNNY_API][{tag}]", data, flush=True)
    else:
        print(f"[{ts}][BUCKET_BUNNY_API][{tag}]", flush=True)

# ---------------- CONFIG ----------------

log("BOOT_START")

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

BUNNY_STORAGE_BASE = f"https://sg.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE}"

log("BOOT_COMPLETE", {
    "BUNNY_STORAGE_BASE": BUNNY_STORAGE_BASE,
})

# ---------------- APP ----------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- HELPERS ----------------

def upload_to_bunny(file_bytes: bytes, filename: str) -> str:

    upload_url = f"{BUNNY_STORAGE_BASE}/{filename}"

    r = requests.put(
        upload_url,
        headers={"AccessKey": BUNNY_API_KEY},
        data=file_bytes,
        timeout=30,
    )

    if r.status_code not in (200, 201):
        raise RuntimeError(f"Bunny upload failed: {r.status_code}")

    return f"{BUNNY_PULL_ZONE}/{filename}"


def update_bucket_json(schedule_id: int, image_id: str, bunny_url: str):

    log("SUPABASE_RPC_CALL", {
        "schedule_id": schedule_id,
        "image_id": image_id
    })

    res = supabase.rpc(
        "update_bucket_image_url_v1",
        {
            "p_schedule_id": schedule_id,
            "p_image_id": image_id,
            "p_bunny_url": bunny_url
        }
    ).execute()

    log("SUPABASE_RPC_DONE", res.data)


# ---------------- ENDPOINT ----------------

@app.post("/upload-bucket-image-to-bunny")
async def upload_bucket_image_to_bunny(
    file: UploadFile = File(...),
    schedule_id: int = Form(...),
    topic_id: str = Form(...),   # currently unused but future-proof
    image_id: str = Form(...)
):
    """
    Uploads image to Bunny.
    Updates image_url inside live_class_schedule.buket_image_description JSONB.
    """

    log("REQUEST_RECEIVED", {
        "schedule_id": schedule_id,
        "topic_id": topic_id,
        "image_id": image_id,
        "filename": file.filename
    })

    try:

        # ---------------- VALIDATION ----------------

        try:
            uuid.UUID(image_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid image_id UUID")

        try:
            uuid.UUID(topic_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid topic_id UUID")

        # ---------------- READ FILE ----------------

        contents = await file.read()

        if not contents:
            raise HTTPException(status_code=400, detail="Empty file")

        ext = file.filename.split(".")[-1].lower()

        if ext not in ["jpg", "jpeg", "png", "webp"]:
            raise HTTPException(status_code=400, detail="Unsupported image type")

        # ---------------- UPLOAD TO BUNNY ----------------

        filename = f"{image_id}.{ext}"

        bunny_url = upload_to_bunny(contents, filename)

        log("BUNNY_UPLOAD_SUCCESS", bunny_url)

        # ---------------- UPDATE JSON VIA RPC ----------------

        update_bucket_json(schedule_id, image_id, bunny_url)

        log("REQUEST_SUCCESS", {
            "image_id": image_id,
            "bunny_url": bunny_url
        })

        return {
            "status": "ok",
            "schedule_id": schedule_id,
            "topic_id": topic_id,
            "image_id": image_id,
            "url": bunny_url
        }

    except HTTPException:
        raise

    except Exception as e:
        log("ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))

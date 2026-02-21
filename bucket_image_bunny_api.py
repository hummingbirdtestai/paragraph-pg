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
    print(f"[{ts}][BUCKET_IMAGE_API][{tag}] {data}", flush=True)

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
    "PULL_ZONE": BUNNY_PULL_ZONE
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

    log("BUNNY_UPLOAD_START", upload_url)

    r = requests.put(
        upload_url,
        headers={"AccessKey": BUNNY_API_KEY},
        data=file_bytes,
        timeout=30,
    )

    log("BUNNY_RESPONSE", {"status": r.status_code})

    if r.status_code not in (200, 201):
        raise RuntimeError(f"Bunny upload failed: {r.status_code}")

    return f"{BUNNY_PULL_ZONE}/{filename}"


def verify_schedule_exists(schedule_id: int):
    log("VERIFY_SCHEDULE", schedule_id)

    res = (
        supabase
        .table("live_class_schedule")
        .select("id, buket_image_description")
        .eq("id", schedule_id)
        .limit(1)
        .execute()
    )

    if not res.data:
        raise RuntimeError("Schedule ID not found")

    if res.data[0]["buket_image_description"] is None:
        raise RuntimeError("buket_image_description is NULL")

    log("SCHEDULE_VERIFIED", schedule_id)


def update_bucket_json(schedule_id: int, image_id: str, bunny_url: str):

    log("RPC_CALL_START", {
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

    log("RPC_RESPONSE", res.data)

# ---------------- ENDPOINT ----------------

@app.post("/upload-bucket-image-to-bunny")
async def upload_bucket_image_to_bunny(
    file: UploadFile = File(...),
    schedule_id: int = Form(...),
    topic_id: str = Form(...),
    image_id: str = Form(...)
):

    log("REQUEST_RECEIVED", {
        "schedule_id": schedule_id,
        "topic_id": topic_id,
        "image_id": image_id,
        "filename": file.filename
    })

    try:
        # ---------------- VALIDATION ----------------

        uuid.UUID(image_id)
        uuid.UUID(topic_id)

        # ---------------- VERIFY TABLE ROW ----------------

        verify_schedule_exists(schedule_id)

        # ---------------- READ FILE ----------------

        contents = await file.read()

        if not contents:
            raise RuntimeError("Empty file")

        ext = file.filename.split(".")[-1].lower()

        if ext not in ["jpg", "jpeg", "png", "webp"]:
            raise RuntimeError("Unsupported file type")

        # ---------------- UPLOAD TO BUNNY ----------------

        filename = f"{image_id}.{ext}"

        bunny_url = upload_to_bunny(contents, filename)

        log("BUNNY_UPLOAD_SUCCESS", bunny_url)

        # ---------------- UPDATE JSON ----------------

        update_bucket_json(schedule_id, image_id, bunny_url)

        log("SUCCESS_COMPLETE", {
            "image_id": image_id,
            "bunny_url": bunny_url
        })

        return {
            "status": "ok",
            "table": "public.live_class_schedule",
            "column": "buket_image_description",
            "schedule_id": schedule_id,
            "image_id": image_id,
            "url": bunny_url
        }

    except Exception as e:
        log("ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))

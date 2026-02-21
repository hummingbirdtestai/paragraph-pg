# ---------------- MOCKIMAGEBUNNY.PY ----------------

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

def log(tag: str, data=None):
    ts = datetime.utcnow().isoformat()
    if data is not None:
        print(f"[{ts}][MOCK_BUNNY_API][{tag}]", data, flush=True)
    else:
        print(f"[{ts}][MOCK_BUNNY_API][{tag}]", flush=True)

# ---------------- CONFIG ----------------

log("BOOT_START")

BUNNY_STORAGE_ZONE = os.getenv("BUNNY_STORAGE_ZONE")
BUNNY_API_KEY = os.getenv("BUNNY_STORAGE_API_KEY")
BUNNY_PULL_ZONE = os.getenv("BUNNY_PULL_ZONE")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

log("ENV_LOADED", {
    "BUNNY_STORAGE_ZONE": bool(BUNNY_STORAGE_ZONE),
    "BUNNY_API_KEY": bool(BUNNY_API_KEY),
    "BUNNY_PULL_ZONE": bool(BUNNY_PULL_ZONE),
    "SUPABASE_URL": bool(SUPABASE_URL),
    "SUPABASE_SERVICE_KEY": bool(SUPABASE_SERVICE_KEY),
})

if not all([
    BUNNY_STORAGE_ZONE,
    BUNNY_API_KEY,
    BUNNY_PULL_ZONE,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY
]):
    log("ENV_MISSING_FATAL")
    raise RuntimeError("Missing required environment variables")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

BUNNY_STORAGE_BASE = f"https://sg.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE}"

log("BOOT_COMPLETE", {
    "BUNNY_STORAGE_BASE": BUNNY_STORAGE_BASE,
    "BUNNY_PULL_ZONE": BUNNY_PULL_ZONE,
})

# ---------------- APP ----------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

log("FASTAPI_READY")

# ---------------- HELPERS ----------------

def upload_to_bunny(file_bytes: bytes, filename: str) -> str:
    upload_url = f"{BUNNY_STORAGE_BASE}/{filename}"

    log("BUNNY_UPLOAD_START", {
        "filename": filename,
        "size_bytes": len(file_bytes),
        "upload_url": upload_url,
    })

    r = requests.put(
        upload_url,
        headers={
            "AccessKey": BUNNY_API_KEY,
        },
        data=file_bytes,
        timeout=30,
    )

    log("BUNNY_UPLOAD_RESPONSE", {
        "status_code": r.status_code,
        "reason": r.reason,
    })

    if r.status_code not in (200, 201):
        log("BUNNY_UPLOAD_FAILED", r.text)
        raise RuntimeError(f"Bunny upload failed: {r.status_code}")

    bunny_url = f"{BUNNY_PULL_ZONE}/{filename}"

    log("BUNNY_UPLOAD_SUCCESS", bunny_url)

    return bunny_url


def update_supabase(row_id: str, bunny_url: str):
    log("SUPABASE_UPDATE_START", {
        "row_id": row_id,
        "bunny_url": bunny_url,
    })

    res = (
        supabase
        .table("mock_tests_phases")
        .update({"mcq_image": bunny_url})
        .eq("id", row_id)
        .execute()
    )

    log("SUPABASE_UPDATE_RESPONSE", {
        "data": res.data,
        "count": len(res.data) if res.data else 0,
    })

    if not res.data:
        log("SUPABASE_UPDATE_FAILED")
        raise RuntimeError("Supabase update failed")

    log("SUPABASE_UPDATE_SUCCESS", row_id)

# ---------------- ENDPOINT ----------------

@app.post("/upload-mockimage-to-bunny")
async def upload_mockimage_to_bunny(
    file: UploadFile = File(...),
    row_id: str = Form(...)
):
    """
    Receives:
    - image file
    - row_id (uuid from mock_tests_phases)

    Does:
    - uploads image to Bunny as <row_id>.<ext>
    - stores Bunny URL in mock_tests_phases.mcq_image
    """

    log("REQUEST_RECEIVED", {
        "row_id": row_id,
        "filename": file.filename,
        "content_type": file.content_type,
    })

    try:
        contents = await file.read()

        log("FILE_READ", {
            "bytes": len(contents),
        })

        ext = file.filename.split(".")[-1].lower()
        log("FILE_EXTENSION", ext)

        if ext not in ["jpg", "jpeg", "png", "webp"]:
            log("UNSUPPORTED_FILE_TYPE", ext)
            raise HTTPException(status_code=400, detail="Unsupported image type")

        filename = f"{row_id}.{ext}"
        log("FINAL_FILENAME", filename)

        bunny_url = upload_to_bunny(
            contents,
            filename,
        )

        update_supabase(row_id, bunny_url)

        log("REQUEST_SUCCESS", {
            "row_id": row_id,
            "bunny_url": bunny_url,
        })

        return {
            "status": "ok",
            "url": bunny_url
        }

    except HTTPException as e:
        log("HTTP_EXCEPTION", str(e.detail))
        raise

    except Exception as e:
        log("UNHANDLED_EXCEPTION", str(e))
        raise HTTPException(status_code=500, detail=str(e))

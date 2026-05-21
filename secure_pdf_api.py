from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

from supabase import create_client

from dotenv import load_dotenv

import os
import time
import hashlib
import base64
import requests

from urllib.parse import quote

# ---------------- ENV ----------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

BUNNY_PULL_ZONE = os.getenv("BUNNY_PULL_ZONE")
BUNNY_TOKEN_KEY = os.getenv("BUNNY_TOKEN_KEY")

if not all([
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_ANON_KEY,
    BUNNY_PULL_ZONE,
    BUNNY_TOKEN_KEY
]):
    raise RuntimeError("Missing env variables")

# ---------------- SUPABASE ----------------

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

# ---------------- APP ----------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROOT ----------------

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "secure-pdf-api"
    }

# ---------------- HELPERS ----------------

def verify_supabase_jwt(token: str):

    r = requests.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": SUPABASE_ANON_KEY,
        },
        timeout=10,
    )

    if r.status_code != 200:
        return None

    return r.json()


def generate_bunny_signed_url(
    storage_path: str,
    expires_in: int = 3600
):

    expires = int(time.time()) + expires_in

    # MUST begin with slash
    path = f"/{storage_path}"

    # EXACT Bunny hash format
    signature = hashlib.sha256(
        f"{BUNNY_TOKEN_KEY}{path}{expires}".encode("utf-8")
    ).digest()

    token = (
        base64.urlsafe_b64encode(signature)
        .decode("utf-8")
        .replace("\n", "")
        .replace("=", "")
    )

    signed_url = (
        f"{BUNNY_PULL_ZONE}{path}"
        f"?token={token}&expires={expires}"
    )

    return signed_url

# ---------------- ENDPOINT ----------------

@app.get("/books/{book_id}/access")
async def access_book(
    book_id: str,
    authorization: str = Header(None)
):

    try:

        # ---------------- AUTH ----------------

        if not authorization:
            raise HTTPException(
                status_code=401,
                detail="Missing authorization header"
            )

        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization format"
            )

        token = authorization.replace(
            "Bearer ",
            ""
        )

        # ---------------- VERIFY USER ----------------

        user = verify_supabase_jwt(token)

        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid token"
            )

        auth_user_id = user["id"]

        # ---------------- BOOK USER ----------------

        book_user_res = (
            supabase
            .table("bookusers")
            .select("*")
            .eq("auth_user_id", auth_user_id)
            .single()
            .execute()
        )

        if not book_user_res.data:
            raise HTTPException(
                status_code=403,
                detail="Book user not found"
            )

        book_user = book_user_res.data

        # ---------------- BOOK ----------------

        book_res = (
            supabase
            .table("books")
            .select("*")
            .eq("id", book_id)
            .single()
            .execute()
        )

        if not book_res.data:
            raise HTTPException(
                status_code=404,
                detail="Book not found"
            )

        book = book_res.data

        # ---------------- SUBSCRIPTION ----------------

        sub_res = (
            supabase
            .table("booksubscriptions")
            .select("*")
            .eq("user_id", book_user["id"])
            .eq("subject_name", book["subject"])
            .gt("active_until", time.strftime("%Y-%m-%dT%H:%M:%S"))
            .execute()
        )

        if not sub_res.data:
            raise HTTPException(
                status_code=403,
                detail="Subscription inactive"
            )

        # ---------------- SIGNED URL ----------------

        signed_url = generate_bunny_signed_url(
            book["storage_path"]
        )

        return {
            "status": "ok",
            "signed_url": signed_url,
            "expires_in": 3600
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

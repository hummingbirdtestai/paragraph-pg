import os
import requests
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

BUCKET = "medical-images"


def download_file(url: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.content


def upload_to_supabase(file_bytes: bytes, filename: str) -> str:
    path = f"feed_images/{filename}"
    res = supabase.storage.from_(BUCKET).upload(
        path,
        file_bytes,
        {"content-type": "application/octet-stream", "upsert": True}
    )

    if "error" in res:
        raise Exception(res["error"])

    public_url = supabase.storage.from_(BUCKET).get_public_url(path)
    return public_url["publicUrl"]


def process_all():
    print("\n🔍 Fetching rows where:")
    print("➡ image_url IS NOT NULL")
    print("➡ image_url_supabase IS NULL")

    rows = (
        supabase
        .table("feed_posts")
        .select("*")
        .not_("image_url", "is", None)      # → image_url IS NOT NULL
        .is_("image_url_supabase", None)    # → image_url_supabase IS NULL
        .execute()
    )

    if not rows.data:
        print("🎉 Nothing left to process!")
        return

    print(f"📌 Found {len(rows.data)} images to process")

    for row in rows.data:
        try:
            print(f"\n➡ Processing ID: {row['id']}")

            url = row["image_url"]

            # Skip invalid URL formats
            if not isinstance(url, str) or not url.startswith("http"):
                print(f"⛔ Skipping invalid URL: {url}")
                continue

            # Step 1: Download
            img_bytes = download_file(url)

            # Step 2: Save filename as ID
            filename = f"{row['id']}.jpg"

            # Step 3: Upload to Supabase
            public_url = upload_to_supabase(img_bytes, filename)

            # Step 4: Update DB
            supabase.table("feed_posts").update({
                "image_url_supabase": public_url
            }).eq("id", row["id"]).execute()

            print(f"✅ Uploaded → {public_url}")

        except requests.exceptions.HTTPError as e:
            if "403" in str(e):
                print(f"🚫 403 Forbidden — Skipping {url}")
                continue
            print(f"❌ HTTP error for {row['id']}: {e}")

        except Exception as e:
            print(f"❌ Error processing {row['id']}: {e}")


if __name__ == "__main__":
    process_all()

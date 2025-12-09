# supabase_client.py
from supabase import create_client
import os
from dotenv import load_dotenv
import requests
import json

# 🔹 Load environment variables
load_dotenv()

# 🔹 Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def call_rpc(function_name: str, params: dict = None):
    """
    Generic helper to call Supabase RPC and handle responses safely.
    """
    try:
        res = supabase.rpc(function_name, params or {}).execute()

        data = getattr(res, "data", None)

        if not data:
            print(f"⚠️ RPC {function_name} returned no data.")
            return None

        if isinstance(data, list):
            return data[0] if len(data) > 0 else None
        if isinstance(data, dict):
            return data

        print(f"⚠️ Unexpected RPC result type ({type(data)}) in {function_name}")
        return None

    except Exception as e:
        print(f"⚠️ RPC Exception in {function_name}: {e}")
        return None


def send_realtime_event(channel: str, payload: dict):
    """
    Sends a broadcast event to Supabase Realtime (v2) using REST API.
    """
    url = f"{SUPABASE_URL}/realtime/v1/broadcast"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apiKey": SUPABASE_KEY,
    }

    body = {
        "channel": channel,
        "type": "broadcast",
        "event": "new_notification",
        "payload": payload
    }

    try:
        resp = requests.post(url, headers=headers, data=json.dumps(body))
        print("Realtime broadcast response:", resp.status_code, resp.text)
        return resp.ok
    except Exception as e:
        print("Realtime broadcast failed:", e)
        return False

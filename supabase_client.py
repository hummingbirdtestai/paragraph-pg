# supabase_client.py
from supabase import create_client
import os
from dotenv import load_dotenv

# 🔹 Load environment variables
load_dotenv()

# 🔹 Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def call_rpc(function_name: str, params: dict = None):
    """
    Generic helper to call Supabase RPC and handle responses safely (for supabase-py v2+).
    Example: call_rpc("start_orchestra", {"p_student_id": "<uuid>"}).
    Returns: dict or None
    """
    try:
        res = supabase.rpc(function_name, params or {}).execute()

        # ✅ Extract data safely from SingleAPIResponse
        data = getattr(res, "data", None)

        # 🧩 Debug prints (optional, remove later)
        # print(f"🧩 RPC raw response for {function_name} →", res)
        # print(f"🧩 RPC data:", data)

        if not data:
            print(f"⚠️ RPC {function_name} returned no data.")
            return None

        # Supabase RPC may return list or dict depending on SQL RETURN TABLE
        if isinstance(data, list):
            if len(data) == 0:
                print(f"⚠️ RPC {function_name} returned empty list.")
                return None
            return data[0]  # Return first row
        elif isinstance(data, dict):
            return data
        else:
            print(f"⚠️ Unexpected RPC result type ({type(data)}) in {function_name}")
            return None

    except Exception as e:
        print(f"⚠️ RPC Exception in {function_name}: {e}")
        return None

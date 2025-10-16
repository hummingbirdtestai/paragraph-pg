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
    Generic helper to call Supabase RPC and handle errors cleanly.
    Example: call_rpc("start_orchestra", {"p_student_id": "<uuid>"})
    """
    try:
        response = supabase.rpc(function_name, params or {}).execute()
        if response.error:
            print(f"❌ RPC Error calling {function_name}:", response.error)
            return None
        return response.data
    except Exception as e:
        print(f"⚠️ RPC Exception in {function_name}:", e)
        return None

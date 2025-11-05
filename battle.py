from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import os, asyncio, time, requests

load_dotenv()
app = FastAPI(title="Battle API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or restrict to your frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# -----------------------------------------------------
# 🔹 SUPABASE REALTIME BROADCAST HELPER
# -----------------------------------------------------
def broadcast_event(battle_id: str, event: str, payload: dict):
    """Send broadcast event to Supabase Realtime channel."""
    try:
        res = requests.post(
            f"{SUPABASE_URL}/realtime/v1/api/broadcast",
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "channel": f"battle_{battle_id}",
                "event": event,
                "payload": payload,
            },
        )
        print(f"📡 Broadcast → {event}: {res.status_code}")
        return res.ok
    except Exception as e:
        print(f"❌ Broadcast failed: {e}")
        return False


# -----------------------------------------------------
# 🔹 REST ENDPOINTS
# -----------------------------------------------------
@app.get("/")
async def root():
    return {"status": "Battle API running ✅"}


@app.post("/battle/get_stats")
async def get_battle_stats(mcq_id: str):
    try:
        response = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="No stats found")
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/battle/leaderboard")
async def get_leaderboard(battle_id: str):
    try:
        response = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="No leaderboard found")
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------
# 🔹 BATTLE ORCHESTRATION (AUTO SEQUENCE)
# -----------------------------------------------------
active_battles = set()

@app.post("/battle/start/{battle_id}")
async def start_battle(battle_id: str, background_tasks: BackgroundTasks):
    """Starts orchestrator if players exist; else waits 30 min grace."""
    try:
        participants = supabase.table("battle_participants")\
            .select("*").eq("battle_id", battle_id).eq("status", "joined").execute().data

        if not participants:
            # No players joined yet → start grace timer
            supabase.table("battle_schedule").update({"status": "Active"}).eq("battle_id", battle_id).execute()
            background_tasks.add_task(expire_battle_if_empty, battle_id)
            print(f"⏳ Grace window started for battle {battle_id}")
            return {"success": False, "message": "Waiting for players (30-min grace window)"}

        if battle_id in active_battles:
            return {"success": False, "message": "Battle already running."}

        active_battles.add(battle_id)
        print(f"🚀 Starting orchestrator for {battle_id}")
        background_tasks.add_task(run_battle_sequence, battle_id)
        return {"success": True, "message": f"Battle {battle_id} started."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def expire_battle_if_empty(battle_id: str):
    """Marks battle as completed after 30-min grace if no players joined."""
    time.sleep(30 * 60)
    participants = supabase.table("battle_participants")\
        .select("id").eq("battle_id", battle_id).eq("status", "joined").execute().data
    if not participants:
        supabase.table("battle_schedule").update({"status": "Completed"}).eq("battle_id", battle_id).execute()
        broadcast_event(battle_id, "battle_end", {"message": "No players joined. Battle expired."})
        print(f"🕒 Battle {battle_id} expired due to inactivity.")


# -----------------------------------------------------
# 🔹 ORCHESTRATOR LOOP (uses Supabase Realtime broadcast)
# -----------------------------------------------------
async def run_battle_sequence(battle_id: str):
    """MCQ → Stats → Leaderboard loop."""
    try:
        print(f"🏁 Running orchestrator for {battle_id}")
        current = supabase.rpc("get_first_mcq", {"battle_id_input": battle_id}).execute()
        if not current.data:
            print("⚠️ No questions found for this battle.")
            broadcast_event(battle_id, "battle_end", {"message": "No MCQs found."})
            return

        while current.data:
            mcq = current.data[0]
            react_order = mcq.get("react_order", 0)

            # 🟢 Question phase
            broadcast_event(battle_id, "new_question", mcq)
            print(f"🧩 Q{react_order} started.")
            for remaining in range(20, 0, -1):
                broadcast_event(battle_id, "timer_sync", {"seconds_left": remaining})
                await asyncio.sleep(1)

            # 📊 Stats phase
            stats = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq["mcq_id"]}).execute().data or []
            broadcast_event(battle_id, "show_stats", stats)
            print(f"📈 Stats broadcast for Q{react_order}")
            await asyncio.sleep(10)

            # 🏆 Leaderboard phase
            leaderboard = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute().data or []
            broadcast_event(battle_id, "update_leaderboard", leaderboard)
            print(f"🏅 Leaderboard broadcasted.")
            await asyncio.sleep(10)

            # ➡️ Next question
            current = supabase.rpc("get_next_mcq", {
                "battle_id_input": battle_id,
                "react_order_input": react_order
            }).execute()

        # ✅ End of battle
        broadcast_event(battle_id, "battle_end", {"message": "Battle completed 🏁"})
        print(f"✅ Battle {battle_id} completed.")

    except Exception as e:
        print(f"💥 Orchestrator error for {battle_id}: {e}")
    finally:
        active_battles.discard(battle_id)

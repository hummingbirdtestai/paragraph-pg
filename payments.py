from fastapi import APIRouter, Request, HTTPException
from uuid import uuid4
from datetime import datetime, timedelta
import os
import requests
import hmac
import hashlib

from supabase_client import supabase

router = APIRouter(prefix="/api/payments", tags=["payments"])

# ───────────────────────────────────────────────
# CASHFREE CONFIG
# ───────────────────────────────────────────────

CASHFREE_BASE_URL = "https://api.cashfree.com/pg"
CASHFREE_APP_ID = os.getenv("CASHFREE_APP_ID")
CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY")

def cashfree_headers():
    return {
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "Content-Type": "application/json",
        "x-api-version": "2023-08-01"
    }

def ensure_cashfree_config():
    if not CASHFREE_APP_ID or not CASHFREE_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payments temporarily unavailable"
        )
# ───────────────────────────────────────────────
# PRICING
# ───────────────────────────────────────────────

PRICING_MAP = {
    "3": 12000,
    "6": 20000,
    "12": 36000,
}

PLAN_MONTHS = {
    "3": 3,
    "6": 6,
    "12": 12,
}

# ───────────────────────────────────────────────
# UTILS
# ───────────────────────────────────────────────
def apply_coupon(amount: int, coupon_code: str | None):
    if not coupon_code:
        return amount, None

    res = (
        supabase.table("coupons")
        .select("*")
        .eq("code", coupon_code)
        .eq("is_active", True)
        .eq("is_redeemed", False)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=400, detail="Invalid or expired coupon")

    coupon = res.data[0]

    discount_percent = coupon["discount_percent"]
    discount = int(amount * discount_percent / 100)
    final_amount = max(amount - discount, 0)

    return final_amount, coupon


def create_cashfree_order(order_id: str, amount: int):
    payload = {
        "order_id": order_id,
        "order_amount": amount,
        "order_currency": "INR",
        "customer_details": {
            "customer_id": order_id,
            "customer_phone": "9999999999"
        }
    }

    res = requests.post(
        f"{CASHFREE_BASE_URL}/orders",
        json=payload,
        headers=cashfree_headers(),
        timeout=15
    )

    if res.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=res.text)

    return res.json()


def verify_webhook_signature(raw_body: bytes, signature: str):
    computed = hmac.new(
        CASHFREE_SECRET_KEY.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, signature)

# ───────────────────────────────────────────────
# INITIATE PAYMENT
# ───────────────────────────────────────────────

@router.options("/initiate")
async def initiate_options():
    return {}

@router.post("/initiate")
async def initiate_payment(request: Request):
    ensure_cashfree_config()
    # 1️⃣ Safe JSON parse
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    plan = body.get("plan")
    coupon_code = body.get("coupon_code")
    student_id = body.get("student_id")

    # 2️⃣ Validation
    if plan not in PRICING_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan")

    if not student_id:
        raise HTTPException(status_code=400, detail="student_id required")

    # 3️⃣ Pricing (backend is source of truth)
    base_amount = PRICING_MAP[plan]
    final_amount, coupon = apply_coupon(base_amount, coupon_code)

    # 4️⃣ Generate order id
    order_id = f"order_{uuid4().hex[:14]}"

    # 5️⃣ Create Cashfree order
    try:
        cf_order = create_cashfree_order(order_id, final_amount)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway unavailable"
        )

    payment_session_id = cf_order.get("payment_session_id")

    if not payment_session_id:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate payment session"
        )

    # 6️⃣ Persist order (idempotent safe)
    supabase.table("payment_orders").insert({
        "order_id": order_id,
        "student_id": student_id,
        "plan": plan,
        "amount": final_amount,
        "coupon_code": coupon_code,
        "status": "initiated",
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    # 7️⃣ Response (frontend redirect)
    return {
        "order_id": order_id,
        "amount": final_amount,
        "payment_session_id": payment_session_id,
        "currency": "INR",
        "status": "initiated"
    }

# ───────────────────────────────────────────────
# CASHFREE WEBHOOK
# ───────────────────────────────────────────────

@router.options("/webhook")
async def webhook_options():
    return {}

@router.post("/webhook")
async def cashfree_webhook(request: Request):
    ensure_cashfree_config()
    raw_body = await request.body()
    payload = await request.json()

    signature = request.headers.get("x-webhook-signature")
    if not signature or not verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = payload.get("type")
    data = payload.get("data", {})
    order = data.get("order", {})

    order_id = order.get("order_id")
    amount = order.get("order_amount")

    # Fetch order
    order_row = (
        supabase.table("payment_orders")
        .select("*")
        .eq("order_id", order_id)
        .single()
        .execute()
        .data
    )

    if not order_row:
        return {"status": "order_not_found"}

    # Idempotency
    if order_row["status"] == "paid":
        return {"status": "already_processed"}

    if event == "PAYMENT_SUCCESS":
        plan = order_row["plan"]
        student_id = order_row["student_id"]

        # 1️⃣ Mark order paid
        supabase.table("payment_orders").update({
            "status": "paid",
            "paid_at": datetime.utcnow().isoformat()
        }).eq("order_id", order_id).execute()

        # 2️⃣ Activate subscription
        starts_at = datetime.utcnow()
        ends_at = starts_at + timedelta(days=30 * PLAN_MONTHS[plan])

        supabase.table("student_subscriptions").upsert({
            "student_id": student_id,
            "plan": plan,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "is_active": True
        }, on_conflict=["student_id"]).execute()

        # 3️⃣ Consume coupon
        if order_row["coupon_code"]:
            supabase.table("coupons").update({
                "is_redeemed": True,
                "redeemed_at": datetime.utcnow().isoformat(),
                "redeemed_by_user_id": student_id
            }).eq("code", order_row["coupon_code"]).execute()

        return {"status": "subscription_activated"}

    if event == "PAYMENT_FAILED":
        supabase.table("payment_orders").update({
            "status": "failed"
        }).eq("order_id", order_id).execute()

        return {"status": "payment_failed"}

    return {"status": "ignored"}

from fastapi import APIRouter, Request, HTTPException
from uuid import uuid4
from datetime import datetime, timedelta
import os
import requests
import hmac
import hashlib
import logging

from supabase_client import supabase

# ───────────────────────────────────────────────
# ROUTER + LOGGER
# ───────────────────────────────────────────────

router = APIRouter(prefix="/api/payments", tags=["payments"])

logger = logging.getLogger("payments")
logger.setLevel(logging.INFO)

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
        logger.error("[CONFIG] Cashfree credentials missing")
        raise HTTPException(status_code=503, detail="Payments temporarily unavailable")

# ───────────────────────────────────────────────
# PRICING
# ───────────────────────────────────────────────

PRICING_MAP = {
    "1": 2500,      # 👈 NEW (1 month plan)
    "3": 12000,
    "6": 20000,
    "12": 36000,
}

PLAN_MONTHS = {
    "1": 1,         # 👈 NEW
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
        logger.warning(f"[COUPON] Invalid coupon: {coupon_code}")
        raise HTTPException(status_code=400, detail="Invalid or expired coupon")

    coupon = res.data[0]
    
    if coupon.get("is_redeemed"):
        raise HTTPException(status_code=400, detail="Coupon already used")

    # 🔐 Optional but STRONGLY recommended
    if coupon.get("package_price") and coupon["package_price"] != amount:
        raise HTTPException(
            status_code=400,
            detail="Coupon not valid for selected plan"
        )

    # ✅ FIXED LOGIC
    if coupon.get("discount_amount") is not None:
        discount = int(coupon["discount_amount"])
    else:
        discount_percent = coupon["discount_percent"] or 0
        discount = int(amount * discount_percent / 100)

    final_amount = max(amount - discount, 0)

    return final_amount, coupon
    

def create_cashfree_order(order_id: str, amount: int, user: dict):
    payload = {
        "order_id": order_id,
        "order_amount": amount,
        "order_currency": "INR",
        "customer_details": {
            "customer_id": user["phone"] or order_id,
            "customer_phone": user["phone"],
            "customer_name": user["name"],
            "customer_email": user["email"],
        },
        "order_meta": {
            "return_url": f"https://www.neetpg.app/payment-success?order_id={order_id}"
        }
    }

    logger.info(f"[CASHFREE] Creating order {order_id} for ₹{amount}")

    res = requests.post(
        f"{CASHFREE_BASE_URL}/orders",
        json=payload,
        headers=cashfree_headers(),
        timeout=15
    )

    logger.info(f"[CASHFREE] Status={res.status_code} Body={res.text}")

    if res.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail="Cashfree order creation failed")

    return res.json()


import hmac
import hashlib
import base64

def verify_webhook_signature(raw_body: bytes, timestamp: str, signature: str):
    message = timestamp.encode() + raw_body   # ❗ NO DOT

    digest = hmac.new(
        CASHFREE_SECRET_KEY.encode(),
        message,
        hashlib.sha256
    ).digest()

    computed_signature = base64.b64encode(digest).decode()

    return hmac.compare_digest(computed_signature, signature)


# ───────────────────────────────────────────────
# INITIATE PAYMENT
# ───────────────────────────────────────────────

@router.options("/initiate")
async def initiate_options():
    return {}

@router.post("/initiate")
async def initiate_payment(request: Request):
    ensure_cashfree_config()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    plan = body.get("plan")
    coupon_code = body.get("coupon_code")
    student_id = body.get("student_id")

    logger.info(f"[INITIATE] student_id={student_id} plan={plan}")

    if plan not in PRICING_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan")

    if not student_id:
        raise HTTPException(status_code=400, detail="student_id required")

    user = (
        supabase.table("users")
        .select("name, phone, email")
        .eq("id", student_id)
        .single()
        .execute()
        .data
    )

    if not user:
        logger.error(f"[INITIATE] User not found: {student_id}")
        raise HTTPException(status_code=404, detail="User not found")

    base_amount = PRICING_MAP[plan]
    final_amount, _ = apply_coupon(base_amount, coupon_code)

    order_id = f"order_{uuid4().hex[:14]}"

    try:
        cf_order = create_cashfree_order(order_id, final_amount, user)
    except Exception as e:
        logger.error(f"[CASHFREE] Order failed: {str(e)}")
        raise HTTPException(status_code=502, detail="Payment gateway unavailable")

    payment_session_id = cf_order.get("payment_session_id")

    if not payment_session_id:
        logger.error("[INITIATE] Missing payment_session_id")
        raise HTTPException(status_code=500, detail="Failed to generate payment session")

    supabase.table("payment_orders").insert({
        "order_id": order_id,
        "student_id": student_id,
        "student_name": user["name"],
        "student_phone": user["phone"],
        "student_email": user["email"],
        "plan": plan,
        "amount": final_amount,
        "coupon_code": coupon_code,
        "status": "initiated",
    }).execute()

    logger.info(f"[INITIATE] Order persisted {order_id}")

    return {
        "order_id": order_id,
        "amount": final_amount,
        "payment_session_id": payment_session_id,
        "currency": "INR",
        "status": "initiated"
    }

# ───────────────────────────────────────────────
# STATUS PAYMENT
# ───────────────────────────────────────────────

@router.get("/status")
async def get_payment_status(order_id: str):
    ensure_cashfree_config()

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id required")

    res = requests.get(
        f"{CASHFREE_BASE_URL}/orders/{order_id}",
        headers=cashfree_headers(),
        timeout=10
    )

    if res.status_code != 200:
        logger.error(f"[STATUS] Cashfree error {res.text}")
        raise HTTPException(status_code=502, detail="Unable to verify payment")

    data = res.json()

    return {
        "order_id": order_id,
        "order_status": data.get("order_status")  # SUCCESS | FAILED | CANCELLED | PENDING
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

    logger.info("🔥 CASHFREE WEBHOOK HIT")
    logger.info(f"Headers: {dict(request.headers)}")

    raw_body = await request.body()
    logger.info(f"Raw body: {raw_body.decode(errors='ignore')}")

    import json
    payload = json.loads(raw_body)

    signature = request.headers.get("x-webhook-signature")
    timestamp = request.headers.get("x-webhook-timestamp")

    if not signature:
        logger.error("❌ Missing x-webhook-signature")
        return {"status": "missing_signature"}

    if not timestamp:
        logger.error("❌ Missing x-webhook-timestamp")
        return {"status": "missing_timestamp"}

    if not verify_webhook_signature(raw_body, timestamp, signature):
        logger.error("❌ Signature mismatch")
        return {"status": "signature_mismatch"}


    event = payload.get("type")
    order = payload.get("data", {}).get("order", {})

    order_id = order.get("order_id")
    amount = order.get("order_amount")

    logger.info(f"[WEBHOOK] Event={event} Order={order_id}")

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

    if order_row["status"] == "paid":
        return {"status": "already_processed"}

    if event in ("PAYMENT_SUCCESS", "PAYMENT_SUCCESS_WEBHOOK"):
        student_id = order_row["student_id"]
        plan = order_row["plan"]

        supabase.table("payment_orders").update({
            "status": "paid",
            "paid_at": datetime.utcnow().isoformat()
        }).eq("order_id", order_id).execute()

        starts_at = datetime.utcnow()
        ends_at = starts_at + timedelta(days=30 * PLAN_MONTHS[plan])

        supabase.table("users").update({
            "is_paid": True,
            "paid_activated_at": starts_at.isoformat(),
            "subscribed_at": starts_at.isoformat(),
            "purchased_package": plan,
            "package_price": PRICING_MAP[plan],
            "amount_paid": order_row["amount"],
            "subscription_start_at": starts_at.isoformat(),
            "subscription_end_at": ends_at.isoformat(),
            "subscribed_coupon_code": order_row["coupon_code"],
        }).eq("id", student_id).execute()

        # ✅ MARK COUPON AS REDEEMED
        if order_row.get("coupon_code"):
            supabase.table("coupons").update({
                "is_redeemed": True,
                "redeemed_at": datetime.utcnow().isoformat(),
                "redeemed_by_user_id": student_id,
                "subscription_start_at": starts_at.isoformat(),
                "subscription_end_at": ends_at.isoformat(),
                "purchased_package": plan,
                "package_price": PRICING_MAP[plan],
                "amount_paid": order_row["amount"],
            }).eq("code", order_row["coupon_code"]).execute()

        return {"status": "subscription_activated"}

    if event == "PAYMENT_FAILED":
        supabase.table("payment_orders").update({
            "status": "failed"
        }).eq("order_id", order_id).execute()

        return {"status": "payment_failed"}

    return {"status": "ignored"}

@router.post("/preview")
async def preview_payment(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    plan = body.get("plan")
    coupon_code = body.get("coupon_code")

    if plan not in PRICING_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan")

    base_amount = PRICING_MAP[plan]

    try:
        final_amount, coupon = apply_coupon(base_amount, coupon_code)
    except HTTPException as e:
        # Invalid coupon
        raise e

    discount_percent = coupon["discount_percent"] if coupon and coupon.get("discount_percent") else None
    discount_amount = coupon["discount_amount"] if coupon and coupon.get("discount_amount") else (base_amount - final_amount)

    return {
        "base_amount": base_amount,
        "final_amount": final_amount,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "coupon_code": coupon_code,
        "valid": True,
    }

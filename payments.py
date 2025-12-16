from fastapi import APIRouter, Request, HTTPException
from uuid import uuid4
from datetime import datetime
import os
import requests

router = APIRouter(prefix="/api/payments", tags=["payments"])

# ───────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────

CASHFREE_BASE_URL = "https://sandbox.cashfree.com/pg"  # change to prod later
CASHFREE_APP_ID = os.getenv("CASHFREE_APP_ID")
CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY")

# Pricing (single source of truth)
PRICING_MAP = {
    "3": 12000,
    "6": 20000,
    "12": 36000,
}

# Coupon definitions
COUPONS = {
    "NEET25": {"type": "percent", "value": 25},
    "FIRST50": {"type": "percent", "value": 50},
    "SAVE500": {"type": "flat", "value": 500},
    "STUDENT20": {"type": "percent", "value": 20},
}

# ───────────────────────────────────────────────
# UTILS
# ───────────────────────────────────────────────

def apply_coupon(amount: int, coupon_code: str | None) -> int:
    if not coupon_code:
        return amount

    coupon = COUPONS.get(coupon_code)
    if not coupon:
        raise HTTPException(status_code=400, detail="Invalid coupon")

    if coupon["type"] == "percent":
        discount = int(amount * coupon["value"] / 100)
        return max(amount - discount, 0)

    if coupon["type"] == "flat":
        return max(amount - coupon["value"], 0)

    return amount


def create_cashfree_order(order_id: str, amount: int):
    payload = {
        "order_id": order_id,
        "order_amount": amount,
        "order_currency": "INR",
        "customer_details": {
            "customer_id": "guest_user",
            "customer_phone": "9999999999"
        }
    }

    headers = {
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "Content-Type": "application/json"
    }

    res = requests.post(
        f"{CASHFREE_BASE_URL}/orders",
        json=payload,
        headers=headers,
        timeout=10
    )

    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="Cashfree order creation failed")

    return res.json()

# ───────────────────────────────────────────────
# INITIATE PAYMENT
# ───────────────────────────────────────────────

@router.post("/initiate")
async def initiate_payment(request: Request):
    payload = await request.json()

    plan = payload.get("plan")
    coupon_code = payload.get("coupon_code")

    if plan not in PRICING_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan")

    base_amount = PRICING_MAP[plan]
    final_amount = apply_coupon(base_amount, coupon_code)

    order_id = f"order_{uuid4().hex[:12]}"

    cashfree_order = create_cashfree_order(order_id, final_amount)

    return {
        "order_id": order_id,
        "amount": final_amount,
        "checkout_url": cashfree_order["payment_link"],
        "status": "initiated"
    }

# ───────────────────────────────────────────────
# CASHFREE WEBHOOK
# ───────────────────────────────────────────────

@router.post("/webhook")
async def cashfree_webhook(request: Request):
    payload = await request.json()

    event = payload.get("type")
    data = payload.get("data", {})

    if event != "PAYMENT_SUCCESS":
        return {"status": "ignored"}

    order = data.get("order", {})
    payment = data.get("payment", {})

    order_id = order.get("order_id")
    amount = order.get("order_amount")
    payment_id = payment.get("cf_payment_id")

    # TODO (PROD):
    # 1. Verify signature
    # 2. Mark order paid in DB
    # 3. Activate subscription
    # 4. Consume coupon
    # 5. Prevent replay (idempotency)

    return {
        "status": "payment_success_processed",
        "order_id": order_id,
        "payment_id": payment_id,
        "amount": amount
    }

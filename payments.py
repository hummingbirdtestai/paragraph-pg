from fastapi import APIRouter, Request
from datetime import datetime, timedelta
from uuid import uuid4

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.post("/initiate")
async def initiate_payment(request: Request):
    payload = await request.json()

    plan = payload.get("plan")
    coupon_code = payload.get("coupon_code")

    if plan not in ["3", "6", "12"]:
        return {"error": "Invalid plan"}

    # 🔒 TEMP MOCK (replace with real logic later)
    pricing_map = {
        "3": 12000,
        "6": 20000,
        "12": 36000,
    }

    amount = pricing_map[plan]

    # TODO later:
    # - validate coupon
    # - calculate discount
    # - create Cashfree order
    # - create payment session

    fake_order_id = f"order_{uuid4().hex[:10]}"
    fake_checkout_url = f"https://sandbox.cashfree.com/pay/{fake_order_id}"

    return {
        "order_id": fake_order_id,
        "amount": amount,
        "checkout_url": fake_checkout_url,
        "status": "initiated"
    }

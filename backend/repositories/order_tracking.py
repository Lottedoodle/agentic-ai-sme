from __future__ import annotations

import json
import re
from typing import Any

# Mock customer orders for shipping-status demos (Kerry Express).
_MOCK_ORDERS: dict[str, dict[str, Any]] = {
    "GB-1001": {
        "order_id": "GB-1001",
        "customer_name": "คุณเอ",
        "status": "กำลังจัดส่ง",
        "status_detail": "พัสดุอยู่ระหว่างการขนส่งโดย Kerry Express",
        "carrier": "Kerry Express",
        "tracking_number": "KER123456789TH",
        "tracking_url": "https://th.kerryexpress.com/th/track/?track=KER123456789TH",
        "items": ["Vitamin C Serum 30ml x1", "Hyaluronic Serum 30ml x1"],
        "estimated_delivery": "1-2 วันทำการ",
    },
    "GB-1002": {
        "order_id": "GB-1002",
        "customer_name": "คุณบี",
        "status": "เตรียมจัดส่ง",
        "status_detail": "ร้านกำลังแพ็คสินค้า รอส่งมอบขนส่ง",
        "carrier": "Kerry Express",
        "tracking_number": "KER987654321TH",
        "tracking_url": "https://th.kerryexpress.com/th/track/?track=KER987654321TH",
        "items": ["ลิปแมตต์ เบอร์ 01 x1"],
        "estimated_delivery": "2-4 วันทำการ",
    },
    "GB-1003": {
        "order_id": "GB-1003",
        "customer_name": "คุณซี",
        "status": "จัดส่งสำเร็จ",
        "status_detail": "พัสดุถูกจัดส่งเรียบร้อยแล้ว",
        "carrier": "Kerry Express",
        "tracking_number": "KER555666777TH",
        "tracking_url": "https://th.kerryexpress.com/th/track/?track=KER555666777TH",
        "items": ["คุชชั่น 21 Light x1"],
        "estimated_delivery": "ส่งถึงแล้ว",
    },
}

# Default mock order when the customer asks about "my order" without an id.
_DEFAULT_CUSTOMER_ORDER_ID = "GB-1001"

_ORDER_ID_RE = re.compile(
    r"\b(GB[- ]?\d{3,6}|KER\d{6,}TH)\b",
    re.IGNORECASE,
)


def extract_order_id(text: str) -> str | None:
    match = _ORDER_ID_RE.search(text or "")
    if not match:
        return None
    raw = match.group(1).upper().replace(" ", "")
    if raw.startswith("GB") and "-" not in raw and len(raw) > 2:
        return f"GB-{raw[2:]}"
    return raw


def lookup_order(order_id: str | None = None, *, query: str = "") -> str:
    """Return mock order status + Kerry tracking URL for the agent tool."""
    resolved = (order_id or "").strip().upper().replace(" ", "")
    if resolved.startswith("GB") and "-" not in resolved and len(resolved) > 2:
        resolved = f"GB-{resolved[2:]}"
    if not resolved:
        resolved = extract_order_id(query) or _DEFAULT_CUSTOMER_ORDER_ID

    order = _MOCK_ORDERS.get(resolved)
    if not order:
        # Allow lookup by Kerry tracking number as well.
        for candidate in _MOCK_ORDERS.values():
            if str(candidate.get("tracking_number", "")).upper() == resolved:
                order = candidate
                break

    if not order:
        return json.dumps(
            {
                "source": "order_tracking_mock",
                "status": "not_found",
                "order_id": resolved,
                "query": query,
                "message": f"ไม่พบออเดอร์ {resolved} ในระบบ (mock)",
                "order": None,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "source": "order_tracking_mock",
            "status": "ok",
            "order_id": order["order_id"],
            "query": query,
            "message": f"พบสถานะออเดอร์ {order['order_id']}",
            "order": order,
        },
        ensure_ascii=False,
    )

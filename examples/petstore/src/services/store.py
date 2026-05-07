# Scaffolded by pyoas — safe to edit; won't be overwritten unless overwrite: true.
from __future__ import annotations

from fastapi import HTTPException
from generated.models.store import CreateOrderRequest, Order

# In-memory store — replace with a real database session in production.
_orders: dict[int, Order] = {}
_next_id = 1


class StoreService:
    async def get_inventory(
        self,
    ) -> dict[str, int]:
        """Get store inventory"""
        counts: dict[str, int] = {"available": 0, "pending": 0, "sold": 0}
        for order in _orders.values():
            status = order.status
            counts[status] = counts.get(status, 0) + 1
        return counts

    async def create_order(
        self,
        *,
        body: CreateOrderRequest,
    ) -> Order:
        """Place an order for a pet"""
        global _next_id
        order = Order(
            id=_next_id,
            pet_id=body.pet_id,
            quantity=body.quantity,
            status="placed",
        )
        _orders[_next_id] = order
        _next_id += 1
        return order

    async def get_order(
        self,
        *,
        order_id: int,
    ) -> Order:
        """Get order by ID"""
        order = _orders.get(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        return order


async def get_store_service() -> StoreService:
    return StoreService()

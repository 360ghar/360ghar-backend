"""Tests for payment endpoints (Razorpay + saved payment methods)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.payments import PaymentMethod


def _mock_method(method_id: int = 1, user_id: int = 1) -> PaymentMethod:
    m = PaymentMethod(
        id=method_id,
        user_id=user_id,
        method_type="card",
        brand="Visa",
        last4="4242",
        razorpay_token="tok_abc",
        razorpay_payment_id="pay_abc",
        nickname="Work card",
        is_default=1,
        created_at=datetime.now(timezone.utc),
    )
    return m


class TestRazorpayOrderEndpoint:
    """Tests for POST /api/v1/payments/razorpay/order/"""

    @pytest.mark.asyncio
    async def test_create_order_success(self, authenticated_client: AsyncClient):
        from app.schemas.payment import RazorpayOrderResponse

        with patch(
            "app.api.api_v1.endpoints.payments.create_razorpay_order",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = RazorpayOrderResponse(
                order_id="order_abc",
                amount=7380.0,
                currency="INR",
                key_id="rzp_test_xxx",
                booking_id=1,
                notes={"booking_id": "1"},
            )
            response = await authenticated_client.post(
                "/api/v1/payments/razorpay/order",
                json={"booking_id": 1},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["order_id"] == "order_abc"
            assert data["amount"] == 7380.0
            assert data["currency"] == "INR"
            mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_order_unauthorized(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/payments/razorpay/order",
            json={"booking_id": 1},
        )
        assert response.status_code == 401


class TestRazorpayVerifyEndpoint:
    """Tests for POST /api/v1/payments/razorpay/verify/"""

    @pytest.mark.asyncio
    async def test_verify_success(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.verify_razorpay_payment",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = True
            response = await authenticated_client.post(
                "/api/v1/payments/razorpay/verify",
                json={
                    "booking_id": 1,
                    "razorpay_order_id": "order_abc",
                    "razorpay_payment_id": "pay_abc",
                    "razorpay_signature": "sig_abc",
                },
            )
            assert response.status_code == 200
            assert response.json()["message"] == "Payment verified successfully"

    @pytest.mark.asyncio
    async def test_verify_failure(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.verify_razorpay_payment",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = False
            response = await authenticated_client.post(
                "/api/v1/payments/razorpay/verify",
                json={
                    "booking_id": 1,
                    "razorpay_order_id": "order_abc",
                    "razorpay_payment_id": "pay_abc",
                    "razorpay_signature": "sig_abc",
                },
            )
            assert response.status_code == 400


class TestPaymentMethodEndpoints:
    """Tests for /api/v1/payments/methods/"""

    @pytest.mark.asyncio
    async def test_list_methods(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.list_payment_methods",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = [_mock_method(1), _mock_method(2)]
            response = await authenticated_client.get("/api/v1/payments/methods")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["brand"] == "Visa"

    @pytest.mark.asyncio
    async def test_add_method(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.add_payment_method",
            new_callable=AsyncMock,
        ) as mock_add:
            mock_add.return_value = _mock_method()
            response = await authenticated_client.post(
                "/api/v1/payments/methods",
                json={
                    "method_type": "card",
                    "brand": "Visa",
                    "last4": "4242",
                    "is_default": True,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["last4"] == "4242"
            assert data["is_default"] is True

    @pytest.mark.asyncio
    async def test_update_method(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.update_payment_method",
            new_callable=AsyncMock,
        ) as mock_update:
            updated = _mock_method()
            updated.nickname = "Personal"
            mock_update.return_value = updated
            response = await authenticated_client.put(
                "/api/v1/payments/methods/1",
                json={"nickname": "Personal", "is_default": True},
            )
            assert response.status_code == 200
            assert response.json()["nickname"] == "Personal"

    @pytest.mark.asyncio
    async def test_update_method_not_found(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.update_payment_method",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = None
            response = await authenticated_client.put(
                "/api/v1/payments/methods/999",
                json={"nickname": "Personal"},
            )
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_method(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.delete_payment_method",
            new_callable=AsyncMock,
        ) as mock_delete:
            mock_delete.return_value = True
            response = await authenticated_client.delete(
                "/api/v1/payments/methods/1"
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_method_not_found(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.payments.delete_payment_method",
            new_callable=AsyncMock,
        ) as mock_delete:
            mock_delete.return_value = False
            response = await authenticated_client.delete(
                "/api/v1/payments/methods/999"
            )
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_methods_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/v1/payments/methods")
        assert response.status_code == 401

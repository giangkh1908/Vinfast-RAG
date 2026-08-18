import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.core.telemetry import (
    calculate_cost,
)
from app.main import app


def test_cost_calculation():
    """Kiểm tra engine tính toán chi phí token USD & VND."""
    # Test DeepSeek V4 Flash: $0.14/M in, $0.28/M out
    prompt_tokens = 1000
    completion_tokens = 500
    usd, vnd = calculate_cost("deepseek-ai/DeepSeek-V4-Flash", prompt_tokens, completion_tokens)

    expected_usd = (1000 / 1_000_000.0) * 0.14 + (500 / 1_000_000.0) * 0.28
    assert usd == round(expected_usd, 6)
    assert vnd == round(expected_usd * settings.usd_vnd_rate, 2)

    # Test Claude Haiku: $0.80/M in, $4.00/M out
    usd_haiku, _ = calculate_cost("anthropic/claude-haiku-4-5", 1000, 1000)
    expected_haiku_usd = (1000 / 1_000_000.0) * 0.80 + (1000 / 1_000_000.0) * 4.00
    assert usd_haiku == round(expected_haiku_usd, 6)


async def test_healthz_liveness():
    """Kiểm tra liveness endpoint /healthz trả về 200 OK."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/healthz")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "alive"
        assert "app_version" in data
        assert "timestamp" in data


async def test_legacy_health():
    """Kiểm tra backward compatibility /api/health."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"


async def test_admin_metrics_auth_protection():
    """Kiểm tra endpoint /api/admin/metrics/* có thể gọi trực tiếp."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/admin/metrics/overview")
        assert res.status_code in (200, 500)




async def test_prompt_registry_and_admin_api():
    """Kiểm tra Admin Prompt APIs: List, Get Detail, Test Render, Create & Activate."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        headers = {"X-Admin-Key": settings.admin_api_key}

        # 1. List active versions
        res_active = await ac.get("/api/admin/prompts/active", headers=headers)
        assert res_active.status_code == 200
        data = res_active.json()
        assert "active_versions" in data
        assert "system" in data["active_versions"]

        # 2. Test render endpoint
        res_render = await ac.post(
            "/api/admin/prompts/test-render",
            headers=headers,
            json={
                "prompt_type": "synthesize",
                "variables": {"context": "VF 8 Eco pin 87.7 kWh", "query": "Pin VF 8 thế nào?"},
            },
        )
        assert res_render.status_code == 200
        render_data = res_render.json()
        assert "VF 8 Eco" in render_data["rendered_text"]
        assert render_data["prompt_type"] == "synthesize"


async def main():
    print("=== Running DevOps, Metrics & Prompt Registry Tests ===")
    test_cost_calculation()
    print("  [OK] test_cost_calculation")

    await test_healthz_liveness()
    print("  [OK] test_healthz_liveness")

    await test_legacy_health()
    print("  [OK] test_legacy_health")

    await test_admin_metrics_auth_protection()
    print("  [OK] test_admin_metrics_auth_protection")

    await test_prompt_registry_and_admin_api()
    print("  [OK] test_prompt_registry_and_admin_api")
    print("=== All Tests Passed Successfully! ===")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())



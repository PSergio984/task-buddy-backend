import asyncio
import random

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_high_concurrency_mixed_operations(authenticated_async_client: AsyncClient):
    """
    Stress test with mixed concurrent operations:
    - Create tasks
    - Create tags
    - Attach tags
    - Update tasks
    - Delete some tasks
    """
    num_iterations = 20


    # Concurrent creation of tasks and tags
    async def create_initial():
        t_res = await asyncio.gather(*[
            authenticated_async_client.post("/api/v1/tasks/", json={"title": f"Initial Task {i}"})
            for i in range(10)
        ])
        tg_res = await asyncio.gather(*[
            authenticated_async_client.post("/api/v1/tasks/tags/", json={"name": f"Initial Tag {i}"})
            for i in range(5)
        ])
        return [r.json()["id"] for r in t_res if r.status_code == 201], \
               [r.json()["id"] for r in tg_res if r.status_code == 201]

    task_ids, tag_ids = await create_initial()

    async def random_op():
        op_type = random.choice(["create_task", "update_task", "attach_tag", "get_tasks"])

        if op_type == "create_task":
            resp = await authenticated_async_client.post(
                "/api/v1/tasks/",
                json={"title": f"Stress Task {random.randint(0, 1000)}"}
            )
            return resp.status_code

        elif op_type == "update_task" and task_ids:
            tid = random.choice(task_ids)
            resp = await authenticated_async_client.put(
                f"/api/v1/tasks/{tid}",
                json={"title": f"Updated Stress {random.randint(0, 1000)}"}
            )
            return resp.status_code

        elif op_type == "attach_tag" and task_ids and tag_ids:
            tid = random.choice(task_ids)
            tgid = random.choice(tag_ids)
            resp = await authenticated_async_client.post(f"/api/v1/tasks/{tid}/tags/{tgid}")
            return resp.status_code

        elif op_type == "get_tasks":
            resp = await authenticated_async_client.get("/api/v1/tasks/")
            return resp.status_code

        return 200

    # Execute many random operations concurrently
    results = await asyncio.gather(*[random_op() for _ in range(num_iterations)])

    # Verify no 500 errors
    for status in results:
        assert status < 500, f"System failed with status {status}"

@pytest.mark.asyncio
async def test_audit_log_resilience_under_load(authenticated_async_client: AsyncClient):
    """Verify that audit logs are correctly recorded even under high load."""
    num_tasks = 15

    # Create tasks concurrently
    responses = await asyncio.gather(*[
        authenticated_async_client.post("/api/v1/tasks/", json={"title": f"Audit Stress {i}"})
        for i in range(num_tasks)
    ])

    for r in responses:
        assert r.status_code == 201

    # Wait a tiny bit for any background flushes if applicable
    # (though our current audit log is usually inline or handled by same transaction)

    # Check audit logs
    audit_resp = await authenticated_async_client.get("/api/v1/audit/logs")
    assert audit_resp.status_code == 200
    logs = audit_resp.json()

    # Filter for task creations
    create_logs = [log for log in logs if log["action"] == "create" and log["target_type"] == "TASK"]

    # Should have at least num_tasks logs (might have more from previous tests in same session)
    assert len(create_logs) >= num_tasks

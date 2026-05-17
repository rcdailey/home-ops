"""Shared permissions helper for taxonomy objects."""

from __future__ import annotations

from paperless._client import get_transport

FAMILY_GROUP_NAME = "family"


async def ensure_family_group() -> int:
    """Find or create the 'family' group and return its ID."""
    transport = get_transport()
    try:
        data = await transport.get("/api/groups/")
        results = data.get("results", data) if isinstance(data, dict) else data
        for group in results:
            if group.get("name") == FAMILY_GROUP_NAME:
                return group["id"]
        result = await transport.post(
            "/api/groups/", json={"name": FAMILY_GROUP_NAME, "permissions": []}
        )
        return result["id"]
    finally:
        await transport.close()


async def set_family_permissions(object_type: str, object_id: int) -> None:
    """Grant family group view+change permissions on a taxonomy object.

    object_type: one of "correspondents", "tags", "document_types"
    object_id: the numeric ID returned from the create call
    """
    group_id = await ensure_family_group()
    transport = get_transport()
    try:
        await transport.patch(
            f"/api/{object_type}/{object_id}/",
            json={
                "set_permissions": {
                    "view": {"users": [], "groups": [group_id]},
                    "change": {"users": [], "groups": [group_id]},
                }
            },
        )
    finally:
        await transport.close()

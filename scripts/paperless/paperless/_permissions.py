"""Shared permissions helper for taxonomy objects."""

from __future__ import annotations

from paperless._client import get_transport

FAMILY_GROUP_NAME = "family"
INBOX_TAG_NAME = "inbox"

_BASE_FIELDS: dict[str, object] = {
    "match": "",
    "matching_algorithm": 0,
    "is_insensitive": True,
}


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


async def create_object(object_type: str, fields: dict[str, object]) -> int:
    """Create a taxonomy object with family group permissions in one atomic POST.

    object_type: API path segment, e.g. "correspondents", "tags", "document_types"
    fields: caller-supplied fields (name, color, etc.); base defaults are merged in automatically
    Returns the created object's ID.
    """
    group_id = await ensure_family_group()
    body: dict[str, object] = {
        **_BASE_FIELDS,
        **fields,
        "set_permissions": {
            "view": {"users": [], "groups": [group_id]},
            "change": {"users": [], "groups": [group_id]},
        },
    }
    transport = get_transport()
    try:
        result = await transport.post(f"/api/{object_type}/", json=body)
        return result["id"]
    finally:
        await transport.close()


async def ensure_inbox_tag() -> int:
    """Find or create the inbox tag and return its ID."""
    transport = get_transport()
    try:
        data = await transport.get("/api/tags/")
        results = data.get("results", data) if isinstance(data, dict) else data
        for tag in results:
            if tag.get("name") == INBOX_TAG_NAME:
                return tag["id"]
    finally:
        await transport.close()
    return await create_object(
        "tags",
        {"name": INBOX_TAG_NAME, "is_inbox_tag": True, "color": "#a6cee3"},
    )


async def set_family_permissions(object_type: str, object_id: int) -> None:
    """Grant family group view+change permissions on an existing taxonomy object.

    object_type: one of "correspondents", "tags", "document_types"
    object_id: the numeric ID of the object to update
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

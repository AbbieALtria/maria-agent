import pytest
from httpx import AsyncClient
from tests.conftest import PASSWORD, auth_header

from app.crm.enums import UserRole


async def test_login_and_me(client: AsyncClient, make_user) -> None:
    user = await make_user(UserRole.manager, email="Manager@Example.com")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "manager@example.com", "password": PASSWORD}
    )
    # stored email kept its case; lookup is case-insensitive
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    assert resp.json()["user"]["role"] == "manager"
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["id"] == str(user.id)
    assert "password_hash" not in me.json()


async def test_login_wrong_password(client: AsyncClient, make_user) -> None:
    user = await make_user(UserRole.admin)
    resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "nope"})
    assert resp.status_code == 401


async def test_login_unknown_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 401


async def test_inactive_user_rejected(client: AsyncClient, make_user, db_session) -> None:
    user = await make_user(UserRole.admin)
    headers = auth_header(user)
    user.is_active = False
    await db_session.flush()
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401
    resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 401


@pytest.mark.parametrize("header", [None, "Bearer garbage", "Basic abc"])
async def test_requires_valid_token(client: AsyncClient, header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    assert (await client.get("/api/v1/campaigns", headers=headers)).status_code == 401


async def test_role_change_applies_immediately(client: AsyncClient, make_user, db_session) -> None:
    user = await make_user(UserRole.admin)
    headers = auth_header(user)
    assert (await client.get("/api/v1/sip-trunks", headers=headers)).status_code == 200
    user.role = UserRole.rep  # token still says admin
    await db_session.flush()
    assert (await client.get("/api/v1/sip-trunks", headers=headers)).status_code == 403


# (method, path, body, {role: expected_status})
MATRIX = [
    ("GET", "/api/v1/campaigns", None,
     {"admin": 200, "manager": 200, "rep": 200, "qa": 200}),
    ("POST", "/api/v1/clients", {"name": "Acme"},
     {"admin": 201, "manager": 201, "rep": 403, "qa": 403}),
    ("GET", "/api/v1/users", None,
     {"admin": 200, "manager": 200, "rep": 403, "qa": 403}),
    ("POST", "/api/v1/users",
     {"email": "new-{role}@example.com", "password": "longenough", "role": "rep"},
     {"admin": 201, "manager": 403, "rep": 403, "qa": 403}),
    ("GET", "/api/v1/sip-trunks", None,
     {"admin": 200, "manager": 200, "rep": 403, "qa": 403}),
    ("POST", "/api/v1/sip-trunks", {"name": "t", "market": "US"},
     {"admin": 201, "manager": 403, "rep": 403, "qa": 403}),
    ("POST", "/api/v1/dnc", {"phone": "+13125550100"},
     {"admin": 201, "manager": 201, "rep": 201, "qa": 201}),
    ("POST", "/api/v1/teams", {"name": "Sales", "timezone": "America/Chicago"},
     {"admin": 201, "manager": 201, "rep": 403, "qa": 403}),
]  # fmt: skip


@pytest.mark.parametrize(("method", "path", "body", "expected"), MATRIX)
@pytest.mark.parametrize("role", ["admin", "manager", "rep", "qa"])
async def test_role_matrix(
    client: AsyncClient, make_user, method: str, path: str, body, expected, role: str
) -> None:
    user = await make_user(UserRole(role))
    if isinstance(body, dict):
        body = {k: v.format(role=role) if isinstance(v, str) else v for k, v in body.items()}
    resp = await client.request(method, path, json=body, headers=auth_header(user))
    assert resp.status_code == expected[role], resp.text


async def test_dnc_delete_admin_only(client: AsyncClient, make_user) -> None:
    admin, manager = await make_user(UserRole.admin), await make_user(UserRole.manager)
    created = await client.post(
        "/api/v1/dnc", json={"phone": "+13125550101"}, headers=auth_header(manager)
    )
    entry_id = created.json()["id"]
    r = await client.delete(f"/api/v1/dnc/{entry_id}", headers=auth_header(manager))
    assert r.status_code == 403
    r = await client.delete(f"/api/v1/dnc/{entry_id}", headers=auth_header(admin))
    assert r.status_code == 204


async def test_cannot_remove_last_admin(client: AsyncClient, make_user, db_session) -> None:
    from sqlalchemy import update

    from app.crm.models import User

    await db_session.execute(update(User).values(is_active=False))
    admin = await make_user(UserRole.admin)
    r = await client.patch(
        f"/api/v1/users/{admin.id}", json={"role": "rep"}, headers=auth_header(admin)
    )
    assert r.status_code == 409


async def test_create_user_then_login(client: AsyncClient, admin_headers) -> None:
    r = await client.post(
        "/api/v1/users",
        json={"email": "rep@altria.local", "password": "s3cret-pass", "role": "rep"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    dup = await client.post(
        "/api/v1/users",
        json={"email": "REP@altria.local", "password": "s3cret-pass", "role": "rep"},
        headers=admin_headers,
    )
    assert dup.status_code == 409
    login = await client.post(
        "/api/v1/auth/login", json={"email": "rep@altria.local", "password": "s3cret-pass"}
    )
    assert login.status_code == 200

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.crm.deps import AnyUser, DbSession, Manager
from app.crm.models import AvailabilityOverride, AvailabilityRule, Team, TeamMember, User
from app.crm.schemas import AvailabilityIn, AvailabilityOut, TeamIn, TeamOut, TeamUpdate

router = APIRouter(prefix="/teams", tags=["teams"])


async def _members(session: DbSession, team_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    out: dict[uuid.UUID, list] = {t: [] for t in team_ids}
    rows = await session.execute(
        select(TeamMember.team_id, TeamMember.user_id).where(TeamMember.team_id.in_(team_ids))
    )
    for team_id, user_id in rows:
        out[team_id].append(user_id)
    return out


async def _set_members(session: DbSession, team: Team, member_ids: list[uuid.UUID]) -> None:
    ids = list(dict.fromkeys(member_ids))
    found = set(await session.scalars(select(User.id).where(User.id.in_(ids))))
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(422, f"unknown users: {missing}")
    await session.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    session.add_all(TeamMember(team_id=team.id, user_id=u) for u in ids)


def _out(team: Team, members: list[uuid.UUID]) -> TeamOut:
    out = TeamOut.model_validate(team)
    out.member_ids = members
    return out


@router.get("", response_model=list[TeamOut])
async def list_teams(session: DbSession, _: AnyUser) -> list[TeamOut]:
    teams = list(await session.scalars(select(Team).order_by(Team.name)))
    members = await _members(session, [t.id for t in teams])
    return [_out(t, members[t.id]) for t in teams]


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(body: TeamIn, session: DbSession, _: Manager) -> TeamOut:
    team = Team(**body.model_dump(exclude={"member_ids"}))
    session.add(team)
    await session.flush()
    await _set_members(session, team, body.member_ids)
    await session.commit()
    await session.refresh(team)
    return _out(team, (await _members(session, [team.id]))[team.id])


async def _get_team(session: DbSession, team_id: uuid.UUID) -> Team:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "team not found")
    return team


@router.patch("/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: uuid.UUID, body: TeamUpdate, session: DbSession, _: Manager
) -> TeamOut:
    team = await _get_team(session, team_id)
    changes = body.model_dump(exclude_unset=True)
    member_ids = changes.pop("member_ids", None)
    for k, v in changes.items():
        if v is not None or k in ("client_id", "webhook_url"):
            setattr(team, k, v)
    if member_ids is not None:
        await _set_members(session, team, member_ids)
    await session.commit()
    await session.refresh(team)
    return _out(team, (await _members(session, [team.id]))[team.id])


@router.get("/{team_id}/availability", response_model=AvailabilityOut)
async def get_availability(team_id: uuid.UUID, session: DbSession, _: AnyUser) -> AvailabilityOut:
    await _get_team(session, team_id)
    rules = await session.scalars(
        select(AvailabilityRule)
        .where(AvailabilityRule.team_id == team_id)
        .order_by(AvailabilityRule.weekday, AvailabilityRule.start_time)
    )
    overrides = await session.scalars(
        select(AvailabilityOverride)
        .where(AvailabilityOverride.team_id == team_id)
        .order_by(AvailabilityOverride.date)
    )
    return AvailabilityOut.model_validate(
        {"rules": list(rules), "overrides": list(overrides)}, from_attributes=True
    )


@router.post("/{team_id}/availability", response_model=AvailabilityOut)
async def set_availability(
    team_id: uuid.UUID, body: AvailabilityIn, session: DbSession, user: Manager
) -> AvailabilityOut:
    """Replace the team's weekly rules and date overrides."""
    await _get_team(session, team_id)
    await session.execute(delete(AvailabilityRule).where(AvailabilityRule.team_id == team_id))
    await session.execute(
        delete(AvailabilityOverride).where(AvailabilityOverride.team_id == team_id)
    )
    session.add_all(AvailabilityRule(team_id=team_id, **r.model_dump()) for r in body.rules)
    session.add_all(AvailabilityOverride(team_id=team_id, **o.model_dump()) for o in body.overrides)
    await session.commit()
    return await get_availability(team_id, session, user)

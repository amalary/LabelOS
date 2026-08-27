from collections.abc import Mapping
from uuid import UUID

from labelos_database.models import Campaign, CampaignGoal, CampaignMilestone
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


async def campaign_exists(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(Campaign.id)
            .where(Campaign.organization_id == workspace_id)
            .where(Campaign.id == campaign_id)
        )
        is not None
    )


async def list_goals(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> list[CampaignGoal] | None:
    if not await campaign_exists(session, workspace_id, campaign_id):
        return None
    rows = await session.scalars(
        select(CampaignGoal)
        .join(CampaignGoal.campaign)
        .where(Campaign.organization_id == workspace_id)
        .where(CampaignGoal.campaign_id == campaign_id)
        .order_by(CampaignGoal.created_at.asc(), CampaignGoal.id.asc())
    )
    return list(rows.all())


async def get_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_id: UUID,
) -> CampaignGoal | None:
    return await session.scalar(
        select(CampaignGoal)
        .join(CampaignGoal.campaign)
        .where(Campaign.organization_id == workspace_id)
        .where(CampaignGoal.campaign_id == campaign_id)
        .where(CampaignGoal.id == goal_id)
    )


async def create_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    values: Mapping[str, object],
) -> CampaignGoal | None:
    if not await campaign_exists(session, workspace_id, campaign_id):
        return None
    goal = CampaignGoal(campaign_id=campaign_id, **dict(values))
    session.add(goal)
    await session.flush()
    return goal


async def update_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_id: UUID,
    values: Mapping[str, object],
) -> CampaignGoal | None:
    goal = await get_goal(session, workspace_id, campaign_id, goal_id)
    if goal is None:
        return None
    for key, value in values.items():
        setattr(goal, key, value)
    await session.flush()
    return goal


async def delete_goal(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_id: UUID,
) -> bool:
    result = await session.execute(
        delete(CampaignGoal)
        .where(CampaignGoal.id == goal_id)
        .where(CampaignGoal.campaign_id == campaign_id)
        .where(
            CampaignGoal.campaign_id.in_(
                select(Campaign.id).where(Campaign.organization_id == workspace_id)
            )
        )
    )
    return result.rowcount > 0


async def list_milestones(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> list[CampaignMilestone] | None:
    if not await campaign_exists(session, workspace_id, campaign_id):
        return None
    rows = await session.scalars(
        select(CampaignMilestone)
        .join(CampaignMilestone.campaign)
        .where(Campaign.organization_id == workspace_id)
        .where(CampaignMilestone.campaign_id == campaign_id)
        .order_by(
            CampaignMilestone.target_date.asc().nulls_last(),
            CampaignMilestone.created_at.asc(),
            CampaignMilestone.id.asc(),
        )
    )
    return list(rows.all())


async def get_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
) -> CampaignMilestone | None:
    return await session.scalar(
        select(CampaignMilestone)
        .join(CampaignMilestone.campaign)
        .where(Campaign.organization_id == workspace_id)
        .where(CampaignMilestone.campaign_id == campaign_id)
        .where(CampaignMilestone.id == milestone_id)
    )


async def create_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    values: Mapping[str, object],
) -> CampaignMilestone | None:
    if not await campaign_exists(session, workspace_id, campaign_id):
        return None
    milestone = CampaignMilestone(campaign_id=campaign_id, **dict(values))
    session.add(milestone)
    await session.flush()
    return milestone


async def update_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
    values: Mapping[str, object],
) -> CampaignMilestone | None:
    milestone = await get_milestone(session, workspace_id, campaign_id, milestone_id)
    if milestone is None:
        return None
    for key, value in values.items():
        setattr(milestone, key, value)
    await session.flush()
    return milestone


async def delete_milestone(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
) -> bool:
    result = await session.execute(
        delete(CampaignMilestone)
        .where(CampaignMilestone.id == milestone_id)
        .where(CampaignMilestone.campaign_id == campaign_id)
        .where(
            CampaignMilestone.campaign_id.in_(
                select(Campaign.id).where(Campaign.organization_id == workspace_id)
            )
        )
    )
    return result.rowcount > 0

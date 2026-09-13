import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db import get_db
from app.modules.companies.models import Company, CompanyStatus
from app.modules.leads.models import Lead, LeadStatus
from app.modules.opportunities.models import Opportunity, OpportunityStatus
from app.modules.service_lines.models import PipelineStage
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.models import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class TaskBucket(BaseModel):
    id: uuid.UUID
    title: str
    due_date: datetime | None
    priority: str


class PipelineColumn(BaseModel):
    stage_id: uuid.UUID
    stage_name: str
    count: int
    total_value: float


class DashboardOut(BaseModel):
    my_open_tasks: int
    my_overdue_tasks: int
    overdue_task_items: list[TaskBucket]
    upcoming_tasks: list[TaskBucket]
    open_opportunities: int
    pipeline_value_eur: float
    pipeline_by_stage: list[PipelineColumn]
    stale_opportunities: int
    new_leads_30d: int
    companies_total: int
    customers_total: int
    unassigned_companies: int


STALE_DAYS = 14


@router.get("", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("dashboard:read")),
):
    now = datetime.now(UTC)
    open_states = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)

    my_open = db.scalar(
        select(func.count(Task.id)).where(
            Task.deleted_at.is_(None), Task.owner_id == user.id, Task.status.in_(open_states)
        )
    ) or 0

    overdue_stmt = (
        select(Task)
        .where(
            Task.deleted_at.is_(None),
            Task.status.in_(open_states),
            Task.due_date.is_not(None),
            Task.due_date < now,
        )
        .order_by(Task.due_date)
    )
    overdue_rows = db.scalars(overdue_stmt).all()
    my_overdue = sum(1 for t in overdue_rows if t.owner_id == user.id)

    upcoming = db.scalars(
        select(Task)
        .where(
            Task.deleted_at.is_(None),
            Task.status.in_(open_states),
            Task.due_date.is_not(None),
            Task.due_date >= now,
            Task.due_date <= now + timedelta(days=7),
        )
        .order_by(Task.due_date)
        .limit(10)
    ).all()

    open_opps = db.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.deleted_at.is_(None), Opportunity.status == OpportunityStatus.OPEN
        )
    ) or 0

    pipeline_value = db.scalar(
        select(func.coalesce(func.sum(Opportunity.expected_value_eur), 0)).where(
            Opportunity.deleted_at.is_(None), Opportunity.status == OpportunityStatus.OPEN
        )
    ) or 0

    stage_rows = db.execute(
        select(PipelineStage.id, PipelineStage.name,
               func.count(Opportunity.id),
               func.coalesce(func.sum(Opportunity.expected_value_eur), 0))
        .join(Opportunity,
              (Opportunity.stage_id == PipelineStage.id)
              & (Opportunity.deleted_at.is_(None))
              & (Opportunity.status == OpportunityStatus.OPEN),
              isouter=True)
        .where(PipelineStage.is_active.is_(True))
        .group_by(PipelineStage.id, PipelineStage.name, PipelineStage.position)
        .order_by(PipelineStage.position)
    ).all()

    stale_cutoff = now - timedelta(days=STALE_DAYS)
    stale = db.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.deleted_at.is_(None),
            Opportunity.status == OpportunityStatus.OPEN,
            Opportunity.updated_at < stale_cutoff,
        )
    ) or 0

    new_leads = db.scalar(
        select(func.count(Lead.id)).where(
            Lead.deleted_at.is_(None),
            Lead.status == LeadStatus.NEW,
            Lead.created_at >= now - timedelta(days=30),
        )
    ) or 0

    companies_total = db.scalar(
        select(func.count(Company.id)).where(Company.deleted_at.is_(None))
    ) or 0
    customers = db.scalar(
        select(func.count(Company.id)).where(
            Company.deleted_at.is_(None), Company.status == CompanyStatus.CUSTOMER
        )
    ) or 0
    unassigned = db.scalar(
        select(func.count(Company.id)).where(
            Company.deleted_at.is_(None), Company.owner_id.is_(None)
        )
    ) or 0

    return DashboardOut(
        my_open_tasks=my_open,
        my_overdue_tasks=my_overdue,
        overdue_task_items=[
            TaskBucket(id=t.id, title=t.title, due_date=t.due_date, priority=t.priority)
            for t in overdue_rows[:10]
        ],
        upcoming_tasks=[
            TaskBucket(id=t.id, title=t.title, due_date=t.due_date, priority=t.priority)
            for t in upcoming
        ],
        open_opportunities=open_opps,
        pipeline_value_eur=float(pipeline_value),
        pipeline_by_stage=[
            PipelineColumn(stage_id=r[0], stage_name=r[1], count=r[2], total_value=float(r[3]))
            for r in stage_rows
        ],
        stale_opportunities=stale,
        new_leads_30d=new_leads,
        companies_total=companies_total,
        customers_total=customers,
        unassigned_companies=unassigned,
    )

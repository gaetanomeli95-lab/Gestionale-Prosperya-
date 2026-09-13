from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.rbac import get_current_user, require_permissions
from app.db import get_db
from app.modules.service_lines.models import PipelineStage, ServiceLine
from app.modules.service_lines.schemas import (
    PipelineStageCreate,
    PipelineStageOut,
    ServiceLineCreate,
    ServiceLineOut,
)
from app.modules.users.models import User

router = APIRouter(prefix="/service-lines", tags=["service-lines"])


@router.get("", response_model=list[ServiceLineOut])
def list_service_lines(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = db.scalars(
        select(ServiceLine).where(ServiceLine.is_active.is_(True)).order_by(ServiceLine.sort_order)
    ).all()
    return [ServiceLineOut.model_validate(r) for r in rows]


@router.post("", response_model=ServiceLineOut, status_code=201)
def create_service_line(
    payload: ServiceLineCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("service_lines:write")),
):
    if db.scalar(select(ServiceLine).where(ServiceLine.code == payload.code)):
        raise ConflictError("A service line with this code already exists.", code="duplicate_service_line")
    sl = ServiceLine(**payload.model_dump())
    db.add(sl)
    db.commit()
    return ServiceLineOut.model_validate(sl)


@router.get("/pipeline-stages", response_model=list[PipelineStageOut])
def list_stages(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = db.scalars(
        select(PipelineStage)
        .where(PipelineStage.is_active.is_(True))
        .order_by(PipelineStage.position)
    ).all()
    return [PipelineStageOut.model_validate(r) for r in rows]


@router.post("/pipeline-stages", response_model=PipelineStageOut, status_code=201)
def create_stage(
    payload: PipelineStageCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("service_lines:write")),
):
    stage = PipelineStage(**payload.model_dump())
    db.add(stage)
    db.commit()
    return PipelineStageOut.model_validate(stage)

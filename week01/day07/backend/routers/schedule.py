from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from schemas.schedule import ScheduleCreate, ScheduleUpdate
from dependencies import get_db, get_current_admin, get_current_worker
from services import schedule as service
from utils.response import ok, ok_page

router = APIRouter(prefix="/api/schedules", tags=["排班管理"])


@router.get("")
def get_schedules(
    date: str = Query(..., description="日期，格式 YYYY-MM-DD"),
    view: str = Query("worker", pattern="^(worker|patient)$"),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.get_schedule_view(db, date, view)
    return ok(result)


@router.post("")
def create_schedule(
    data: ScheduleCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.create_schedule(db, data, user.id)
    return ok(result, "排班创建成功")


@router.put("/{schedule_id}")
def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    # For now, update reuses create logic via cancel+create
    service.cancel_schedule(db, schedule_id, user.id)
    result = service.create_schedule(db, data, user.id)
    return ok(result, "排班更新成功")


@router.delete("/{schedule_id}")
def cancel_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.cancel_schedule(db, schedule_id, user.id)
    return ok(result, "排班已取消")


@router.get("/logs")
def get_logs(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.get_schedule_logs(db, page=page, page_size=pageSize)
    return ok_page(result["data"], result["total"], page, pageSize)


@router.get("/my")
def get_my_schedules(
    date: str | None = Query(None, description="日期，格式 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.get_my_schedules(db, worker.id, date)
    return ok(result)

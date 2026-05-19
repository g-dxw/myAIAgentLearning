from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from dependencies import get_db, get_current_worker
from services import reminder as service
from utils.response import ok, ok_page

router = APIRouter(prefix="/api/reminders", tags=["提醒"])


@router.get("")
def list_reminders(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.list_reminders(db, worker.id, page=page, page_size=pageSize)
    return ok_page(result["data"], result["total"], page, pageSize)


@router.patch("/{reminder_id}/read")
def mark_read(
    reminder_id: int,
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.mark_read(db, reminder_id, worker.id)
    return ok(result, "已标记为已读")

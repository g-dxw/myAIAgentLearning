from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from schemas.checkin import CheckinStart, CheckinSubmit, CheckinMakeup
from dependencies import get_db, get_current_worker
from services import checkin as service
from utils.response import ok

router = APIRouter(prefix="/api/checkin", tags=["打卡"])


@router.post("")
def start_checkin(
    data: CheckinStart,
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.start_checkin(db, data, worker.id)
    return ok(result, "开始服务")


@router.post("/{checkin_id}/submit")
def submit_checkin(
    checkin_id: int,
    data: CheckinSubmit,
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.submit_checkin(db, checkin_id, data, worker.id)
    return ok(result, "护理记录已提交")


@router.post("/makeup")
def makeup_checkin(
    data: CheckinMakeup,
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.makeup_checkin(db, data, worker.id)
    return ok(result, "补卡成功")


@router.get("/my")
def get_my_checkins(
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.get_my_checkins(db, worker.id)
    return ok(result)

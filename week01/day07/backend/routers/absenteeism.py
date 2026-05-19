from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from schemas.absenteeism import AbsenteeismCorrect
from dependencies import get_db, get_current_admin
from services import absenteeism as service
from utils.response import ok, ok_page

router = APIRouter(prefix="/api/absenteeism", tags=["出勤统计"])


@router.get("")
def list_absenteeism(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    worker_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.list_absenteeism(
        db, page=page, page_size=pageSize,
        worker_id=worker_id, start_date=start_date, end_date=end_date,
    )
    return ok_page(result["data"], result["total"], page, pageSize)


@router.patch("/{absenteeism_id}/correct")
def correct_absenteeism(
    absenteeism_id: int,
    data: AbsenteeismCorrect,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.correct_absenteeism(db, absenteeism_id, data, user.id)
    return ok(result, "旷工状态已纠正")

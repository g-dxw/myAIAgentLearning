from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from dependencies import get_db, get_current_admin, get_current_worker, get_current_user
from services import record as service
from utils.response import ok, ok_page

router = APIRouter(prefix="/api/records", tags=["护理记录"])


@router.get("")
def list_records(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    patient_id: int | None = None,
    worker_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.list_records(
        db, page=page, page_size=pageSize,
        patient_id=patient_id, worker_id=worker_id,
    )
    return ok_page(result["data"], result["total"], page, pageSize)


@router.get("/my")
def list_my_records(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.list_my_records(db, worker.id, page=page, page_size=pageSize)
    return ok_page(result["data"], result["total"], page, pageSize)


@router.get("/{record_id}")
def get_record(
    record_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    result = service.get_record(db, record_id)
    return ok(result)

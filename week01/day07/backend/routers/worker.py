from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from schemas.worker import WorkerCreate, WorkerUpdate, WorkerStatusUpdate
from dependencies import get_db, get_current_admin
from services import worker as service
from utils.response import ok, ok_page

router = APIRouter(prefix="/api/workers", tags=["护工管理"])


@router.get("")
def list_workers(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    name: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.list_workers(db, page=page, page_size=pageSize, name=name, status=status)
    return ok_page(result["data"], result["total"], page, pageSize)


@router.get("/{worker_id}")
def get_worker(worker_id: int, db: Session = Depends(get_db), _=Depends(get_current_admin)):
    result = service.get_worker(db, worker_id)
    return ok(result)


@router.post("")
def create_worker(data: WorkerCreate, db: Session = Depends(get_db), _=Depends(get_current_admin)):
    result = service.create_worker(db, data)
    return ok(result, "护工创建成功")


@router.put("/{worker_id}")
def update_worker(
    worker_id: int,
    data: WorkerUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.update_worker(db, worker_id, data)
    return ok(result, "更新成功")


@router.patch("/{worker_id}/status")
def update_status(
    worker_id: int,
    data: WorkerStatusUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.update_status(db, worker_id, data)
    return ok(result, "状态更新成功")


@router.delete("/{worker_id}")
def delete_worker(worker_id: int, db: Session = Depends(get_db), _=Depends(get_current_admin)):
    result = service.delete_worker(db, worker_id)
    return ok(result, "删除成功")


@router.patch("/{worker_id}/reset-password")
def reset_password(
    worker_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.reset_password(db, worker_id)
    return ok(result, "密码已重置")

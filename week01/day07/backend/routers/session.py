from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from schemas.session import SessionCreate, MessageAdd, ConfirmSubmit
from dependencies import get_db, get_current_worker
from services import session as service
from utils.response import ok

router = APIRouter(prefix="/api", tags=["AI 对话"])


@router.get("/worker/patients")
def get_worker_patients(
    db: DbSession = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.get_worker_patients(db, worker.id)
    return ok(result)


@router.post("/sessions")
def create_session(
    data: SessionCreate,
    db: DbSession = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.get_or_create_session(db, data, worker.id)
    return ok(result, "对话已创建")


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    db: DbSession = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.get_session(db, session_id, worker.id)
    return ok(result)


@router.post("/sessions/{session_id}/messages")
def add_message(
    session_id: int,
    data: MessageAdd,
    db: DbSession = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.add_message(db, session_id, data, worker.id)
    return ok(result)


@router.post("/sessions/{session_id}/extract")
def extract_info(
    session_id: int,
    db: DbSession = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.extract_info(db, session_id, worker.id)
    return ok(result)


@router.post("/sessions/{session_id}/confirm")
def confirm_submit(
    session_id: int,
    data: ConfirmSubmit,
    db: DbSession = Depends(get_db),
    worker=Depends(get_current_worker),
):
    result = service.confirm_submit(db, session_id, data, worker.id)
    return ok(result, "信息已提交")

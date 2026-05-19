from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from schemas.patient import (
    PatientCreate, PatientUpdate, PatientAssign,
    SpecialConditionCreate, RejectRequest,
)
from dependencies import get_db, get_current_admin, get_current_user
from services import patient as service
from utils.response import ok, ok_page

router = APIRouter(prefix="/api", tags=["病人管理"])


# ── 病人 CRUD ──
@router.get("/patients")
def list_patients(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    name: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.list_patients(db, page=page, page_size=pageSize, name=name, status=status)
    return ok_page(result["data"], result["total"], page, pageSize)


@router.get("/patients/{patient_id}")
def get_patient(patient_id: int, db: Session = Depends(get_db), _=Depends(get_current_admin)):
    result = service.get_patient(db, patient_id)
    return ok(result)


@router.post("/patients")
def create_patient(
    data: PatientCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.create_patient(db, data, user.id)
    return ok(result, "病人创建成功")


@router.put("/patients/{patient_id}")
def update_patient(
    patient_id: int,
    data: PatientUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.update_patient(db, patient_id, data, user.id)
    return ok(result, "更新成功")


@router.post("/patients/{patient_id}/assign")
def assign_worker(
    patient_id: int,
    data: PatientAssign,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.assign_worker(db, patient_id, data.worker_id, user.id)
    return ok(result, "护工分配成功")


# ── 审核 ──
@router.get("/approvals")
def list_approvals(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.list_approvals(db, page=page, page_size=pageSize)
    return ok_page(result["data"], result["total"], page, pageSize)


@router.post("/approvals/{patient_id}/approve")
def approve_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.approve_patient(db, patient_id, user.id)
    return ok(result, "审核通过")


@router.post("/approvals/{patient_id}/reject")
def reject_patient(
    patient_id: int,
    data: RejectRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    result = service.reject_patient(db, patient_id, data.reason, user.id)
    return ok(result, "已驳回")


# ── 特殊情况 ──
@router.get("/patients/{patient_id}/special-conditions")
def list_special_conditions(
    patient_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.list_special_conditions(db, patient_id)
    return ok(result)


@router.post("/patients/{patient_id}/special-conditions")
def add_special_condition(
    patient_id: int,
    data: SpecialConditionCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.add_special_condition(db, patient_id, data)
    return ok(result, "特殊情况添加成功")


# ── 版本历史 ──
@router.get("/patients/{patient_id}/versions")
def list_versions(
    patient_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
):
    result = service.list_versions(db, patient_id)
    return ok(result)

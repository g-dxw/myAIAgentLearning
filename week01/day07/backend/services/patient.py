"""病人管理业务逻辑：CRUD + 审核流程 + 特殊情况 + 版本追踪"""
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from models.patient import Patient, PatientStatus
from models.worker import Worker
from models.special_cond import SpecialCondition
from models.patient_version import PatientVersion
from schemas.patient import (
    PatientCreate, PatientUpdate, PatientAssign,
    SpecialConditionCreate, RejectRequest,
)


def _to_out(p) -> dict:
    """Patient ORM 对象 → 前端响应 dict"""
    status = p.status
    if hasattr(status, "value"):
        status = status.value
    return {
        "id": p.id,
        "name": p.name,
        "age": p.age,
        "gender": p.gender,
        "insurance_type": p.insurance_type,
        "phone": p.phone,
        "address": p.address,
        "emergency_contact": p.emergency_contact or "",
        "guardian_info": p.guardian_info,
        "disease_info": p.disease_info,
        "care_requirements": p.care_requirements,
        "personality": p.personality,
        "status": status,
        "assigned_worker_id": p.assigned_worker_id,
        "assigned_worker_name": p.assigned_worker.name if p.assigned_worker else None,
        "last_updater_id": p.last_updater_id,
        "update_method": p.update_method,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else "",
    }


def _record_version(
    db: Session,
    patient_id: int,
    updater_id: int,
    method: str,
    changed_fields: dict,
):
    """创建一条病人档案变更记录"""
    version = PatientVersion(
        patient_id=patient_id,
        updater_id=updater_id,
        update_method=method,
        changed_fields=json.dumps(changed_fields, ensure_ascii=False),
    )
    db.add(version)


def list_patients(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    name: str | None = None,
    status: str | None = None,
):
    """分页查询病人列表，支持按姓名模糊搜索和状态筛选"""
    query = db.query(Patient).options(joinedload(Patient.assigned_worker))
    if name:
        query = query.filter(Patient.name.contains(name))
    if status:
        query = query.filter(Patient.status == status)

    total = query.count()
    patients = query.order_by(Patient.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {"data": [_to_out(p) for p in patients], "total": total}


def create_patient(db: Session, data: PatientCreate, admin_id: int):
    """管理员新增病人：创建后自动审核通过（管理员自审），记录版本历史"""
    patient = Patient(
        name=data.name,
        age=data.age,
        gender=data.gender,
        insurance_type=data.insurance_type,
        phone=data.phone,
        address=data.address,
        emergency_contact=data.emergency_contact,
        status=PatientStatus.PENDING,
        assigned_worker_id=data.assigned_worker_id,
        last_updater_id=admin_id,
        update_method="admin_manual",
        updated_at=datetime.utcnow(),
    )
    db.add(patient)
    db.flush()

    # 管理员自审：直接激活
    patient.status = PatientStatus.ACTIVE
    db.flush()

    _record_version(db, patient.id, admin_id, "admin_manual", {"action": "create"})
    db.commit()
    db.refresh(patient)
    return _to_out(patient)


def get_patient(db: Session, patient_id: int):
    """查询单个病人详情（含分配的护工信息）"""
    patient = db.query(Patient).options(joinedload(Patient.assigned_worker)).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="病人不存在")
    return _to_out(patient)


def update_patient(db: Session, patient_id: int, data: PatientUpdate, admin_id: int):
    """管理员编辑病人信息，记录变更到版本历史"""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="病人不存在")

    changed = {}
    for field in ["name", "age", "gender", "insurance_type", "phone", "address",
                   "emergency_contact", "assigned_worker_id"]:
        old_val = getattr(patient, field)
        new_val = getattr(data, field)
        if old_val != new_val:
            changed[field] = {"old": str(old_val), "new": str(new_val)}
            setattr(patient, field, new_val)

    if changed:
        patient.last_updater_id = admin_id
        patient.update_method = "admin_manual"
        patient.updated_at = datetime.utcnow()
        _record_version(db, patient.id, admin_id, "admin_manual", changed)

    db.commit()
    db.refresh(patient)
    return _to_out(patient)


def assign_worker(db: Session, patient_id: int, worker_id: int, admin_id: int):
    """为病人重新分配护工，记录变更历史"""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="病人不存在")

    worker = db.query(Worker).filter(Worker.id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="护工不存在")

    old_worker = patient.assigned_worker_id
    patient.assigned_worker_id = worker_id
    patient.last_updater_id = admin_id
    patient.update_method = "admin_manual"
    patient.updated_at = datetime.utcnow()
    _record_version(db, patient.id, admin_id, "admin_manual", {
        "assigned_worker_id": {"old": str(old_worker), "new": str(worker_id)}
    })
    db.commit()
    db.refresh(patient)
    return _to_out(patient)


# ── 审核相关 ──

def list_approvals(db: Session, page: int = 1, page_size: int = 20):
    """查询待审核病人列表（status=pending）"""
    query = db.query(Patient).options(joinedload(Patient.assigned_worker)).filter(
        Patient.status == PatientStatus.PENDING
    )
    total = query.count()
    patients = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"data": [_to_out(p) for p in patients], "total": total}


def approve_patient(db: Session, patient_id: int, admin_id: int):
    """审核通过：将病人状态从 pending 改为 active"""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="病人不存在")
    if patient.status != PatientStatus.PENDING:
        raise HTTPException(status_code=400, detail="病人当前状态不可审核")

    patient.status = PatientStatus.ACTIVE
    patient.updated_at = datetime.utcnow()
    _record_version(db, patient.id, admin_id, "admin_manual", {"status": {"old": "pending", "new": "active"}})
    db.commit()
    db.refresh(patient)
    return _to_out(patient)


def reject_patient(db: Session, patient_id: int, reason: str, admin_id: int):
    """驳回病人申请：记录驳回原因后删除记录"""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="病人不存在")

    _record_version(db, patient.id, admin_id, "admin_manual", {
        "status": {"old": "pending", "new": f"rejected: {reason}"}
    })
    db.delete(patient)
    db.commit()
    return {"rejected": True}


# ── 特殊情况 ──

def list_special_conditions(db: Session, patient_id: int):
    """查询病人的所有特殊情况记录（按时间倒序）"""
    conds = db.query(SpecialCondition).filter(
        SpecialCondition.patient_id == patient_id
    ).order_by(SpecialCondition.recorded_at.desc()).all()
    return [
        {
            "id": c.id,
            "patient_id": c.patient_id,
            "type": c.type,
            "description": c.description,
            "recorded_at": c.recorded_at.isoformat() if c.recorded_at else "",
        }
        for c in conds
    ]


def add_special_condition(db: Session, patient_id: int, data: SpecialConditionCreate):
    """新增病人特殊情况（固定类型：死亡/就医/外出/其他）"""
    cond = SpecialCondition(
        patient_id=patient_id,
        type=data.type,
        description=data.description,
    )
    db.add(cond)
    db.commit()
    db.refresh(cond)
    return {
        "id": cond.id,
        "patient_id": cond.patient_id,
        "type": cond.type,
        "description": cond.description,
        "recorded_at": cond.recorded_at.isoformat() if cond.recorded_at else "",
    }


# ── 版本历史 ──

def list_versions(db: Session, patient_id: int):
    """查询病人档案变更历史（按时间倒序）"""
    versions = db.query(PatientVersion).filter(
        PatientVersion.patient_id == patient_id
    ).order_by(PatientVersion.created_at.desc()).all()
    return [
        {
            "id": v.id,
            "patient_id": v.patient_id,
            "updater_id": v.updater_id,
            "update_method": v.update_method,
            "changed_fields": v.changed_fields,
            "created_at": v.created_at.isoformat() if v.created_at else "",
        }
        for v in versions
    ]

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from models.care_record import CareRecord


def _record_to_dict(r: CareRecord) -> dict:
    return {
        "id": r.id,
        "patient_id": r.patient_id,
        "worker_id": r.worker_id,
        "content": r.content,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "patient_name": r.patient.name if r.patient else None,
        "worker_name": r.worker.name if r.worker else None,
    }


def list_records(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    patient_id: int | None = None,
    worker_id: int | None = None,
):
    """机构端全量护理记录查询，支持按病人/护工筛选"""
    query = db.query(CareRecord).options(
        joinedload(CareRecord.patient),
        joinedload(CareRecord.worker),
    )

    if patient_id:
        query = query.filter(CareRecord.patient_id == patient_id)
    if worker_id:
        query = query.filter(CareRecord.worker_id == worker_id)

    total = query.count()
    records = query.order_by(CareRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {"data": [_record_to_dict(r) for r in records], "total": total}


def list_my_records(db: Session, worker_id: int, page: int = 1, page_size: int = 20):
    """护工端查询自己的护理记录"""
    query = db.query(CareRecord).options(
        joinedload(CareRecord.patient),
        joinedload(CareRecord.worker),
    ).filter(CareRecord.worker_id == worker_id)

    total = query.count()
    records = query.order_by(CareRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {"data": [_record_to_dict(r) for r in records], "total": total}


def get_record(db: Session, record_id: int):
    """查询单条护理记录详情"""
    record = db.query(CareRecord).options(
        joinedload(CareRecord.patient),
        joinedload(CareRecord.worker),
    ).filter(CareRecord.id == record_id).first()

    if not record:
        raise HTTPException(status_code=404, detail="护理记录不存在")

    return _record_to_dict(record)

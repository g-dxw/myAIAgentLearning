from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from models.absenteeism import Absenteeism


def _absenteeism_to_dict(a: Absenteeism) -> dict:
    return {
        "id": a.id,
        "schedule_id": a.schedule_id,
        "worker_id": a.worker_id,
        "patient_id": a.patient_id,
        "status": a.status,
        "auto_marked_at": a.auto_marked_at.isoformat() if a.auto_marked_at else "",
        "corrected_at": a.corrected_at.isoformat() if a.corrected_at else None,
        "corrected_by": a.corrected_by,
        "correction_reason": a.correction_reason,
        "score": a.score,
        "created_at": a.created_at.isoformat() if a.created_at else "",
        "worker_name": a.worker.name if a.worker else None,
        "patient_name": None,  # filled below if needed
    }


def list_absenteeism(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    worker_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """分页查询缺勤记录，支持按护工和日期范围筛选"""
    query = db.query(Absenteeism).options(
        joinedload(Absenteeism.worker),
        joinedload(Absenteeism.patient),
    )

    if worker_id:
        query = query.filter(Absenteeism.worker_id == worker_id)
    if start_date:
        query = query.filter(Absenteeism.auto_marked_at >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(
            Absenteeism.auto_marked_at <= datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59)
        )

    total = query.count()
    records = query.order_by(Absenteeism.auto_marked_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    data = []
    for a in records:
        d = _absenteeism_to_dict(a)
        if a.patient:
            d["patient_name"] = a.patient.name
        data.append(d)

    return {"data": data, "total": total}


def correct_absenteeism(db: Session, absenteeism_id: int, data, user_id: int):
    """管理员纠正旷工状态：标记为corrected并记录纠正原因"""
    record = db.query(Absenteeism).filter(Absenteeism.id == absenteeism_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="缺勤记录不存在")

    if record.status != "absent":
        raise HTTPException(status_code=400, detail="该记录当前状态不可纠正")

    record.status = "corrected"
    record.corrected_at = datetime.utcnow()
    record.corrected_by = user_id
    record.correction_reason = data.correction_reason
    db.commit()

    return {"corrected": True}

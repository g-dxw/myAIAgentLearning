from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from models.checkin import Checkin, CheckinStatus
from models.schedule import Schedule, ScheduleStatus
from models.care_record import CareRecord


def _checkin_to_dict(c: Checkin) -> dict:
    status = c.status
    if hasattr(status, "value"):
        status = status.value
    return {
        "id": c.id,
        "worker_id": c.worker_id,
        "patient_id": c.patient_id,
        "schedule_id": c.schedule_id,
        "start_time": c.start_time.isoformat() if c.start_time else "",
        "end_time": c.end_time.isoformat() if c.end_time else None,
        "content": c.content,
        "status": status,
        "is_makeup": c.is_makeup,
        "created_at": c.created_at.isoformat() if c.created_at else "",
        "patient_name": c.patient.name if c.patient else None,
        "worker_name": c.worker.name if c.worker else None,
    }


def start_checkin(db: Session, data, worker_id: int):
    """开始服务打卡：从排班详情页触发，创建Checkin记录，排班状态变为in_progress"""
    schedule = db.query(Schedule).options(
        joinedload(Schedule.patient),
        joinedload(Schedule.worker),
    ).filter(
        Schedule.id == data.schedule_id,
        Schedule.worker_id == worker_id,
    ).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="排班不存在")

    s_status = schedule.status
    if hasattr(s_status, "value"):
        s_status = s_status.value

    if s_status != ScheduleStatus.ASSIGNED.value and s_status != ScheduleStatus.ASSIGNED:
        raise HTTPException(status_code=400, detail="该排班当前状态不可开始服务")

    # Check if already started
    existing = db.query(Checkin).filter(
        Checkin.schedule_id == data.schedule_id,
        Checkin.status == CheckinStatus.STARTED,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该排班已开始服务")

    checkin = Checkin(
        worker_id=worker_id,
        patient_id=schedule.patient_id,
        schedule_id=data.schedule_id,
        start_time=datetime.utcnow(),
        status=CheckinStatus.STARTED,
        is_makeup=False,
    )
    db.add(checkin)
    db.flush()

    schedule.status = ScheduleStatus.IN_PROGRESS
    db.commit()
    db.refresh(checkin)

    return _checkin_to_dict(checkin)


def submit_checkin(db: Session, checkin_id: int, data, worker_id: int):
    """提交护理记录：创建CareRecord + 完成Checkin + 排班状态变为completed"""
    checkin = db.query(Checkin).options(
        joinedload(Checkin.patient),
        joinedload(Checkin.worker),
    ).filter(
        Checkin.id == checkin_id,
        Checkin.worker_id == worker_id,
    ).first()

    if not checkin:
        raise HTTPException(status_code=404, detail="打卡记录不存在")

    c_status = checkin.status
    if hasattr(c_status, "value"):
        c_status = c_status.value

    if c_status != CheckinStatus.STARTED.value and c_status != CheckinStatus.STARTED:
        raise HTTPException(status_code=400, detail="该打卡记录不可提交")

    # Create care record
    record = CareRecord(
        patient_id=checkin.patient_id,
        worker_id=worker_id,
        content=data.content,
    )
    db.add(record)
    db.flush()

    # Update checkin
    checkin.status = CheckinStatus.COMPLETED
    checkin.end_time = datetime.utcnow()
    checkin.content = data.content
    db.flush()

    # Update schedule status
    if checkin.schedule_id:
        schedule = db.query(Schedule).filter(Schedule.id == checkin.schedule_id).first()
        if schedule:
            schedule.status = ScheduleStatus.COMPLETED

    db.commit()
    db.refresh(checkin)

    return _checkin_to_dict(checkin)


def makeup_checkin(db: Session, data, worker_id: int):
    """补卡：不关联排班记录（schedule_id为空），校验不允许跨日，同时创建CareRecord"""
    start_time = datetime.fromisoformat(data.start_time)
    end_time = datetime.fromisoformat(data.end_time)

    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")

    # Cross-day validation
    if start_time.date() != end_time.date():
        raise HTTPException(status_code=400, detail="补卡不允许跨日")

    checkin = Checkin(
        worker_id=worker_id,
        patient_id=data.patient_id,
        schedule_id=None,
        start_time=start_time,
        end_time=end_time,
        content=data.content,
        status=CheckinStatus.COMPLETED,
        is_makeup=True,
    )
    db.add(checkin)
    db.flush()

    # Create care record
    record = CareRecord(
        patient_id=data.patient_id,
        worker_id=worker_id,
        content=data.content,
    )
    db.add(record)
    db.commit()
    db.refresh(checkin)

    return _checkin_to_dict(checkin)


def get_my_checkins(db: Session, worker_id: int):
    """护工端查询自己的打卡记录"""
    checkins = db.query(Checkin).options(
        joinedload(Checkin.patient),
        joinedload(Checkin.worker),
    ).filter(
        Checkin.worker_id == worker_id,
    ).order_by(Checkin.created_at.desc()).all()

    return [_checkin_to_dict(c) for c in checkins]

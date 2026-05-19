from datetime import datetime, date, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from models.schedule import Schedule, ScheduleStatus
from models.schedule_log import ScheduleLog
from models.worker import Worker, WorkerStatus
from models.patient import Patient, PatientStatus
from models.user import User


def _schedule_to_dict(s: Schedule) -> dict:
    status = s.status
    if hasattr(status, "value"):
        status = status.value
    return {
        "id": s.id,
        "worker_id": s.worker_id,
        "patient_id": s.patient_id,
        "start_time": s.start_time.isoformat(),
        "end_time": s.end_time.isoformat(),
        "status": status,
        "worker_name": s.worker.name if s.worker else None,
        "patient_name": s.patient.name if s.patient else None,
    }


def _build_slots(schedules: list, date_str: str, is_worker_view: bool):
    """构建24小时时段数组：将排班记录映射到0-23小时的槽位中"""
    slots = []
    target_date = date.fromisoformat(date_str)

    for hour in range(24):
        slot = {"hour": hour, "schedule_id": None}

        if is_worker_view:
            slot["patient_id"] = None
            slot["patient_name"] = None
        else:
            slot["worker_id"] = None
            slot["worker_name"] = None

        slot["status"] = None

        # Find schedule covering this hour
        for s in schedules:
            s_start = s.start_time
            s_end = s.end_time
            slot_start = datetime(target_date.year, target_date.month, target_date.day, hour)
            slot_end = slot_start + timedelta(hours=1)

            if s_start <= slot_start and s_end >= slot_end:
                status = s.status
                if hasattr(status, "value"):
                    status = status.value

                slot["schedule_id"] = s.id
                slot["status"] = status
                if is_worker_view:
                    slot["patient_id"] = s.patient_id
                    slot["patient_name"] = s.patient.name if s.patient else None
                else:
                    slot["worker_id"] = s.worker_id
                    slot["worker_name"] = s.worker.name if s.worker else None
                break

        slots.append(slot)

    return slots


def get_schedule_view(db: Session, date_str: str, view: str = "worker"):
    """排班矩阵视图：支持护工视角（行=护工，列=24小时）和病人视角（行=病人，列=24小时）"""
    target_date = date.fromisoformat(date_str)
    day_start = datetime(target_date.year, target_date.month, target_date.day)
    day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)

    if view == "worker":
        workers = db.query(Worker).filter(
            Worker.status == WorkerStatus.ACTIVE
        ).all()

        rows = []
        for worker in workers:
            schedules = db.query(Schedule).options(
                joinedload(Schedule.patient),
                joinedload(Schedule.worker),
            ).filter(
                Schedule.worker_id == worker.id,
                Schedule.start_time <= day_end,
                Schedule.end_time >= day_start,
                Schedule.status != ScheduleStatus.CANCELLED,
            ).all()

            rows.append({
                "worker_id": worker.id,
                "worker_name": worker.name,
                "slots": _build_slots(schedules, date_str, True),
            })

        return {"view": "worker", "date": date_str, "rows": rows}

    else:
        patients = db.query(Patient).filter(
            Patient.status == PatientStatus.ACTIVE
        ).all()

        rows = []
        for patient in patients:
            schedules = db.query(Schedule).options(
                joinedload(Schedule.worker),
                joinedload(Schedule.patient),
            ).filter(
                Schedule.patient_id == patient.id,
                Schedule.start_time <= day_end,
                Schedule.end_time >= day_start,
                Schedule.status != ScheduleStatus.CANCELLED,
            ).all()

            rows.append({
                "patient_id": patient.id,
                "patient_name": patient.name,
                "slots": _build_slots(schedules, date_str, False),
            })

        return {"view": "patient", "date": date_str, "rows": rows}


def create_schedule(db: Session, data, user_id: int):
    """创建排班：校验护工/病人状态 + 冲突检测（同一护工/病人不能同时段重复）+ 记录操作日志"""
    worker = db.query(Worker).filter(Worker.id == data.worker_id).first()
    if not worker or worker.status != WorkerStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="护工不存在或已停用")

    patient = db.query(Patient).filter(Patient.id == data.patient_id).first()
    if not patient or patient.status != PatientStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="病人不存在或未激活")

    start_time = datetime.fromisoformat(data.start_time)
    end_time = datetime.fromisoformat(data.end_time)

    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")

    # Conflict check: same worker at the same time
    conflict_worker = db.query(Schedule).filter(
        Schedule.worker_id == data.worker_id,
        Schedule.status != ScheduleStatus.CANCELLED,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
    ).first()
    if conflict_worker:
        raise HTTPException(
            status_code=409,
            detail=f"排班冲突：该护工在 {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} 已有排班",
        )

    # Conflict check: same patient at the same time
    conflict_patient = db.query(Schedule).filter(
        Schedule.patient_id == data.patient_id,
        Schedule.status != ScheduleStatus.CANCELLED,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
    ).first()
    if conflict_patient:
        raise HTTPException(
            status_code=409,
            detail=f"排班冲突：该病人在 {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} 已有排班",
        )

    schedule = Schedule(
        worker_id=data.worker_id,
        patient_id=data.patient_id,
        start_time=start_time,
        end_time=end_time,
        status=ScheduleStatus.ASSIGNED,
    )
    db.add(schedule)
    db.flush()

    # Create schedule log
    log = ScheduleLog(
        schedule_id=schedule.id,
        action="created",
        operator_id=user_id,
    )
    db.add(log)
    db.commit()
    db.refresh(schedule)

    return _schedule_to_dict(schedule)


def cancel_schedule(db: Session, schedule_id: int, user_id: int):
    """取消排班：仅允许取消 assigned 状态的排班，记录操作日志"""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="排班不存在")

    s_status = schedule.status
    if hasattr(s_status, "value"):
        s_status = s_status.value

    if s_status != ScheduleStatus.ASSIGNED.value and s_status != ScheduleStatus.ASSIGNED:
        raise HTTPException(status_code=400, detail="只能取消待执行的排班")

    schedule.status = ScheduleStatus.CANCELLED
    db.flush()

    log = ScheduleLog(
        schedule_id=schedule.id,
        action="cancelled",
        operator_id=user_id,
    )
    db.add(log)
    db.commit()

    return {"cancelled": True}


def get_schedule_logs(db: Session, page: int = 1, page_size: int = 20):
    """分页查询排班变更日志"""
    query = db.query(ScheduleLog).order_by(ScheduleLog.created_at.desc())
    total = query.count()
    logs = query.offset((page - 1) * page_size).limit(page_size).all()

    data = []
    for log in logs:
        data.append({
            "id": log.id,
            "schedule_id": log.schedule_id,
            "action": log.action,
            "operator_id": log.operator_id,
            "original_worker_id": log.original_worker_id,
            "new_worker_id": log.new_worker_id,
            "remark": log.remark,
            "created_at": log.created_at.isoformat() if log.created_at else "",
        })

    return {"data": data, "total": total}


def get_my_schedules(db: Session, worker_id: int, date_str: str | None = None):
    """护工端查询自己的排班列表，可按日期筛选"""
    query = db.query(Schedule).options(
        joinedload(Schedule.patient),
    ).filter(
        Schedule.worker_id == worker_id,
        Schedule.status != ScheduleStatus.CANCELLED,
    )

    if date_str:
        target_date = date.fromisoformat(date_str)
        day_start = datetime(target_date.year, target_date.month, target_date.day)
        day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)
        query = query.filter(
            Schedule.start_time <= day_end,
            Schedule.end_time >= day_start,
        )

    schedules = query.order_by(Schedule.start_time).all()

    result = []
    for s in schedules:
        status = s.status
        if hasattr(status, "value"):
            status = status.value
        result.append({
            "id": s.id,
            "worker_id": s.worker_id,
            "patient_id": s.patient_id,
            "patient_name": s.patient.name if s.patient else None,
            "start_time": s.start_time.isoformat(),
            "end_time": s.end_time.isoformat(),
            "status": status,
        })

    return result

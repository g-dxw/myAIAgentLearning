from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.reminder import Reminder


def _reminder_to_dict(r: Reminder) -> dict:
    return {
        "id": r.id,
        "worker_id": r.worker_id,
        "schedule_id": r.schedule_id,
        "type": r.type,
        "message": r.message,
        "is_read": r.is_read,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


def list_reminders(db: Session, worker_id: int, page: int = 1, page_size: int = 20):
    """护工端查询自己的提醒列表"""
    query = db.query(Reminder).filter(Reminder.worker_id == worker_id)
    total = query.count()
    reminders = query.order_by(Reminder.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {"data": [_reminder_to_dict(r) for r in reminders], "total": total}


def mark_read(db: Session, reminder_id: int, worker_id: int):
    """标记提醒为已读"""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.worker_id == worker_id,
    ).first()

    if not reminder:
        raise HTTPException(status_code=404, detail="提醒不存在")

    reminder.is_read = True
    db.commit()

    return {"read": True}

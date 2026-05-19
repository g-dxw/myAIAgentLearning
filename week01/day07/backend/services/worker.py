"""护工管理业务逻辑：CRUD + 账号自动创建 + 状态联动排班"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.user import User, UserRole
from models.worker import Worker, WorkerStatus
from models.schedule import Schedule, ScheduleStatus
from schemas.worker import WorkerCreate, WorkerUpdate, WorkerStatusUpdate
from utils.security import hash_password


def _to_out(worker: Worker) -> dict:
    """Worker ORM 对象 → 前端响应 dict"""
    status = worker.status
    if hasattr(status, "value"):
        status = status.value
    return {
        "id": worker.id,
        "user_id": worker.user_id,
        "name": worker.name,
        "phone": worker.phone,
        "id_card": worker.id_card,
        "avatar": worker.avatar,
        "status": status,
        "created_at": worker.created_at.isoformat() if worker.created_at else "",
    }


def list_workers(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    name: str | None = None,
    status: str | None = None,
):
    """分页查询护工列表，支持按姓名模糊搜索和状态筛选"""
    query = db.query(Worker).filter(Worker.status != WorkerStatus.DELETED)

    if name:
        query = query.filter(Worker.name.contains(name))
    if status:
        query = query.filter(Worker.status == status)

    total = query.count()
    workers = query.offset((page - 1) * page_size).limit(page_size).all()

    return {"data": [_to_out(w) for w in workers], "total": total}


def create_worker(db: Session, data: WorkerCreate):
    """新增护工：在同一事务中创建 User（手机号为用户名，身份证后6位为密码）和 Worker 记录"""
    existing = db.query(User).filter(User.username == data.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="该手机号已注册")

    password = data.id_card[-6:]
    user = User(
        username=data.phone,
        password_hash=hash_password(password),
        role=UserRole.WORKER,
    )
    db.add(user)
    db.flush()

    worker = Worker(
        user_id=user.id,
        name=data.name,
        phone=data.phone,
        id_card=data.id_card,
        avatar=data.avatar,
        status=WorkerStatus.ACTIVE,
    )
    db.add(worker)
    db.flush()
    db.commit()
    db.refresh(worker)

    return _to_out(worker)


def get_worker(db: Session, worker_id: int):
    """查询单个护工详情"""
    worker = db.query(Worker).filter(
        Worker.id == worker_id,
        Worker.status != WorkerStatus.DELETED,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="护工不存在")
    return _to_out(worker)


def update_worker(db: Session, worker_id: int, data: WorkerUpdate):
    """编辑护工基础信息（姓名、手机号、头像）"""
    worker = db.query(Worker).filter(
        Worker.id == worker_id,
        Worker.status != WorkerStatus.DELETED,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="护工不存在")

    worker.name = data.name
    worker.phone = data.phone
    if data.avatar is not None:
        worker.avatar = data.avatar
    db.commit()
    db.refresh(worker)
    return _to_out(worker)


def update_status(db: Session, worker_id: int, data: WorkerStatusUpdate):
    """启用/停用护工：停用时自动取消该护工所有待执行排班"""
    worker = db.query(Worker).filter(
        Worker.id == worker_id,
        Worker.status != WorkerStatus.DELETED,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="护工不存在")

    worker.status = WorkerStatus(data.status)
    db.flush()

    if data.status == "inactive":
        schedules = db.query(Schedule).filter(
            Schedule.worker_id == worker_id,
            Schedule.status == ScheduleStatus.ASSIGNED,
        ).all()
        for s in schedules:
            s.status = ScheduleStatus.CANCELLED

    db.commit()
    db.refresh(worker)
    return _to_out(worker)


def delete_worker(db: Session, worker_id: int):
    """删除护工：有历史关联数据时逻辑删除（标记为deleted），无关联数据时物理删除"""
    worker = db.query(Worker).filter(
        Worker.id == worker_id,
        Worker.status != WorkerStatus.DELETED,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="护工不存在")

    from models.care_record import CareRecord

    has_schedule = db.query(Schedule).filter(Schedule.worker_id == worker_id).first() is not None
    has_record = db.query(CareRecord).filter(CareRecord.worker_id == worker_id).first() is not None
    has_records = has_schedule or has_record
    if has_records:
        worker.status = WorkerStatus.DELETED
    else:
        db.query(User).filter(User.id == worker.user_id).delete()
        db.delete(worker)

    db.commit()
    return {"deleted": True}


def reset_password(db: Session, worker_id: int):
    """重置护工密码为身份证后6位"""
    worker = db.query(Worker).filter(
        Worker.id == worker_id,
        Worker.status != WorkerStatus.DELETED,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="护工不存在")

    new_password = worker.id_card[-6:]
    user = db.query(User).filter(User.id == worker.user_id).first()
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"password": new_password}

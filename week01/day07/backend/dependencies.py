from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

# 由 main.py 在 startup 时注入
_db_session_factory = None


def init_db(factory):
    global _db_session_factory
    _db_session_factory = factory


def get_db():
    if _db_session_factory is None:
        raise RuntimeError("数据库未初始化")
    db = _db_session_factory()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: str = Header(..., alias="Authorization"),
    db: Session = Depends(get_db),
):
    from models.user import User
    from utils.security import decode_token

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的认证格式")
    token = authorization[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def get_current_admin(user=Depends(get_current_user)):
    from models.user import UserRole

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def get_current_worker(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from models.user import UserRole
    from models.worker import Worker

    if user.role != UserRole.WORKER:
        raise HTTPException(status_code=403, detail="需要护工权限")
    worker = db.query(Worker).filter(Worker.user_id == user.id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="护工信息不存在")
    return worker

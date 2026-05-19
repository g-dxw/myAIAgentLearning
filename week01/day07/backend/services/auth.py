from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.user import User
from models.worker import Worker
from schemas.auth import LoginResponse, UserOut
from utils.security import verify_password, create_access_token


def login(db: Session, username: str, password: str) -> LoginResponse:
    """用户登录：校验用户名密码，生成 JWT token 返回用户信息"""
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id, user.role)

    user_out = UserOut(id=user.id, username=user.username, role=user.role)

    if user.role == "worker":
        worker = db.query(Worker).filter(Worker.user_id == user.id).first()
        if worker and worker.status.value == "active":
            user_out.name = worker.name
            user_out.avatar = worker.avatar

    return LoginResponse(token=token, user=user_out)


def get_me(db: Session, user: User) -> UserOut:
    """获取当前登录用户信息"""
    user_out = UserOut(id=user.id, username=user.username, role=user.role)

    if user.role == "worker":
        worker = db.query(Worker).filter(Worker.user_id == user.id).first()
        if worker:
            user_out.name = worker.name
            user_out.avatar = worker.avatar

    return user_out

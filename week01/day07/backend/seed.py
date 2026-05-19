"""种子数据：预置管理员账号"""
from models.user import User, UserRole
from utils.security import hash_password


def seed_admin(db):
    existing = db.query(User).filter(User.username == "admin").first()
    if existing:
        return
    admin = User(
        username="admin",
        password_hash=hash_password("fd7105203322"),
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.commit()

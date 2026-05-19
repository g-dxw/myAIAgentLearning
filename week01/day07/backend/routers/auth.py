from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from schemas.auth import LoginRequest, LoginResponse, UserOut
from schemas.common import ApiResponse
from services.auth import login, get_me
from dependencies import get_db, get_current_user
from utils.response import ok

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=ApiResponse[LoginResponse])
def login_api(req: LoginRequest, db: Session = Depends(get_db)):
    result = login(db, req.username, req.password)
    return ok(result)


@router.get("/me", response_model=ApiResponse[UserOut])
def me_api(user=Depends(get_current_user), db: Session = Depends(get_db)):
    result = get_me(db, user)
    return ok(result)

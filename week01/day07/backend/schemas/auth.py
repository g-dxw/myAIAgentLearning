from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    token: str
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    name: str | None = None
    avatar: str | None = None

    model_config = {"from_attributes": True}

from pydantic import BaseModel, Field


class WorkerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=1, max_length=20)
    id_card: str = Field(..., min_length=1, max_length=18)
    avatar: str | None = None


class WorkerUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=1, max_length=20)
    avatar: str | None = None


class WorkerStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(active|inactive)$")


class WorkerOut(BaseModel):
    id: int
    user_id: int
    name: str
    phone: str
    id_card: str
    avatar: str | None = None
    status: str
    created_at: str

    model_config = {"from_attributes": True}

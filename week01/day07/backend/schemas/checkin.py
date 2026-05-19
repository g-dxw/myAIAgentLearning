from pydantic import BaseModel, Field


class CheckinStart(BaseModel):
    schedule_id: int = Field(..., ge=1)


class CheckinSubmit(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class CheckinMakeup(BaseModel):
    patient_id: int = Field(..., ge=1)
    start_time: str  # ISO 8601
    end_time: str    # ISO 8601
    content: str = Field(..., min_length=1, max_length=2000)


class CheckinOut(BaseModel):
    id: int
    worker_id: int
    patient_id: int
    schedule_id: int | None = None
    start_time: str
    end_time: str | None = None
    content: str | None = None
    status: str
    is_makeup: bool
    created_at: str
    patient_name: str | None = None
    worker_name: str | None = None

    model_config = {"from_attributes": True}

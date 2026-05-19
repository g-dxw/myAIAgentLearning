from pydantic import BaseModel, Field


class ScheduleCreate(BaseModel):
    worker_id: int = Field(..., ge=1)
    patient_id: int = Field(..., ge=1)
    start_time: str  # ISO 8601
    end_time: str    # ISO 8601


class ScheduleUpdate(BaseModel):
    worker_id: int = Field(..., ge=1)
    patient_id: int = Field(..., ge=1)
    start_time: str
    end_time: str


class ScheduleOut(BaseModel):
    id: int
    worker_id: int
    patient_id: int
    start_time: str
    end_time: str
    status: str
    worker_name: str | None = None
    patient_name: str | None = None

    model_config = {"from_attributes": True}


class ScheduleLogOut(BaseModel):
    id: int
    schedule_id: int
    action: str
    operator_id: int
    original_worker_id: int | None = None
    new_worker_id: int | None = None
    remark: str | None = None
    created_at: str

    model_config = {"from_attributes": True}

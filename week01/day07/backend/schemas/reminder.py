from pydantic import BaseModel


class ReminderOut(BaseModel):
    id: int
    worker_id: int
    schedule_id: int
    type: str
    message: str
    is_read: bool
    created_at: str

    model_config = {"from_attributes": True}

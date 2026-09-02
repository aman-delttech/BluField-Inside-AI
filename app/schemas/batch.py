from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BatchRunRequest(BaseModel):
    limit: int | None = None
    force: bool = False


class BatchJobStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # built directly from a BatchJob dataclass

    id: str
    status: str
    total: int
    processed: int
    skipped: int
    failed: int
    current_account: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class BatchJobList(BaseModel):
    jobs: list[BatchJobStatus]

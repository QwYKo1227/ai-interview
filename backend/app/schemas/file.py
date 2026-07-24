from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class StoredFileResponse(BaseModel):
    id: UUID
    original_filename: str
    content_type: str | None = None
    size: int
    category: str
    resource_type: str | None = None
    resource_id: UUID | None = None
    created_at: datetime

    @computed_field
    @property
    def download_url(self) -> str:
        return f"/api/files/{self.id}"

    model_config = ConfigDict(from_attributes=True)


class PublicFileTokenRequest(BaseModel):
    ttl_seconds: int = Field(default=900, ge=60, le=86400)


class PublicFileTokenResponse(BaseModel):
    token: str
    url: str
    expires_at: datetime

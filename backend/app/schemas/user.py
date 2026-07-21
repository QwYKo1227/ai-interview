from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Optional
from uuid import UUID
from app.models.models import UserRole

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: Optional[UserRole] = UserRole.HR

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    tenant_code: str = Field(min_length=1, max_length=64)
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[UserRole] = None

class UserUpdateMe(BaseModel):
    full_name: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UserResponse(UserBase):
    id: UUID
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: UUID
    tenant_id: UUID
    role: str

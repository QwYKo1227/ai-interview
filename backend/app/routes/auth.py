from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.config.database import get_unscoped_db
from app.config.tenant_session import tenant_authentication_session
from app.models.models import User, UserRole
from app.models.tenant_models import Tenant, TenantDomain, TenantStatus
from app.schemas.tenant import TenantSummary
from app.schemas.user import Token, UserResponse, CurrentUserResponse, UserLogin, UserCreate, UserUpdateMe, ChangePasswordRequest
from app.core.security import verify_password, create_access_token, check_roles, get_password_hash
from app.core.tenant_dependencies import get_current_user_dep, get_tenant_context, get_tenant_db
from app.core.tenant_context import TenantContext
from app.core.rate_limit import enforce_rate_limit
from app.core.host_policy import resolve_request_origin
from sqlalchemy.exc import IntegrityError
from datetime import timedelta
from typing import List
import re


LOGIN_ERROR = "公司、账号或密码错误"
DUMMY_PASSWORD_HASH = "$2b$12$b2EfUH39fOFct42kb2HHv.Uq3Dml9R3urPsHrAu.F5E87KLizmY5C"

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

# Reuse the dependency from security.py to avoid duplication and mismatch
get_current_user = get_current_user_dep

def validate_password_strength(password: str) -> None:
    """
    验证密码强度
    - 至少8个字符
    - 必须包含字母
    - 必须包含数字
    """
    if len(password.encode("utf-8")) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码长度至少8位"
        )
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码最多为 72 个 UTF-8 字节",
        )
    if not re.search(r'[A-Za-z]', password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码必须包含字母"
        )
    if not re.search(r'\d', password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码必须包含数字"
        )

def _login_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=LOGIN_ERROR,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authenticate_tenant_user(
    db: Session, *, tenant_code: str, email: str, password: str
) -> tuple[Tenant, User]:
    tenant_code = tenant_code.strip().lower()
    email = email.strip().lower()
    tenant = (
        db.query(Tenant)
        .filter(Tenant.code == tenant_code)
        .first()
    )
    if tenant is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        raise _login_error()
    with tenant_authentication_session(tenant.id) as tenant_db:
        user = (
            tenant_db.query(User)
            .filter(User.tenant_id == tenant.id, User.email == email)
            .first()
        )
        password_hash = (
            user.hashed_password
            if user is not None and user.is_active
            else DUMMY_PASSWORD_HASH
        )
        password_matches = verify_password(password, password_hash)
        if (
            user is None
            or not user.is_active
            or not password_matches
        ):
            raise _login_error()

    if tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access is disabled",
        )

    return tenant, user


def _token_for_user(tenant: Tenant, user: User) -> Token:
    access_token_expires = timedelta(minutes=60 * 24 * 30)  # 30 days
    access_token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        role=user.role.value,
        credential_version=user.credential_version,
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")


def _enforce_login_host(db: Session, request: Request, tenant: Tenant) -> None:
    """A registered company host may authenticate only its mapped tenant."""
    domain = resolve_request_origin(db, request).domain
    if domain is not None and domain.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant does not match request domain",
        )


@router.get("/tenants", response_model=List[TenantSummary])
def list_login_tenants(
    request: Request,
    db: Session = Depends(get_unscoped_db),
):
    resolve_request_origin(db, request)
    rows = (
        db.query(Tenant, TenantDomain.domain)
        .outerjoin(
            TenantDomain,
            (TenantDomain.tenant_id == Tenant.id) & TenantDomain.is_primary,
        )
        .filter(Tenant.status == TenantStatus.ACTIVE)
        .order_by(Tenant.code)
        .all()
    )
    return [
        TenantSummary(
            id=tenant.id,
            code=tenant.code,
            name=tenant.name,
            logo_url=tenant.logo_url,
            primary_domain=primary_domain,
        )
        for tenant, primary_domain in rows
    ]


@router.post("/token", response_model=Token, deprecated=True)
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    tenant_code: str = Form(...),
    db: Session = Depends(get_unscoped_db),
):
    enforce_rate_limit(
        request,
        "login",
        tenant_code.strip().lower(),
        form_data.username.strip().lower(),
    )
    tenant, user = _authenticate_tenant_user(
        db,
        tenant_code=tenant_code,
        email=form_data.username,
        password=form_data.password,
    )
    _enforce_login_host(db, request, tenant)
    return _token_for_user(tenant, user)

@router.post("/login", response_model=Token)
def login(
    login_data: UserLogin,
    request: Request,
    db: Session = Depends(get_unscoped_db),
):
    enforce_rate_limit(
        request,
        "login",
        login_data.tenant_code.strip().lower(),
        str(login_data.email).strip().lower(),
    )
    tenant, user = _authenticate_tenant_user(
        db,
        tenant_code=login_data.tenant_code,
        email=str(login_data.email),
        password=login_data.password,
    )
    _enforce_login_host(db, request, tenant)
    return _token_for_user(tenant, user)

@router.get("/me", response_model=CurrentUserResponse)
def read_users_me(
    current_user: User = Depends(get_current_user),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_unscoped_db),
):
    tenant, primary_domain = (
        db.query(Tenant, TenantDomain.domain)
        .outerjoin(
            TenantDomain,
            (TenantDomain.tenant_id == Tenant.id) & TenantDomain.is_primary,
        )
        .filter(Tenant.id == tenant_context.tenant_id)
        .one()
    )
    return CurrentUserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active,
        tenant=TenantSummary(
            id=tenant.id,
            code=tenant.code,
            name=tenant.name,
            logo_url=tenant.logo_url,
            primary_domain=primary_domain,
        ),
    )

@router.put("/me", response_model=UserResponse)
def update_users_me(
    payload: UserUpdateMe,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    data = payload.dict(exclude_unset=True)
    if "full_name" in data:
        current_user.full_name = data["full_name"]
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user

@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码错误")
    # 验证新密码强度
    validate_password_strength(payload.new_password)
    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.credential_version += 1
    db.add(current_user)
    db.commit()
    return {"success": True}

# Admin routes for user management
@router.get("/users", response_model=List[UserResponse])
def get_users(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_tenant_db),
    current_user: UserResponse = Depends(check_roles([UserRole.ADMIN]))
):
    return db.query(User).offset(skip).limit(limit).all()

def _is_email_unique_conflict(error: IntegrityError) -> bool:
    original = error.orig
    sqlstate = getattr(original, "sqlstate", getattr(original, "pgcode", None))
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return (
        sqlstate == "23505"
        and constraint_name == "uq_users_tenant_lower_email"
    )


@router.post("/users", response_model=UserResponse)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_tenant_db),
    current_user: UserResponse = Depends(check_roles([UserRole.ADMIN]))
):
    normalized_email = str(user.email).strip().lower()
    db_user = db.query(User).filter(User.email == normalized_email).first()
    if db_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    # 验证密码强度
    validate_password_strength(user.password)

    hashed_password = get_password_hash(user.password)
    new_user = User(
        email=normalized_email,
        hashed_password=hashed_password,
        full_name=user.full_name,
        role=user.role
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if _is_email_unique_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from None
        raise
    db.refresh(new_user)
    return new_user

@router.get("/interviewers", response_model=List[UserResponse])
def get_interviewers(db: Session = Depends(get_tenant_db)):
    # Helper to get all interviewers (HR and Interviewer roles can be assigned)
    # Accessible by authenticated users to assign to interviews
    return db.query(User).filter(User.role.in_([UserRole.HR, UserRole.INTERVIEWER, UserRole.ADMIN])).all()

@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    user_update: UserUpdateMe,
    db: Session = Depends(get_tenant_db),
    current_user: UserResponse = Depends(check_roles([UserRole.ADMIN]))
):
    """更新用户信息"""
    from uuid import UUID
    try:
        uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID")

    db_user = db.query(User).filter(User.id == uuid).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    data = user_update.dict(exclude_unset=True)
    if "full_name" in data:
        db_user.full_name = data["full_name"]

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.put("/users/{user_id}/role")
def update_user_role(
    user_id: str,
    role: str,
    db: Session = Depends(get_tenant_db),
    current_user: UserResponse = Depends(check_roles([UserRole.ADMIN]))
):
    """更新用户角色"""
    from uuid import UUID
    try:
        uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID")

    try:
        new_role = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的角色")

    db_user = db.query(User).filter(User.id == uuid).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止管理员修改自己的角色
    if db_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")

    db_user.role = new_role
    db.add(db_user)
    db.commit()
    return {"success": True, "message": "角色更新成功"}

@router.put("/users/{user_id}/status")
def toggle_user_status(
    user_id: str,
    db: Session = Depends(get_tenant_db),
    current_user: UserResponse = Depends(check_roles([UserRole.ADMIN]))
):
    """切换用户状态（启用/禁用）"""
    from uuid import UUID
    try:
        uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID")

    db_user = db.query(User).filter(User.id == uuid).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止禁用自己
    if db_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账户")

    db_user.is_active = not db_user.is_active
    db.add(db_user)
    db.commit()
    return {"success": True, "is_active": db_user.is_active}

@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(get_tenant_db),
    current_user: UserResponse = Depends(check_roles([UserRole.ADMIN]))
):
    """删除用户"""
    from uuid import UUID
    try:
        uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID")

    db_user = db.query(User).filter(User.id == uuid).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止删除自己
    if db_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")

    db.delete(db_user)
    db.commit()
    return {"success": True, "message": "用户已删除"}

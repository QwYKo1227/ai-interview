# 多租户 SaaS 改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单租户 AI 面试系统改造成一套前后端和一个 PostgreSQL 数据库服务多家公司的 SaaS，并通过 `tenant_id`、应用层会话过滤和 PostgreSQL RLS 阻止跨租户访问。

**Architecture:** 新增全局租户、域名、平台管理员和公开访问令牌模型；所有业务表增加 `tenant_id`。登录后 JWT 携带用户 UUID 与租户 UUID，后端为每个事务设置 `app.current_tenant_id`，租户 Session 自动过滤和填充租户字段，PostgreSQL RLS 作为最后防线。现有数据统一迁移到 `careray`，新增公司通过平台开通事务完成。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、PostgreSQL 15、python-jose、React 19、TypeScript、Ant Design、Axios、Vitest、Docker Compose。

## Global Constraints

- 所有设计与部署文档使用中文。
- 普通业务请求不得从请求体、查询参数或可修改请求头读取可信 `tenant_id`。
- 用户账号只属于一个租户，不实现登录后的跨公司切换。
- 当前全部业务数据归入代码为 `careray` 的默认租户。
- 跨租户资源与不存在资源统一返回 404。
- `app_runtime` 数据库角色不得拥有 `BYPASSRLS`、超级用户或表所有者权限。
- 公开 token、JWT、SMTP 授权码、LLM API Key 和密码不得写入日志。
- 所有后台任务必须显式传递 `tenant_id` 和资源 ID，不得直接创建裸 `SessionLocal()`。
- 文件保存到 `uploads/{tenant_id}/...`，不再整体公开挂载 `/uploads`。
- 每项业务改造遵循测试先行；每个任务完成后运行该任务测试与完整后端测试。
- 生产迁移期间禁止执行 `docker compose down -v`。

---

### Task 1: 建立租户与平台全局模型

**Files:**
- Create: `backend/app/models/tenant_models.py`
- Create: `backend/app/schemas/tenant.py`
- Create: `backend/tests/test_tenant_models.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces: `TenantStatus`、`Tenant`、`TenantDomain`、`PlatformUser`、`PlatformAuditLog`、`PublicAccessToken`。
- Produces: `TenantScopedMixin.tenant_id`，供所有业务模型继承。
- Produces: `TenantSummary`、`TenantCreate`、`TenantResponse`。

- [ ] **Step 1: 写租户模型失败测试**

```python
def test_tenant_code_is_unique(db):
    db.add(Tenant(code="careray", name="CareRay", status=TenantStatus.ACTIVE))
    db.commit()
    db.add(Tenant(code="careray", name="Duplicate", status=TenantStatus.ACTIVE))
    with pytest.raises(IntegrityError):
        db.commit()


def test_tenant_domain_is_globally_unique(db, tenant_a, tenant_b):
    db.add(TenantDomain(tenant_id=tenant_a.id, domain="interview.careray.com", is_primary=True))
    db.commit()
    db.add(TenantDomain(tenant_id=tenant_b.id, domain="interview.careray.com", is_primary=True))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: 运行测试并确认因模型不存在而失败**

Run: `cd backend && pytest tests/test_tenant_models.py -v`

Expected: collection error mentioning `Tenant` or `app.models.tenant_models` cannot be imported.

- [ ] **Step 3: 实现全局模型与租户混入类**

```python
class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    status = Column(Enum(TenantStatus), nullable=False, default=TenantStatus.ACTIVE)
    logo_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TenantScopedMixin:
    @declared_attr
    def tenant_id(cls):
        return Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
```

实现 `TenantDomain` 的全局唯一 `domain`、每租户单一主域名约束；实现独立平台用户、平台审计日志以及只保存 SHA-256 哈希的公开访问令牌模型。

- [ ] **Step 4: 更新 SQLite 测试表与租户 fixtures**

```python
@pytest.fixture
def tenant_a(db):
    tenant = Tenant(code="careray", name="CareRay", status=TenantStatus.ACTIVE)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def tenant_b(db):
    tenant = Tenant(code="photonthix", name="Photonthix", status=TenantStatus.ACTIVE)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant
```

- [ ] **Step 5: 运行测试并提交**

Run: `cd backend && pytest tests/test_tenant_models.py -v`

Expected: all tests pass.

```bash
git add backend/app/models backend/app/schemas/tenant.py backend/tests
git commit -m "feat: add tenant platform models"
```

---

### Task 2: 为所有业务模型增加租户字段并迁移现有数据

**Files:**
- Create: `backend/alembic/versions/l1m2n3o4p5q6_add_multi_tenant_foundation.py`
- Create: `backend/tests/test_tenant_model_coverage.py`
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/models/workflow_models.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `TenantScopedMixin`、`Tenant`。
- Produces: 所有业务模型统一拥有 `tenant_id: UUID`。
- Produces: 默认租户常量 `DEFAULT_TENANT_CODE = "careray"`。

- [ ] **Step 1: 写模型覆盖失败测试**

```python
TENANT_MODELS = [
    User, Position, QuestionBank, Resume, DepartmentReview, Interview,
    InterviewPanel, Offer, OfferTemplate, CodingTest, CodingSubmission,
    SystemConfig, Workflow, WorkflowNode, WorkflowEdge,
    WorkflowExecution, WorkflowNodeExecution,
]


@pytest.mark.parametrize("model", TENANT_MODELS)
def test_every_business_model_has_tenant_id(model):
    assert "tenant_id" in model.__table__.columns
```

- [ ] **Step 2: 运行覆盖测试并确认失败**

Run: `cd backend && pytest tests/test_tenant_model_coverage.py -v`

Expected: failures list every model missing `tenant_id`.

- [ ] **Step 3: 让业务模型继承租户混入类**

```python
class User(TenantScopedMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
    )
```

对 Task 2 列出的全部业务模型应用同一混入类。移除 `User.email` 的 `unique=True`。将 `SystemConfig` 的全局单例约束替换为 `UniqueConstraint("tenant_id", name="uq_system_configs_tenant")`。

- [ ] **Step 4: 编写兼容性 Alembic 迁移**

迁移必须按以下顺序执行：创建全局表；插入默认 `careray`；为全部业务表添加允许为空的 `tenant_id`；将现有行更新为默认租户；创建租户前缀索引；暂不启用 RLS。

```python
TENANT_TABLES = [
    "users", "positions", "question_banks", "resumes", "department_reviews",
    "interviews", "interview_panels", "offers", "offer_templates",
    "coding_tests", "coding_submissions", "system_configs", "workflows",
    "workflow_nodes", "workflow_edges", "workflow_executions",
    "workflow_node_executions",
]

default_tenant_id = str(uuid.uuid4())
op.execute(
    sa.text("INSERT INTO tenants (id, code, name, status, created_at, updated_at) "
            "VALUES (:id, 'careray', 'CareRay', 'ACTIVE', now(), now())")
    .bindparams(id=default_tenant_id)
)
for table in TENANT_TABLES:
    op.add_column(table, sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(sa.text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE tenant_id IS NULL")
               .bindparams(tenant_id=default_tenant_id))
```

迁移的 downgrade 只在所有租户仍为 `careray` 时允许执行；检测到其他租户后主动抛出错误，避免误删租户数据。

- [ ] **Step 5: 验证模型、迁移和完整测试**

Run: `cd backend && pytest tests/test_tenant_model_coverage.py -v && pytest`

Expected: coverage tests and existing suite pass.

```bash
git add backend/app/models backend/alembic/versions backend/tests
git commit -m "feat: add tenant ownership to business models"
```

---

### Task 3: 建立可信租户上下文和租户数据库会话

**Files:**
- Create: `backend/app/core/tenant_context.py`
- Create: `backend/app/config/tenant_session.py`
- Create: `backend/tests/test_tenant_session.py`
- Modify: `backend/app/config/database.py`

**Interfaces:**
- Produces: `TenantContext(tenant_id: UUID, tenant_code: str, source: str)`。
- Produces: `set_tenant_context(db: Session, tenant_id: UUID) -> None`。
- Produces: `tenant_session(tenant_id: UUID) -> ContextManager[Session]`。
- Produces: `TenantSession`，自动过滤读取并填充新增对象的 `tenant_id`。
- Produces: `get_unscoped_db()`，仅供全局表查询。

- [ ] **Step 1: 写租户 Session 失败测试**

```python
def test_tenant_session_only_reads_own_rows(tenant_session_factory, tenant_a, tenant_b):
    with tenant_session_factory(tenant_a.id) as db:
        db.add(Position(title="A", description="A"))
        db.commit()
    with tenant_session_factory(tenant_b.id) as db:
        db.add(Position(title="B", description="B"))
        db.commit()
    with tenant_session_factory(tenant_a.id) as db:
        assert [p.title for p in db.query(Position).all()] == ["A"]


def test_new_row_gets_tenant_id_automatically(tenant_session_factory, tenant_a):
    with tenant_session_factory(tenant_a.id) as db:
        position = Position(title="A", description="A")
        db.add(position)
        db.commit()
        assert position.tenant_id == tenant_a.id
```

- [ ] **Step 2: 运行测试并确认缺少租户 Session**

Run: `cd backend && pytest tests/test_tenant_session.py -v`

Expected: import error for `TenantSession` or `tenant_session`.

- [ ] **Step 3: 实现 TenantSession 事件和事务级 RLS 设置**

```python
class TenantSession(Session):
    pass


@event.listens_for(TenantSession, "do_orm_execute")
def add_tenant_filter(execute_state):
    tenant_id = execute_state.session.info.get("tenant_id")
    if tenant_id and execute_state.is_select:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantScopedMixin,
                lambda model: model.tenant_id == tenant_id,
                include_aliases=True,
            )
        )


@event.listens_for(TenantSession, "before_flush")
def fill_tenant_id(session, _flush_context, _instances):
    tenant_id = session.info.get("tenant_id")
    for obj in session.new:
        if isinstance(obj, TenantScopedMixin):
            if obj.tenant_id not in (None, tenant_id):
                raise ValueError("tenant_id does not match session tenant")
            obj.tenant_id = tenant_id
```

`set_tenant_context` 在 PostgreSQL 事务内执行：

```python
db.execute(
    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
    {"tenant_id": str(tenant_id)},
)
```

SQLite 测试跳过 `set_config`，但保留 ORM 会话过滤。

- [ ] **Step 4: 验证连接池复用不会残留租户**

```python
def test_session_factory_requires_explicit_tenant(tenant_session_factory, tenant_a, tenant_b):
    with tenant_session_factory(tenant_a.id) as first:
        assert first.info["tenant_id"] == tenant_a.id
    with tenant_session_factory(tenant_b.id) as second:
        assert second.info["tenant_id"] == tenant_b.id
```

- [ ] **Step 5: 运行测试并提交**

Run: `cd backend && pytest tests/test_tenant_session.py -v && pytest`

Expected: all tests pass.

```bash
git add backend/app/core/tenant_context.py backend/app/config backend/tests
git commit -m "feat: add tenant scoped database sessions"
```

---

### Task 4: 改造公司识别、登录和 JWT

**Files:**
- Create: `backend/app/core/tenant_dependencies.py`
- Create: `backend/tests/test_tenant_auth.py`
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/app/routes/auth.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces: `GET /api/auth/tenants`。
- Produces: `POST /api/auth/login`，接收 `tenant_code`、`email`、`password`。
- Produces: JWT claims `sub=<user UUID>`、`tenant_id`、`role`。
- Produces: `get_tenant_context()` 和 `get_tenant_db()` FastAPI dependencies。

- [ ] **Step 1: 写同邮箱跨租户登录失败测试**

```python
def test_login_selects_user_by_tenant(client, tenant_a, tenant_b, create_user):
    user_a = create_user(tenant_a.id, "same@example.com", "Password123")
    create_user(tenant_b.id, "same@example.com", "OtherPass123")
    response = client.post("/api/auth/login", json={
        "tenant_code": "careray",
        "email": "same@example.com",
        "password": "Password123",
    })
    assert response.status_code == 200
    claims = jwt.decode(response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["sub"] == str(user_a.id)
    assert claims["tenant_id"] == str(tenant_a.id)


def test_tenant_a_password_cannot_login_to_tenant_b(client, tenant_a, tenant_b, create_user):
    create_user(tenant_a.id, "same@example.com", "Password123")
    create_user(tenant_b.id, "same@example.com", "OtherPass123")
    response = client.post("/api/auth/login", json={
        "tenant_code": "photonthix",
        "email": "same@example.com",
        "password": "Password123",
    })
    assert response.status_code == 401
```

- [ ] **Step 2: 运行测试并确认旧登录接口不识别租户**

Run: `cd backend && pytest tests/test_tenant_auth.py -v`

Expected: 422 or missing `tenant_code` behavior causes assertions to fail.

- [ ] **Step 3: 扩展登录 Schema 和 JWT**

```python
class UserLogin(BaseModel):
    tenant_code: str
    email: EmailStr
    password: str


def create_access_token(*, user_id: UUID, tenant_id: UUID, role: str,
                        expires_delta: Optional[timedelta] = None) -> str:
    claims = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "exp": datetime.utcnow() + (expires_delta or timedelta(minutes=15)),
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
```

登录先通过非租户 Session 查询启用租户，再使用 `tenant_session(tenant.id)` 查询 `(tenant_id, email)` 用户。错误统一使用“公司、账号或密码错误”，不泄露公司和账号是否存在。

- [ ] **Step 4: 实现域名与 JWT 一致性校验**

```python
@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    tenant_code: str
    source: Literal["jwt", "domain", "public_token"]
```

公司专属域名存在映射时，JWT 租户与域名租户不一致返回 403；统一入口域名不执行该匹配。

- [ ] **Step 5: 更新测试 token fixtures 并运行完整测试**

测试 fixtures 统一改为：

```python
create_access_token(
    user_id=test_user.id,
    tenant_id=test_user.tenant_id,
    role=test_user.role.value,
)
```

Run: `cd backend && pytest tests/test_tenant_auth.py -v && pytest`

Expected: all tests pass.

```bash
git add backend/app/core backend/app/routes/auth.py backend/app/schemas/user.py backend/tests
git commit -m "feat: authenticate users within tenants"
```

---

### Task 5: 将受保护业务 API 切换到租户会话

**Files:**
- Create: `backend/tests/test_tenant_route_isolation.py`
- Modify: `backend/app/routes/positions.py`
- Modify: `backend/app/routes/resumes.py`
- Modify: `backend/app/routes/interviews.py`
- Modify: `backend/app/routes/question_banks.py`
- Modify: `backend/app/routes/offers.py`
- Modify: `backend/app/routes/offer_templates.py`
- Modify: `backend/app/routes/coding_tests.py`
- Modify: `backend/app/routes/dashboard.py`
- Modify: `backend/app/routes/public_review.py`
- Modify: `backend/app/routes/settings.py`
- Modify: `backend/app/routes/workflows.py`
- Modify: corresponding files under `backend/app/services/`

**Interfaces:**
- Consumes: `get_tenant_db`、`TenantSession`。
- Produces: 所有已认证业务 CRUD 自动按 JWT 租户过滤。
- Produces: 跨租户 UUID 与不存在 UUID 均返回 404。

- [ ] **Step 1: 写跨租户路由失败测试**

```python
def test_tenant_cannot_read_other_tenant_position(
    client, tenant_a_headers, tenant_b_position
):
    response = client.get(
        f"/api/positions/{tenant_b_position.id}",
        headers=tenant_a_headers,
    )
    assert response.status_code == 404


def test_dashboard_only_counts_current_tenant(
    client, tenant_a_headers, tenant_a_position, tenant_b_position
):
    response = client.get("/api/dashboard/stats", headers=tenant_a_headers)
    assert response.status_code == 200
    assert response.json()["total_positions"] == 1
```

- [ ] **Step 2: 运行测试并确认现有全局 `get_db` 导致跨租户可见**

Run: `cd backend && pytest tests/test_tenant_route_isolation.py -v`

Expected: tenant A can see or count tenant B data, so assertions fail.

- [ ] **Step 3: 批量替换受保护路由依赖**

每个已认证路由使用：

```python
from app.core.tenant_dependencies import get_tenant_db

def get_position_route(position_id: UUID, db: Session = Depends(get_tenant_db)):
    position = db.query(Position).filter(Position.id == position_id).first()
    if position is None:
        raise HTTPException(status_code=404, detail="职位不存在")
    return position
```

禁止在受保护路由导入 `get_unscoped_db`。创建对象时不接受 `tenant_id` Schema 字段，由 TenantSession 自动填充。

- [ ] **Step 4: 添加静态防回归测试**

```python
PROTECTED_ROUTE_FILES = [
    "positions.py", "resumes.py", "interviews.py", "question_banks.py",
    "offers.py", "offer_templates.py", "coding_tests.py", "dashboard.py",
    "settings.py", "workflows.py",
]


def test_protected_routes_do_not_import_legacy_get_db():
    route_dir = Path(__file__).parents[1] / "app" / "routes"
    for filename in PROTECTED_ROUTE_FILES:
        source = (route_dir / filename).read_text(encoding="utf-8")
        assert "from app.config.database import get_db" not in source
```

- [ ] **Step 5: 运行隔离测试、完整测试并提交**

Run: `cd backend && pytest tests/test_tenant_route_isolation.py -v && pytest`

Expected: all tests pass.

```bash
git add backend/app/routes backend/app/services backend/tests/test_tenant_route_isolation.py
git commit -m "feat: isolate business routes by tenant"
```

---

### Task 6: 租户化系统配置、AI、邮件和后台任务

**Files:**
- Create: `backend/tests/test_tenant_background_tasks.py`
- Create: `backend/tests/test_tenant_system_config.py`
- Modify: `backend/app/services/ai_service.py`
- Modify: `backend/app/services/mail_service.py`
- Modify: `backend/app/services/resume_service.py`
- Modify: `backend/app/services/interview_service.py`
- Modify: `backend/app/services/coding_test_service.py`
- Modify: `backend/app/services/coding_test_ai_service.py`
- Modify: `backend/app/utils/prompt_manager.py`
- Modify: `backend/app/routes/interviews.py`

**Interfaces:**
- Consumes: `tenant_session(tenant_id)`。
- Produces: `get_system_config(db)` 只返回当前租户配置。
- Produces: 所有后台任务签名首个参数为 `tenant_id: UUID`，随后是资源 ID。

- [ ] **Step 1: 写配置和任务失败测试**

```python
def test_each_tenant_reads_own_smtp_config(tenant_session_factory, tenant_a, tenant_b):
    with tenant_session_factory(tenant_a.id) as db:
        db.add(SystemConfig(smtp_host="smtp.a.test", mail_enabled=True))
        db.commit()
    with tenant_session_factory(tenant_b.id) as db:
        db.add(SystemConfig(smtp_host="smtp.b.test", mail_enabled=True))
        db.commit()
    with tenant_session_factory(tenant_a.id) as db:
        assert get_system_config(db).smtp_host == "smtp.a.test"


def test_resume_background_task_receives_tenant_id(mock_background_tasks, tenant_a, resume):
    enqueue_resume_parse(mock_background_tasks, tenant_a.id, resume.id)
    _func, args, _kwargs = mock_background_tasks.tasks[0]
    assert args[:2] == (tenant_a.id, resume.id)
```

- [ ] **Step 2: 运行测试并确认全局配置或旧任务签名失败**

Run: `cd backend && pytest tests/test_tenant_system_config.py tests/test_tenant_background_tasks.py -v`

Expected: configuration collision or task arguments omit tenant ID.

- [ ] **Step 3: 修改后台任务签名与会话创建**

```python
def process_resume_task(tenant_id: UUID, resume_id: UUID) -> None:
    with tenant_session(tenant_id) as db:
        resume = db.query(Resume).filter(Resume.id == resume_id).first()
        if resume is None:
            logger.warning("resume task resource not found", extra={"tenant_id": str(tenant_id)})
            return
        process_resume(db, resume)
```

相同模式应用于面试 AI、笔试 AI、邮件通知、提示词读取和工作流执行。删除这些模块中所有直接 `SessionLocal()` 调用。

- [ ] **Step 4: 添加静态扫描测试**

```python
BACKGROUND_MODULES = [
    "resume_service.py", "interview_service.py", "coding_test_service.py",
    "coding_test_ai_service.py", "ai_service.py",
]


def test_background_modules_do_not_create_raw_session():
    services = Path(__file__).parents[1] / "app" / "services"
    for filename in BACKGROUND_MODULES:
        assert "SessionLocal()" not in (services / filename).read_text(encoding="utf-8")
```

- [ ] **Step 5: 运行测试并提交**

Run: `cd backend && pytest tests/test_tenant_system_config.py tests/test_tenant_background_tasks.py -v && pytest`

Expected: all tests pass.

```bash
git add backend/app/services backend/app/utils/prompt_manager.py backend/app/routes/interviews.py backend/tests
git commit -m "feat: scope configuration and jobs to tenants"
```

---

### Task 7: 统一公开访问令牌和公开业务路由

**Files:**
- Create: `backend/app/services/public_token_service.py`
- Create: `backend/tests/test_public_token_tenant_isolation.py`
- Modify: `backend/app/routes/offers.py`
- Modify: `backend/app/routes/coding_tests.py`
- Modify: `backend/app/routes/public_review.py`
- Modify: `backend/app/routes/positions.py`
- Modify: `backend/app/services/offer_service.py`
- Modify: `backend/app/services/coding_test_service.py`

**Interfaces:**
- Produces: `issue_public_token(db, tenant_id, resource_type, resource_id, expires_at) -> str`。
- Produces: `resolve_public_token(db, raw_token, resource_type) -> TenantContextAndResource`。
- Produces: 公开职位通过域名或 URL 中的 `tenant_code` 建立只读租户上下文。

- [ ] **Step 1: 写公开 token 跨租户失败测试**

```python
def test_public_token_resolves_exact_tenant(db, tenant_a_offer):
    raw = issue_public_token(
        db,
        tenant_id=tenant_a_offer.tenant_id,
        resource_type="offer",
        resource_id=tenant_a_offer.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    resolved = resolve_public_token(db, raw, "offer")
    assert resolved.tenant_id == tenant_a_offer.tenant_id
    assert resolved.resource_id == tenant_a_offer.id


def test_database_never_stores_raw_public_token(db, tenant_a_offer):
    raw = issue_public_token(
        db,
        tenant_id=tenant_a_offer.tenant_id,
        resource_type="offer",
        resource_id=tenant_a_offer.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    assert db.query(PublicAccessToken).filter(PublicAccessToken.token_hash == raw).first() is None
```

- [ ] **Step 2: 运行测试并确认服务不存在**

Run: `cd backend && pytest tests/test_public_token_tenant_isolation.py -v`

Expected: import error for `public_token_service`.

- [ ] **Step 3: 实现 token 哈希与常量时间比较**

```python
def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_public_token(db, tenant_id, resource_type, resource_id, expires_at):
    raw_token = secrets.token_urlsafe(32)
    db.add(PublicAccessToken(
        token_hash=hash_token(raw_token),
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        expires_at=expires_at,
    ))
    db.commit()
    return raw_token
```

解析 token 后使用记录中的 `tenant_id` 创建租户 Session；无效、过期、撤销或资源不存在统一返回 404，已明确过期的链接可返回 410。

- [ ] **Step 4: 改造 Offer、笔试、评审和公开职位路由**

公开职位统一入口使用 `/api/public/{tenant_code}/positions`；公司专属域名使用 `tenant_domains`。两种租户来源同时存在且不一致时返回 403。

- [ ] **Step 5: 运行测试并提交**

Run: `cd backend && pytest tests/test_public_token_tenant_isolation.py -v && pytest`

Expected: all tests pass.

```bash
git add backend/app/services backend/app/routes backend/tests/test_public_token_tenant_isolation.py
git commit -m "feat: isolate public links by tenant"
```

---

### Task 8: 改造租户文件存储与授权下载

**Files:**
- Create: `backend/app/models/file_models.py`
- Create: `backend/app/schemas/file.py`
- Create: `backend/app/routes/files.py`
- Create: `backend/tests/test_tenant_file_storage.py`
- Create: `backend/alembic/versions/m2n3o4p5q6r7_add_tenant_files.py`
- Modify: `backend/app/utils/file_storage.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routes/resumes.py`
- Modify: `backend/app/routes/interviews.py`
- Modify: `backend/app/services/question_bank_service.py`

**Interfaces:**
- Produces: `StoredFile` 租户业务模型。
- Produces: `save_upload_file(upload_file, tenant_id, category, root=UPLOAD_ROOT) -> StoredFile`。
- Produces: `GET /api/files/{file_id}`，使用当前租户授权下载。

- [ ] **Step 1: 写路径和权限失败测试**

```python
def test_uploaded_file_is_saved_under_tenant_root(tmp_path, tenant_a, upload_file):
    stored = save_upload_file(upload_file, tenant_a.id, "resumes", root=tmp_path)
    assert Path(stored.object_key).parts[:2] == (str(tenant_a.id), "resumes")


def test_tenant_cannot_download_other_tenant_file(client, tenant_a_headers, tenant_b_file):
    response = client.get(f"/api/files/{tenant_b_file.id}", headers=tenant_a_headers)
    assert response.status_code == 404


def test_storage_rejects_path_traversal(tmp_path, tenant_a):
    with pytest.raises(ValueError):
        resolve_object_path(tmp_path, tenant_a.id, "../../secret.txt")
```

- [ ] **Step 2: 运行测试并确认旧存储没有租户路径**

Run: `cd backend && pytest tests/test_tenant_file_storage.py -v`

Expected: signature mismatch and authorization route missing.

- [ ] **Step 3: 实现 StoredFile 和安全路径解析**

```python
def resolve_object_path(root: Path, tenant_id: UUID, object_key: str) -> Path:
    tenant_root = (root / str(tenant_id)).resolve()
    candidate = (root / object_key).resolve()
    if tenant_root != candidate and tenant_root not in candidate.parents:
        raise ValueError("file path escapes tenant root")
    return candidate
```

文件名使用服务端生成 UUID；数据库保存相对 `object_key`、原始文件名、MIME 类型、大小和关联资源。

- [ ] **Step 4: 移除全局 StaticFiles 暴露**

删除：

```python
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
```

前端与 API 响应改用 `/api/files/{file_id}`。公开文件必须通过短期公开 token，不允许猜测路径访问。

- [ ] **Step 5: 运行测试并提交**

Run: `cd backend && pytest tests/test_tenant_file_storage.py -v && pytest`

Expected: all tests pass.

```bash
git add backend/app/models/file_models.py backend/app/schemas/file.py backend/app/routes/files.py backend/app/utils/file_storage.py backend/app/main.py backend/app/routes backend/app/services/question_bank_service.py backend/alembic/versions backend/tests
git commit -m "feat: secure tenant file storage"
```

---

### Task 9: 实现平台管理员和事务化租户开通

**Files:**
- Create: `backend/app/core/platform_security.py`
- Create: `backend/app/services/tenant_service.py`
- Create: `backend/app/routes/platform.py`
- Create: `backend/tests/test_tenant_onboarding.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/tenant.py`

**Interfaces:**
- Produces: `POST /api/platform/auth/login`。
- Produces: `POST /api/platform/tenants`。
- Produces: `PATCH /api/platform/tenants/{tenant_id}/status`。
- Produces: `create_tenant_with_admin(db, payload) -> Tenant`，单事务完成租户、域名、配置和首位管理员。

- [ ] **Step 1: 写开通原子性失败测试**

```python
def test_create_tenant_creates_defaults(db, platform_admin):
    tenant = create_tenant_with_admin(db, TenantOnboardingRequest(
        code="photonthix",
        name="Photonthix",
        primary_domain="interview.photonthix.com",
        admin_email="admin@photonthix.com",
        admin_password="StrongPassword123",
    ), actor_id=platform_admin.id)
    assert db.query(TenantDomain).filter_by(tenant_id=tenant.id, is_primary=True).count() == 1
    assert db.query(SystemConfig).filter_by(tenant_id=tenant.id).count() == 1
    assert db.query(User).filter_by(tenant_id=tenant.id, role=UserRole.ADMIN).count() == 1


def test_duplicate_code_rolls_back_all_rows(db, platform_admin):
    payload = make_onboarding_request(code="careray")
    create_tenant_with_admin(db, payload, actor_id=platform_admin.id)
    with pytest.raises(TenantConflictError):
        create_tenant_with_admin(db, payload, actor_id=platform_admin.id)
    assert db.query(Tenant).filter_by(code="careray").count() == 1
```

- [ ] **Step 2: 运行测试并确认服务不存在**

Run: `cd backend && pytest tests/test_tenant_onboarding.py -v`

Expected: import error for `tenant_service`.

- [ ] **Step 3: 实现独立平台认证与开通事务**

平台 JWT 使用 `token_type="platform"`，平台依赖拒绝租户 JWT。开通事务在创建租户后使用该租户 Session 创建默认配置与管理员，并写入 `PlatformAuditLog`。

```python
with db.begin():
    tenant = Tenant(code=payload.code, name=payload.name, status=TenantStatus.ACTIVE)
    db.add(tenant)
    db.flush()
    db.add(TenantDomain(tenant_id=tenant.id, domain=payload.primary_domain, is_primary=True))
    set_tenant_context(db, tenant.id)
    db.add(SystemConfig(tenant_id=tenant.id))
    db.add(User(
        tenant_id=tenant.id,
        email=payload.admin_email,
        hashed_password=get_password_hash(payload.admin_password),
        role=UserRole.ADMIN,
        is_active=True,
    ))
    db.add(PlatformAuditLog(
        actor_id=actor_id,
        action="tenant.created",
        target_tenant_id=tenant.id,
    ))
```

全流程只能使用这一条数据库事务，不调用会自行提交的服务，也不创建第二个 Session，确保任一步骤异常时全量回滚。

- [ ] **Step 4: 实现停用租户即时失效**

`get_tenant_context` 每次请求验证 `Tenant.status == ACTIVE`。停用后新登录返回 403，旧 JWT 下一次请求也返回 403；不删除任何业务数据。

- [ ] **Step 5: 运行测试并提交**

Run: `cd backend && pytest tests/test_tenant_onboarding.py -v && pytest`

Expected: all tests pass.

```bash
git add backend/app/core/platform_security.py backend/app/services/tenant_service.py backend/app/routes/platform.py backend/app/main.py backend/app/schemas/tenant.py backend/tests
git commit -m "feat: add platform tenant onboarding"
```

---

### Task 10: 改造前端公司选择和租户身份显示

**Files:**
- Create: `frontend/src/types/tenant.ts`
- Create: `frontend/src/utils/tenantRouting.ts`
- Create: `frontend/src/pages/Login/Login.test.tsx`
- Create: `frontend/src/utils/tenantRouting.test.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/src/pages/Login/index.tsx`
- Modify: `frontend/src/contexts/AuthContext.tsx`
- Modify: `frontend/src/components/Layout/index.tsx`
- Modify: `frontend/src/utils/request.ts`

**Interfaces:**
- Consumes: `GET /api/auth/tenants`、`POST /api/auth/login`。
- Produces: `TenantSummary` TypeScript 类型。
- Produces: `resolveTenantSelection(hostname, tenants)`。
- Produces: 登录页公司选择和页面顶部公司名称。

- [ ] **Step 1: 安装前端测试依赖并增加测试脚本**

Run: `cd frontend && npm install --save-dev vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom`

在 `package.json` 增加：

```json
"test": "vitest run"
```

- [ ] **Step 2: 写公司选择失败测试**

```tsx
it('提交公司代码、邮箱和密码', async () => {
  render(<Login />)
  await user.selectOptions(screen.getByLabelText('公司'), 'careray')
  await user.type(screen.getByLabelText('邮箱'), 'admin@example.com')
  await user.type(screen.getByLabelText('密码'), 'Password123')
  await user.click(screen.getByRole('button', { name: '登录' }))
  expect(mockPost).toHaveBeenCalledWith('/auth/login', {
    tenant_code: 'careray',
    email: 'admin@example.com',
    password: 'Password123',
  })
})


it('公司专属域名自动选择对应租户', () => {
  expect(resolveTenantSelection('interview.careray.com', tenants)?.code).toBe('careray')
})
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `cd frontend && npm test`

Expected: login lacks company field and `resolveTenantSelection` is missing.

- [ ] **Step 4: 实现登录和 AuthContext 租户状态**

```ts
export interface TenantSummary {
  id: string
  code: string
  name: string
  logo_url?: string | null
  primary_domain?: string | null
}

export interface LoginPayload {
  tenant_code: string
  email: string
  password: string
}
```

登录页启动时加载租户列表；专属域名匹配后预选并锁定公司；统一入口显示选择框。AuthContext 从 `/auth/me` 保存当前公司名称，布局顶部显示公司名称，不提供登录后切换器。

- [ ] **Step 5: 运行前端测试和构建并提交**

Run: `cd frontend && npm test && npm run build`

Expected: tests and production build pass.

```bash
git add frontend/package.json frontend/package-lock.json frontend/src
git commit -m "feat: add tenant aware login experience"
```

---

### Task 11: 启用 PostgreSQL 复合约束、运行角色和 RLS

**Files:**
- Create: `backend/alembic/versions/n3o4p5q6r7s8_enforce_tenant_rls.py`
- Create: `backend/tests/integration/test_postgres_rls.py`
- Create: `docker-compose.test.yml`
- Modify: `backend/app/models/tenant_models.py`
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/models/workflow_models.py`
- Modify: `backend/app/models/file_models.py`
- Modify: `docker-compose.prod.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: 所有租户模型和 `tenant_session`。
- Produces: `app_runtime`、`app_migration` 两类连接配置。
- Produces: 全部租户业务表 `ENABLE ROW LEVEL SECURITY` 与 `FORCE ROW LEVEL SECURITY`。
- Produces: 非空 `tenant_id`、租户组合索引和关键复合外键。

- [ ] **Step 1: 创建真实 PostgreSQL 集成测试环境**

`docker-compose.test.yml` 使用 PostgreSQL 15，宿主机端口 `55432`，数据库 `ai_interview_test`，健康检查使用 `pg_isready`。测试命令：

```powershell
docker compose -f docker-compose.test.yml up -d postgres
$env:TEST_DATABASE_URL='postgresql://app_runtime:runtime_test_password@localhost:55432/ai_interview_test'
cd backend
pytest tests/integration/test_postgres_rls.py -v
```

- [ ] **Step 2: 写 RLS 失败测试**

```python
def test_rls_blocks_known_other_tenant_uuid(pg_session_factory, tenant_a, tenant_b):
    position_b = create_position(pg_session_factory, tenant_b.id, "B")
    with pg_session_factory(tenant_a.id) as db:
        assert db.execute(
            text("SELECT id FROM positions WHERE id = :id"),
            {"id": position_b.id},
        ).first() is None


def test_rls_rejects_cross_tenant_insert(pg_session_factory, tenant_a, tenant_b):
    with pytest.raises(DBAPIError):
        with pg_session_factory(tenant_a.id) as db:
            db.execute(text(
                "INSERT INTO positions (id, tenant_id, title, description) "
                "VALUES (gen_random_uuid(), :tenant_b, 'X', 'X')"
            ), {"tenant_b": tenant_b.id})
            db.commit()
```

- [ ] **Step 3: 运行测试并确认未启用 RLS 时失败**

Run: `cd backend && pytest tests/integration/test_postgres_rls.py -v`

Expected: raw SQL can read or write another tenant, so assertions fail.

- [ ] **Step 4: 编写最终约束和 RLS 迁移**

迁移先检查每个业务表 `tenant_id IS NULL` 数量为零，再设置非空、添加组合约束，最后执行：

```python
for table in TENANT_TABLES:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'''
        CREATE POLICY {table}_tenant_isolation ON "{table}"
        USING (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
    ''')
```

`TENANT_TABLES` 必须包含 Task 2 的全部业务表以及 Task 8 新增的 `stored_files`。同时将 `TenantScopedMixin.tenant_id` 的 ORM 定义改为 `nullable=False`，保持模型与最终数据库约束一致。

生产 Compose 使用 `MIGRATION_DATABASE_URL` 执行 Alembic，再以 `DATABASE_URL` 的 `app_runtime` 启动 Uvicorn。两个账号密码分别通过环境变量提供。

- [ ] **Step 5: 运行 PostgreSQL、完整后端和前端验证并提交**

Run:

```powershell
cd backend
pytest tests/integration/test_postgres_rls.py -v
pytest
cd ..\frontend
npm test
npm run build
```

Expected: RLS integration tests, all backend tests, frontend tests and build pass.

```bash
git add backend/alembic/versions backend/tests/integration docker-compose.test.yml docker-compose.prod.yml .env.example
git commit -m "feat: enforce PostgreSQL tenant isolation"
```

---

### Task 12: 迁移演练、双租户验收、部署和回滚文档

**Files:**
- Create: `backend/scripts/verify_tenant_migration.py`
- Create: `backend/scripts/create_platform_admin.py`
- Create: `backend/tests/test_tenant_migration_verifier.py`
- Create: `docs/deployment/multi-tenant-production-rollout.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `verify_tenant_migration.py`，输出各表总行数、空租户行数和跨租户关系异常数，异常时退出码非零。
- Produces: 平台管理员初始化脚本，仅从环境变量读取密码。
- Produces: 中文生产发布、备份、验证和回滚步骤。

- [ ] **Step 1: 写迁移验证器失败测试**

```python
def test_verifier_fails_when_tenant_id_is_null(db, tenant_a):
    db.execute(text("INSERT INTO positions (id, title, description, tenant_id) "
                    "VALUES (:id, 'bad', 'bad', NULL)"), {"id": uuid4()})
    db.commit()
    result = verify_tenant_integrity(db)
    assert result.ok is False
    assert result.null_tenant_rows["positions"] == 1


def test_verifier_passes_for_two_isolated_tenants(db, tenant_a, tenant_b):
    seed_isolated_tenant_data(db, tenant_a.id)
    seed_isolated_tenant_data(db, tenant_b.id)
    assert verify_tenant_integrity(db).ok is True
```

- [ ] **Step 2: 运行测试并确认验证器不存在**

Run: `cd backend && pytest tests/test_tenant_migration_verifier.py -v`

Expected: import error for migration verifier.

- [ ] **Step 3: 实现验证脚本和平台管理员初始化**

验证器检查：所有租户表空租户行、用户重复约束、系统配置每租户数量、关键父子表 tenant 一致性、默认 `careray` 存在。脚本输出 JSON，任何异常退出 `1`。

平台管理员脚本只读取：

```text
PLATFORM_ADMIN_EMAIL
PLATFORM_ADMIN_PASSWORD
```

日志只输出邮箱和创建结果，不输出密码哈希或明文。

- [ ] **Step 4: 编写生产发布文档**

文档必须包含以下按序命令和判定条件：

1. `pg_dump -Fc` 整库备份和上传目录归档。
2. 在数据库副本执行 Alembic 和验证器。
3. 部署兼容性迁移与租户化应用。
4. 验证 `careray` 数据行数和主要业务流程。
5. 创建 `photonthix`，使用相同邮箱建立独立管理员。
6. 运行跨租户读取、后台任务、公开链接和文件测试。
7. 使用 `app_runtime` 启用 RLS 版本。
8. 验证两个域名、HTTPS、麦克风、SMTP 和 LLM。
9. 回滚时先回滚 RLS 策略，再回滚应用；不删除租户列和新表。

- [ ] **Step 5: 执行最终验证并提交**

Run:

```powershell
cd backend
pytest
cd ..\frontend
npm test
npm run build
cd ..
git diff --check
```

Expected: all tests and build pass; `git diff --check` reports no errors.

```bash
git add backend/scripts backend/tests/test_tenant_migration_verifier.py docs/deployment/multi-tenant-production-rollout.md README.md
git commit -m "docs: add multi-tenant rollout and verification"
```

---

## 最终验收门禁

- [ ] 在同一个 PostgreSQL 数据库创建 `careray` 和 `photonthix`。
- [ ] 两家公司使用相同邮箱、不同密码分别登录成功，错误公司登录失败。
- [ ] 职位、简历、面试、Offer、笔试、工作流、仪表盘和系统配置完全隔离。
- [ ] 后台任务携带错误租户时找不到资源且不更新其他租户数据。
- [ ] 公开链接只解析令牌绑定租户，数据库不保存明文 token。
- [ ] 上传文件位于租户目录，跨租户下载和路径穿越均失败。
- [ ] 原始 SQL 遗漏租户过滤时仍受 PostgreSQL RLS 限制。
- [ ] 禁用租户后新旧 JWT 均不能访问业务 API。
- [ ] 现有生产数据全部映射至 `careray`，迁移前后行数一致。
- [ ] 后端完整测试、PostgreSQL RLS 集成测试、前端测试和生产构建全部通过。

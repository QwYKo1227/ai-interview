# 岗位管理招聘负责人筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在岗位管理页增加默认展示全部岗位、可按单个招聘负责人精确筛选的下拉框。

**Architecture:** 后端在现有岗位列表查询上增加可选的 `hiring_manager_id` 条件，并提供一个受登录保护的负责人选项接口。前端独立加载负责人选项，通过纯函数构造岗位查询参数，再将单选下拉框放在岗位状态筛选框左侧。

**Tech Stack:** FastAPI、SQLAlchemy、Pydantic、Pytest、React 19、TypeScript、Ant Design、Axios、Vitest

## Global Constraints

- 页面首次进入时负责人为空，默认展示全部岗位。
- 不提供“未分配负责人”筛选项。
- 负责人筛选必须与标题和岗位状态组合生效。
- 不新增数据库字段或迁移，复用 `positions.hiring_manager_id`。
- 不改变岗位查看、编辑、发布或删除权限。
- 负责人选项只列出至少负责一个岗位的用户，并允许所有已登录用户读取。

---

### Task 1: 岗位列表按负责人精确筛选

**Files:**
- Create: `backend/tests/test_position_routes.py`
- Modify: `backend/app/services/position_service.py`
- Modify: `backend/app/routes/positions.py`

**Interfaces:**
- Consumes: `Position.hiring_manager_id: UUID | None` 和现有 `GET /positions` 查询参数。
- Produces: `get_positions_with_stats(..., hiring_manager_id: UUID | None = None)`；`GET /positions?hiring_manager_id=<uuid>`。

- [ ] **Step 1: 写入会失败的负责人及组合筛选测试**

在 `backend/tests/test_position_routes.py` 创建测试数据辅助函数和两个路由测试：

```python
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.models import Position, PositionStatus, User, UserRole


def create_manager(db: Session, email: str, full_name: str) -> User:
    manager = User(
        id=uuid4(),
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash("testpassword"),
        role=UserRole.HR,
        is_active=True,
    )
    db.add(manager)
    db.commit()
    db.refresh(manager)
    return manager


def create_position(
    db: Session,
    title: str,
    manager: User,
    position_status: PositionStatus = PositionStatus.OPEN,
) -> Position:
    position = Position(
        id=uuid4(),
        title=title,
        description=f"{title} description",
        status=position_status,
        hiring_manager_id=manager.id,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


class TestPositionHiringManagerFilter:
    def test_omitting_manager_returns_positions_for_all_managers(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        first = create_manager(db, "first@example.com", "First Manager")
        second = create_manager(db, "second@example.com", "Second Manager")
        create_position(db, "Backend Engineer", first)
        create_position(db, "Frontend Engineer", second)

        response = client.get("/api/positions", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert {item["title"] for item in response.json()} == {
            "Backend Engineer",
            "Frontend Engineer",
        }

    def test_manager_filter_combines_with_title_and_status(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        target = create_manager(db, "target@example.com", "Target Manager")
        other = create_manager(db, "other@example.com", "Other Manager")
        create_position(db, "Senior Backend Engineer", target, PositionStatus.PUBLISHED)
        create_position(db, "Backend Intern", target, PositionStatus.OPEN)
        create_position(db, "Senior Backend Engineer", other, PositionStatus.PUBLISHED)

        response = client.get(
            "/api/positions",
            params={
                "hiring_manager_id": str(target.id),
                "title": "Senior",
                "status": "published",
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert [item["title"] for item in response.json()] == [
            "Senior Backend Engineer"
        ]
        assert response.json()[0]["hiring_manager_id"] == str(target.id)
```

- [ ] **Step 2: 运行测试并确认按负责人过滤尚未生效**

Run: `cd backend && pytest tests/test_position_routes.py::TestPositionHiringManagerFilter -v`

Expected: 第一项通过，第二项失败，因为路由尚未接收并传递 `hiring_manager_id`，返回两个同名已发布岗位。

- [ ] **Step 3: 添加最小后端实现**

在 `backend/app/services/position_service.py` 为两个岗位查询函数增加参数，并在查询中追加精确条件：

```python
def get_positions(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    title: str = None,
    hiring_manager_id: Optional[UUID] = None,
):
    query = db.query(Position)
    if status:
        query = query.filter(Position.status == status)
    if title:
        query = query.filter(Position.title.ilike(f"%{title}%"))
    if hiring_manager_id:
        query = query.filter(Position.hiring_manager_id == hiring_manager_id)
    return query.order_by(Position.created_at.desc()).offset(skip).limit(limit).all()
```

在 `get_positions_with_stats` 使用相同签名和相同过滤条件。在 `backend/app/routes/positions.py` 更新列表路由：

```python
@router.get("", response_model=List[PositionWithStats])
def get_positions_route(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    title: str = None,
    hiring_manager_id: UUID = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_positions_with_stats(
        db,
        skip=skip,
        limit=limit,
        status=status,
        title=title,
        hiring_manager_id=hiring_manager_id,
    )
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `cd backend && pytest tests/test_position_routes.py::TestPositionHiringManagerFilter -v`

Expected: `2 passed`。

- [ ] **Step 5: 提交岗位筛选实现**

```bash
git add backend/tests/test_position_routes.py backend/app/services/position_service.py backend/app/routes/positions.py
git commit -m "feat: filter positions by hiring manager"
```

---

### Task 2: 提供已分配招聘负责人选项

**Files:**
- Modify: `backend/tests/test_position_routes.py`
- Modify: `backend/app/schemas/position.py`
- Modify: `backend/app/services/position_service.py`
- Modify: `backend/app/routes/positions.py`

**Interfaces:**
- Consumes: Task 1 的 `create_manager`、`create_position` 测试辅助函数和现有登录依赖 `get_current_user`。
- Produces: `HiringManagerOption`；`get_hiring_managers(db: Session) -> list[User]`；`GET /positions/hiring-managers`。

- [ ] **Step 1: 写入会失败的负责人选项测试**

追加以下测试，验证去重、排除未负责岗位的用户、HR 可访问以及未登录时拒绝访问：

```python
class TestHiringManagerOptions:
    def test_returns_distinct_managers_with_positions(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        assigned = create_manager(db, "assigned@example.com", "Assigned Manager")
        create_manager(db, "unused@example.com", "Unused Manager")
        create_position(db, "Backend Engineer", assigned)
        create_position(db, "Frontend Engineer", assigned)

        response = client.get(
            "/api/positions/hiring-managers", headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "id": str(assigned.id),
                "full_name": "Assigned Manager",
                "email": "assigned@example.com",
            }
        ]

    def test_requires_authentication(self, client: TestClient):
        response = client.get("/api/positions/hiring-managers")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
```

- [ ] **Step 2: 运行测试并确认静态接口尚不存在**

Run: `cd backend && pytest tests/test_position_routes.py::TestHiringManagerOptions -v`

Expected: 测试失败；`/hiring-managers` 被动态 `/{position_id}` 路由处理并返回 UUID 校验错误，或返回 404。

- [ ] **Step 3: 添加响应模型、服务查询和静态路由**

在 `backend/app/schemas/position.py` 添加：

```python
class HiringManagerOption(BaseModel):
    id: UUID
    full_name: Optional[str] = None
    email: str
    model_config = ConfigDict(from_attributes=True)
```

在 `backend/app/services/position_service.py` 添加：

```python
def get_hiring_managers(db: Session) -> List[User]:
    return (
        db.query(User)
        .join(Position, Position.hiring_manager_id == User.id)
        .distinct()
        .order_by(User.full_name.asc(), User.email.asc())
        .all()
    )
```

在 `backend/app/routes/positions.py` 导入新 schema 和 service，并在 `@router.get("/{position_id}")` 之前定义静态路由：

```python
@router.get("/hiring-managers", response_model=List[HiringManagerOption])
def get_hiring_managers_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_hiring_managers(db)
```

- [ ] **Step 4: 运行负责人选项与岗位筛选测试**

Run: `cd backend && pytest tests/test_position_routes.py -v`

Expected: `4 passed`。

- [ ] **Step 5: 提交负责人选项接口**

```bash
git add backend/tests/test_position_routes.py backend/app/schemas/position.py backend/app/services/position_service.py backend/app/routes/positions.py
git commit -m "feat: list assigned hiring managers"
```

---

### Task 3: 在岗位状态左侧接入负责人筛选

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/pages/Positions/filters.ts`
- Create: `frontend/src/pages/Positions/filters.test.ts`
- Modify: `frontend/src/pages/Positions/List.tsx`

**Interfaces:**
- Consumes: `GET /positions/hiring-managers` 返回 `{ id, full_name, email }[]`；`GET /positions` 接受 `hiring_manager_id`。
- Produces: `buildPositionListParams(filters: PositionListFilters)`；位于岗位状态左侧的单选负责人下拉框。

- [ ] **Step 1: 安装 Vitest 并增加测试脚本**

Run: `cd frontend && npm install --save-dev vitest`

在 `frontend/package.json` 的 scripts 中加入：

```json
"test": "vitest run"
```

- [ ] **Step 2: 为默认省略和组合查询参数写失败测试**

创建 `frontend/src/pages/Positions/filters.test.ts`：

```typescript
import { describe, expect, it } from 'vitest';
import { buildPositionListParams } from './filters';

describe('buildPositionListParams', () => {
  it('omits hiring_manager_id when no manager is selected', () => {
    expect(buildPositionListParams({ title: '', status: undefined, hiringManagerId: undefined }))
      .toEqual({ title: '', status: undefined });
  });

  it('combines hiring manager with title and status', () => {
    expect(buildPositionListParams({
      title: 'Backend',
      status: 'published',
      hiringManagerId: 'manager-id',
    })).toEqual({
      title: 'Backend',
      status: 'published',
      hiring_manager_id: 'manager-id',
    });
  });
});
```

- [ ] **Step 3: 运行测试并确认模块缺失**

Run: `cd frontend && npm test -- src/pages/Positions/filters.test.ts`

Expected: FAIL，提示无法解析 `./filters`。

- [ ] **Step 4: 实现纯查询参数构造函数**

创建 `frontend/src/pages/Positions/filters.ts`：

```typescript
export interface PositionListFilters {
  title: string;
  status?: string;
  hiringManagerId?: string;
}

export const buildPositionListParams = ({
  title,
  status,
  hiringManagerId,
}: PositionListFilters) => ({
  title,
  status,
  ...(hiringManagerId ? { hiring_manager_id: hiringManagerId } : {}),
});
```

- [ ] **Step 5: 运行测试并确认通过**

Run: `cd frontend && npm test -- src/pages/Positions/filters.test.ts`

Expected: `2 passed`。

- [ ] **Step 6: 接入负责人数据与筛选状态**

在 `frontend/src/pages/Positions/List.tsx` 导入 `buildPositionListParams`，定义类型并增加状态：

```typescript
interface HiringManagerOption {
  id: string;
  full_name: string | null;
  email: string;
}

const [hiringManagers, setHiringManagers] = useState<HiringManagerOption[]>([]);
const [searchHiringManagerId, setSearchHiringManagerId] = useState<string | undefined>();
```

将岗位请求 params 替换为：

```typescript
params: buildPositionListParams({
  title: searchTitle,
  status: searchStatus,
  hiringManagerId: searchHiringManagerId,
})
```

新增只在首次挂载时执行的选项请求：

```typescript
const fetchHiringManagers = async () => {
  try {
    const res = await request.get('/positions/hiring-managers');
    setHiringManagers(res);
  } catch {
    message.error('获取招聘负责人列表失败');
  }
};

useEffect(() => {
  fetchUsers();
  fetchHiringManagers();
}, []);

useEffect(() => {
  fetchPositions();
}, [searchTitle, searchStatus, searchHiringManagerId]);
```

移除原先同时调用 `fetchPositions()` 和 `fetchUsers()` 的 effect，避免每次筛选重复加载用户。

- [ ] **Step 7: 在岗位状态筛选框左侧添加下拉框**

紧接标题输入框之后、岗位状态 `Select` 之前插入：

```tsx
<Select
  placeholder="招聘负责人"
  style={{ width: 220 }}
  allowClear
  showSearch
  optionFilterProp="label"
  options={hiringManagers.map((manager) => ({
    value: manager.id,
    label: manager.full_name
      ? `${manager.full_name} (${manager.email})`
      : manager.email,
  }))}
  onChange={setSearchHiringManagerId}
/>
```

不添加“未分配负责人”选项，也不设置默认值。

- [ ] **Step 8: 验证测试、类型和改动文件 lint**

Run: `cd frontend && npm test -- src/pages/Positions/filters.test.ts && npm run build && npx eslint src/pages/Positions/List.tsx src/pages/Positions/filters.ts src/pages/Positions/filters.test.ts`

Expected: Vitest 显示 `2 passed`，Vite build 成功，ESLint 退出码为 0。

- [ ] **Step 9: 提交前端筛选**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/pages/Positions/filters.ts frontend/src/pages/Positions/filters.test.ts frontend/src/pages/Positions/List.tsx
git commit -m "feat: add hiring manager position filter"
```

---

### Task 4: 全量回归与人工验收

**Files:**
- Verify only; no planned file changes.

**Interfaces:**
- Consumes: Tasks 1-3 的后端接口、测试和前端筛选。
- Produces: 可交付的验证记录。

- [ ] **Step 1: 运行后端全量测试**

Run: `cd backend && pytest -v`

Expected: 全部测试通过，无新增 warning 或 error。

- [ ] **Step 2: 运行前端全量验证**

Run: `cd frontend && npm test && npm run build && npx eslint src/pages/Positions/List.tsx src/pages/Positions/filters.ts src/pages/Positions/filters.test.ts`

Expected: 全部前端测试通过，生产构建成功，改动文件 lint 退出码为 0。

- [ ] **Step 3: 人工验收页面行为**

启动应用后逐项确认：

1. 招聘负责人下拉框位于岗位状态左侧。
2. 首次进入未选负责人，列表展示全部岗位。
3. 下拉框仅包含已负责至少一个岗位的人员，不包含“未分配负责人”。
4. 选择负责人后只展示其岗位。
5. 负责人可与标题、状态组合筛选。
6. 清空负责人后恢复展示其他筛选条件下的全部岗位。
7. 使用 HR 账号可以加载负责人选项。
8. 模拟负责人选项请求失败时，岗位列表仍可使用且页面显示错误提示。

- [ ] **Step 4: 检查工作区和提交历史**

Run: `git status --short && git log -4 --oneline`

Expected: 除用户原有的 `backups/` 等无关未跟踪内容外，没有本功能的未提交文件；最近三个功能提交依次覆盖后端筛选、负责人选项接口和前端筛选。

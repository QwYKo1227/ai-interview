# 岗位与简历统一筛选及岗位列表字段调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一岗位管理与简历管理的即时筛选交互，补齐岗位部门/紧急度和简历应聘岗位筛选，并按指定顺序调整岗位列表字段。

**Architecture:** 岗位后端扩展现有查询参数并提供去重部门选项接口；两个前端页面都使用受控筛选对象、当前值 ref 和共享最新请求协调器，筛选变化立即请求，重置只清空状态。岗位列表只调整展示列，不改模型或数据库；简历复用已经支持的 `position_id` 后端查询。

**Tech Stack:** FastAPI、SQLAlchemy、Pydantic、Pytest、React 19、TypeScript、Ant Design、Axios、Vitest、Playwright（仅验收环境）

## Global Constraints

- 岗位管理与简历管理均使用卡片式横向筛选栏，标签、间距、控件尺寸和重置按钮样式保持一致。
- 两个模块的筛选条件变化后立即生效，不显示“搜索”按钮，只保留“重置”按钮。
- 岗位筛选为岗位名称、部门、招聘负责人、紧急度、状态；重置后五项全部为空。
- 简历筛选为候选人、应聘岗位、状态；重置后三项全部为空。
- 岗位列表列顺序固定为岗位名称、部门、招聘人数、招聘负责人、紧急度、状态、招聘进度、创建时间、操作。
- 不使用表格标题内置筛选菜单。
- 不改变岗位或简历权限、简历状态定义、轮询周期或分页方式。
- 不新增数据库字段或迁移。
- 旧响应不得覆盖当前筛选结果；轮询、手动刷新和 mutation 后刷新必须读取调用时的最新筛选条件。

---

### Task 1: 扩展岗位部门与紧急度后端筛选

**Files:**
- Modify: `backend/tests/test_position_routes.py`
- Modify: `backend/app/services/position_service.py`
- Modify: `backend/app/routes/positions.py`

**Interfaces:**
- Consumes: 已有 `GET /positions` 的 `title`、`status`、`hiring_manager_id` 和现有 `Position.department`、`Position.urgency` 字段。
- Produces: `GET /positions?department=<name>&urgency=<value>`；`get_position_departments(db) -> list[str]`；认证接口 `GET /positions/departments -> list[str]`。

- [ ] **Step 1: 扩展测试辅助函数并写失败测试**

在 `backend/tests/test_position_routes.py` 导入 `PositionUrgency`，将辅助函数扩展为：

```python
def create_position(
    db: Session,
    title: str,
    manager: User,
    position_status: PositionStatus = PositionStatus.OPEN,
    department: str | None = None,
    urgency: PositionUrgency = PositionUrgency.MEDIUM,
) -> Position:
    position = Position(
        id=uuid4(),
        title=title,
        description=f"{title} description",
        status=position_status,
        department=department,
        urgency=urgency,
        hiring_manager_id=manager.id,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position
```

追加组合筛选和部门选项测试：

```python
class TestPositionDepartmentAndUrgencyFilters:
    def test_combines_department_urgency_manager_status_and_title(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        target = create_manager(db, "target-filter@example.com", "Target Filter")
        other = create_manager(db, "other-filter@example.com", "Other Filter")
        create_position(
            db, "Senior Backend Engineer", target, PositionStatus.PUBLISHED,
            "Engineering", PositionUrgency.URGENT,
        )
        create_position(
            db, "Backend Intern", target, PositionStatus.PUBLISHED,
            "Engineering", PositionUrgency.LOW,
        )
        create_position(
            db, "Senior Backend Engineer", other, PositionStatus.PUBLISHED,
            "Engineering", PositionUrgency.URGENT,
        )

        response = client.get(
            "/api/positions",
            params={
                "title": "Senior",
                "department": "Engineering",
                "urgency": "urgent",
                "status": "published",
                "hiring_manager_id": str(target.id),
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert [item["title"] for item in response.json()] == ["Senior Backend Engineer"]
        assert response.json()[0]["hiring_manager_id"] == str(target.id)


class TestPositionDepartmentOptions:
    def test_returns_distinct_non_empty_sorted_departments(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        manager = create_manager(db, "departments@example.com", "Department Owner")
        create_position(db, "Platform", manager, department="Engineering")
        create_position(db, "Frontend", manager, department="Engineering")
        create_position(db, "Recruiter", manager, department="People")
        create_position(db, "Unassigned Department", manager, department=None)

        response = client.get("/api/positions/departments", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == ["Engineering", "People"]

    def test_requires_authentication(self, client: TestClient):
        response = client.get("/api/positions/departments")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
```

- [ ] **Step 2: 运行测试并确认新能力缺失**

Run: `cd backend && C:\Users\wb.yu\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_position_routes.py::TestPositionDepartmentAndUrgencyFilters tests/test_position_routes.py::TestPositionDepartmentOptions -v`

Expected: 组合筛选测试返回多余岗位；部门静态路径被 UUID 路由捕获并返回 422，未登录用例返回 401 或 422。

- [ ] **Step 3: 实现查询参数和部门选项服务**

在 `backend/app/services/position_service.py` 的 `get_positions` 和 `get_positions_with_stats` 签名中追加：

```python
department: Optional[str] = None,
urgency: Optional[PositionUrgency] = None,
```

并在两个查询中使用相同条件：

```python
if department:
    query = query.filter(Position.department == department)
if urgency:
    query = query.filter(Position.urgency == urgency)
```

添加部门服务：

```python
def get_position_departments(db: Session) -> List[str]:
    rows = (
        db.query(Position.department)
        .filter(Position.department.isnot(None), Position.department != "")
        .distinct()
        .order_by(Position.department.asc())
        .all()
    )
    return [department for (department,) in rows]
```

在 `backend/app/routes/positions.py` 为岗位列表增加 `department: str = None` 和 `urgency: PositionUrgency = None`，转发到服务。导入 `PositionUrgency` 和 `get_position_departments`，并在 `/{position_id}` 之前添加：

```python
@router.get("/departments", response_model=List[str])
def get_position_departments_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_position_departments(db)
```

- [ ] **Step 4: 运行岗位路由测试**

Run: `cd backend && C:\Users\wb.yu\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_position_routes.py -v`

Expected: 全部岗位路由测试通过。

- [ ] **Step 5: 提交后端筛选**

```bash
git add backend/tests/test_position_routes.py backend/app/services/position_service.py backend/app/routes/positions.py
git commit -m "feat: filter positions by department and urgency"
```

---

### Task 2: 统一岗位筛选栏并调整岗位列表字段

**Files:**
- Create: `frontend/src/utils/latestRequest.ts`
- Modify: `frontend/src/pages/Positions/filters.ts`
- Modify: `frontend/src/pages/Positions/filters.test.ts`
- Modify: `frontend/src/pages/Positions/List.tsx`

**Interfaces:**
- Consumes: Task 1 的 `department`、`urgency` 查询参数和 `/positions/departments`，以及现有 `/positions/hiring-managers`。
- Produces: `PositionListFilters` 五项筛选、`createEmptyPositionListFilters()`、共享 `createLatestRequestCoordinator()`，以及指定九列岗位表格。

- [ ] **Step 1: 写岗位筛选参数与重置失败测试**

更新 `frontend/src/pages/Positions/filters.test.ts`，在现有参数测试中加入：

```typescript
import { createEmptyPositionListFilters } from './filters';

it('combines all position filters', () => {
  expect(buildPositionListParams({
    title: 'Backend',
    department: 'Engineering',
    hiringManagerId: 'manager-id',
    urgency: 'urgent',
    status: 'published',
  })).toEqual({
    title: 'Backend',
    department: 'Engineering',
    hiring_manager_id: 'manager-id',
    urgency: 'urgent',
    status: 'published',
  });
});

it('creates an empty five-field filter state for reset', () => {
  expect(createEmptyPositionListFilters()).toEqual({
    title: '',
    department: undefined,
    hiringManagerId: undefined,
    urgency: undefined,
    status: undefined,
  });
});

it('clears a selected department after its final position disappears', () => {
  expect(reconcileDepartmentSelection('People', ['Engineering'])).toBeUndefined();
  expect(reconcileDepartmentSelection('Engineering', ['Engineering'])).toBe('Engineering');
});
```

同时把现有“未选择负责人”测试的期望值改为 `{}`，因为新的参数构造函数会省略全部空值；其余现有 fixture 可以省略新增可选字段。导入 `reconcileDepartmentSelection`。

- [ ] **Step 2: 运行测试并确认类型/导出缺失**

Run: `cd frontend && npm test -- src/pages/Positions/filters.test.ts`

Expected: FAIL，提示 `department`/`urgency` 不属于接口或 `createEmptyPositionListFilters` 未导出。

- [ ] **Step 3: 扩展岗位筛选模型并提取共享协调器**

创建 `frontend/src/utils/latestRequest.ts`，将现有 `LatestRequestCallbacks` 和 `createLatestRequestCoordinator` 原样移动到该文件并导出。`Positions/List.tsx` 和测试改从 `../../utils/latestRequest` 导入；从 `Positions/filters.ts` 删除协调器定义。

将岗位筛选定义改为：

```typescript
export interface PositionListFilters {
  title: string;
  department?: string;
  hiringManagerId?: string;
  urgency?: string;
  status?: string;
}

export const createEmptyPositionListFilters = (): PositionListFilters => ({
  title: '',
  department: undefined,
  hiringManagerId: undefined,
  urgency: undefined,
  status: undefined,
});

export const reconcileDepartmentSelection = (
  selectedDepartment: string | undefined,
  departments: readonly string[],
): string | undefined => (
  selectedDepartment && departments.includes(selectedDepartment)
    ? selectedDepartment
    : undefined
);
```

`buildPositionListParams` 对五项使用条件展开，空字符串或 `undefined` 时省略，非空时输出 `title`、`department`、`hiring_manager_id`、`urgency`、`status`。

- [ ] **Step 4: 运行岗位筛选测试并确认通过**

Run: `cd frontend && npm test -- src/pages/Positions/filters.test.ts`

Expected: 所有岗位筛选测试通过。

- [ ] **Step 5: 将岗位筛选状态改为五项受控对象**

在 `frontend/src/pages/Positions/List.tsx`：

```typescript
const [filters, setFilters] = useState<PositionListFilters>(createEmptyPositionListFilters);
const filtersRef = useRef(filters);
filtersRef.current = filters;
```

删除独立的 `searchTitle/searchStatus/searchHiringManagerId` state。筛选 effect 依赖五项值；`fetchPositions` 继续通过 `buildCurrentPositionListParams(filtersRef)` 读取调用时最新条件。负责人选项刷新时使用：

```typescript
setFilters((current) => ({
  ...current,
  hiringManagerId: reconcileHiringManagerSelection(
    current.hiringManagerId,
    response,
  ),
}));
```

新增 `departments: string[]` 状态和 `/positions/departments` 请求；失败时 `message.error('获取部门列表失败')`，不影响岗位列表。请求成功后调用 `reconcileDepartmentSelection`：当前部门仍存在时保留，已消失时清空。

初次挂载加载部门。创建/编辑、单删和批删成功后，与负责人选项一起刷新部门选项；批量发布/下架不刷新选项。使用 `Promise.all([fetchPositions(), fetchHiringManagers(), fetchDepartments()])` 或等价并行刷新，且保留现有只提交最新岗位列表请求的协调机制。

- [ ] **Step 6: 用统一 Card/Form 渲染即时筛选与重置**

将岗位筛选容器替换为与简历页一致的结构：

```tsx
<Card style={{ marginBottom: 24, borderRadius: '8px' }} bodyStyle={{ padding: '24px' }}>
  <Form layout="inline">
    <Form.Item label="岗位名称">...</Form.Item>
    <Form.Item label="部门">...</Form.Item>
    <Form.Item label="招聘负责人">...</Form.Item>
    <Form.Item label="紧急度">...</Form.Item>
    <Form.Item label="状态">...</Form.Item>
    {/* 现有批量操作 Form.Item，仅在选中行时显示 */}
    <Form.Item>
      <Button onClick={() => setFilters(createEmptyPositionListFilters())}>重置</Button>
    </Form.Item>
  </Form>
</Card>
```

所有 Input/Select 都设置 `value` 并在 `onChange` 中更新对应字段；部门、负责人支持搜索和清空，紧急度、状态支持清空。不渲染搜索按钮。

- [ ] **Step 7: 按指定顺序调整岗位列**

删除职位类型列和不再使用的 `positionTypeConfig`，在部门后插入：

```typescript
{
  title: '招聘人数',
  dataIndex: 'headcount',
  key: 'headcount',
  render: (value: number) => `${value || 1} 人`,
},
{
  title: '招聘负责人',
  dataIndex: 'hiring_manager_name',
  key: 'hiring_manager_name',
  render: (value: string | null) => value || '-',
},
```

确认最终数组顺序为岗位名称、部门、招聘人数、招聘负责人、紧急度、状态、招聘进度、创建时间、操作。

- [ ] **Step 8: 运行前端岗位验证**

Run: `cd frontend && npm test -- src/pages/Positions/filters.test.ts && npm run build && npx eslint src/pages/Positions/List.tsx src/pages/Positions/filters.ts src/pages/Positions/filters.test.ts src/utils/latestRequest.ts`

Expected: 测试通过、生产构建成功、目标文件 ESLint 退出码 0。

- [ ] **Step 9: 提交岗位页面调整**

```bash
git add frontend/src/utils/latestRequest.ts frontend/src/pages/Positions/filters.ts frontend/src/pages/Positions/filters.test.ts frontend/src/pages/Positions/List.tsx
git commit -m "feat: unify position filters and columns"
```

---

### Task 3: 为简历列表增加即时应聘岗位筛选

**Files:**
- Create: `frontend/src/pages/Resumes/filters.ts`
- Create: `frontend/src/pages/Resumes/filters.test.ts`
- Modify: `frontend/src/pages/Resumes/List.tsx`
- Create: `backend/tests/test_resume_routes.py`

**Interfaces:**
- Consumes: Task 2 的 `createLatestRequestCoordinator`；现有 `GET /resumes` 的 `candidate_name`、`status`、`position_id`、`reviewer_id` 参数和页面已有岗位选项。
- Produces: `ResumeListFilters`、`createEmptyResumeListFilters()`、`buildResumeListParams()`、即时筛选和统一重置行为。

- [ ] **Step 1: 写简历筛选纯函数失败测试**

创建 `frontend/src/pages/Resumes/filters.test.ts`：

```typescript
import { describe, expect, it } from 'vitest';
import {
  buildCurrentResumeListParams,
  buildResumeListParams,
  createEmptyResumeListFilters,
} from './filters';

describe('resume filters', () => {
  it('combines candidate, position, status, and reviewer filters', () => {
    expect(buildResumeListParams({
      candidateName: 'Alice',
      positionId: 'position-id',
      status: 'pending_review',
    }, 'reviewer-id')).toEqual({
      candidate_name: 'Alice',
      position_id: 'position-id',
      status: 'pending_review',
      reviewer_id: 'reviewer-id',
    });
  });

  it('creates an empty three-field filter state for reset', () => {
    expect(createEmptyResumeListFilters()).toEqual({
      candidateName: '',
      positionId: undefined,
      status: undefined,
    });
  });

  it('reads the latest filters when a stable refresh is invoked', () => {
    const ref = { current: createEmptyResumeListFilters() };
    const refresh = () => buildCurrentResumeListParams(ref, undefined);
    ref.current = { candidateName: 'Bob', positionId: 'new-position', status: 'hired' };

    expect(refresh()).toEqual({
      candidate_name: 'Bob',
      position_id: 'new-position',
      status: 'hired',
    });
  });
});
```

- [ ] **Step 2: 运行测试并确认模块缺失**

Run: `cd frontend && npm test -- src/pages/Resumes/filters.test.ts`

Expected: FAIL，提示无法解析 `./filters`。

- [ ] **Step 3: 实现简历筛选纯函数**

创建 `frontend/src/pages/Resumes/filters.ts`：

```typescript
export interface ResumeListFilters {
  candidateName: string;
  positionId?: string;
  status?: string;
}

export const createEmptyResumeListFilters = (): ResumeListFilters => ({
  candidateName: '',
  positionId: undefined,
  status: undefined,
});

export const buildResumeListParams = (
  filters: ResumeListFilters,
  reviewerId?: string,
) => ({
  ...(filters.candidateName ? { candidate_name: filters.candidateName } : {}),
  ...(filters.positionId ? { position_id: filters.positionId } : {}),
  ...(filters.status ? { status: filters.status } : {}),
  ...(reviewerId ? { reviewer_id: reviewerId } : {}),
});

export const buildCurrentResumeListParams = (
  filtersRef: { readonly current: ResumeListFilters },
  reviewerId?: string,
) => buildResumeListParams(filtersRef.current, reviewerId);
```

- [ ] **Step 4: 运行纯函数测试并确认通过**

Run: `cd frontend && npm test -- src/pages/Resumes/filters.test.ts`

Expected: `3 passed`。

- [ ] **Step 5: 改造简历请求为即时、最新条件请求**

在 `frontend/src/pages/Resumes/List.tsx` 使用单个筛选对象和 ref：

```typescript
const [filters, setFilters] = useState<ResumeListFilters>(createEmptyResumeListFilters);
const filtersRef = useRef(filters);
filtersRef.current = filters;
const userRef = useRef(user);
userRef.current = user;
const requestCoordinator = useRef(createLatestRequestCoordinator()).current;
```

将 `fetchResumes` 包装为稳定 `useCallback`，请求参数来自 `buildCurrentResumeListParams`；仅当 `userRef.current?.role === 'interviewer'` 时传 reviewer ID。所有请求由同一 coordinator 执行，只有最新请求更新 `data` 和 `pollingEnabled`。非静默请求在 `onStart` 设置 loading；所有最新请求（包括静默轮询）在 `onSettled` 设置 loading 为 false，以免静默请求取代尚未完成的非静默请求后留下 loading。静默轮询不显示错误消息，但同样不能提交旧数据。

添加 effect：

```typescript
useEffect(() => {
  void fetchResumes();
}, [fetchResumes, filters.candidateName, filters.positionId, filters.status]);
```

删除旧 `handleSearch` 和直接调用 `/resumes` 的重置请求。重置只执行：

```typescript
setFilters(createEmptyResumeListFilters());
```

轮询、手动刷新和 mutation 后现有 `fetchResumes()` 调用全部保留，并因稳定函数而读取最新 ref。

- [ ] **Step 6: 将简历筛选栏调整为统一即时样式**

保留现有 `Card` 和 `Form layout="inline"`，统一控件宽度与岗位页对应。受控项依次为候选人、应聘岗位、状态：

```tsx
<Form.Item label="应聘岗位">
  <Select
    placeholder="请选择应聘岗位"
    value={filters.positionId}
    onChange={(positionId) => setFilters((current) => ({ ...current, positionId }))}
    style={{ width: 220 }}
    allowClear
    showSearch
    optionFilterProp="children"
  >
    {positions.map((position: PositionOption) => (
      <Select.Option key={position.id} value={position.id}>{position.title}</Select.Option>
    ))}
  </Select>
</Form.Item>
```

删除 `SearchOutlined` 导入和搜索按钮，只保留：

```tsx
<Button onClick={() => setFilters(createEmptyResumeListFilters())}>重置</Button>
```

现有面试官筛选区可见性条件保持不变。

- [ ] **Step 7: 添加现有简历 position_id API 回归测试**

创建 `backend/tests/test_resume_routes.py`：

```python
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.models import Position, Resume, ResumeStatus


def test_filters_resumes_by_position_id(
    client: TestClient,
    auth_headers: dict,
    db: Session,
    test_resume: Resume,
    test_position: Position,
):
    other_position = Position(
        id=uuid4(),
        title="Other Position",
        description="Other position description",
    )
    db.add(other_position)
    db.commit()
    db.refresh(other_position)

    other_resume = Resume(
        id=uuid4(),
        candidate_name="Other Candidate",
        contact="13900000000",
        email="other@example.com",
        position_id=other_position.id,
        file_path="/uploads/other.pdf",
        status=ResumeStatus.PENDING_SCREENING,
    )
    db.add(other_resume)
    db.commit()

    response = client.get(
        "/api/resumes",
        params={"position_id": str(test_position.id)},
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()
    assert {item["position_id"] for item in response.json()} == {
        str(test_position.id)
    }
```

该测试是对已存在后端能力的特征回归测试，预期首次运行即通过，不驱动生产代码修改。

- [ ] **Step 8: 运行简历与全前端验证**

Run: `cd backend && C:\Users\wb.yu\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_resume_routes.py -v`

Expected: 简历 position_id 回归测试通过。

Run: `cd frontend && npm test && npm run build && npx eslint src/pages/Resumes/List.tsx src/pages/Resumes/filters.ts src/pages/Resumes/filters.test.ts src/pages/Positions/List.tsx src/pages/Positions/filters.ts src/pages/Positions/filters.test.ts src/utils/latestRequest.ts`

Expected: 全部 Vitest 通过、生产构建成功、目标文件 ESLint 退出码 0。

- [ ] **Step 9: 提交简历即时筛选**

```bash
git add backend/tests/test_resume_routes.py frontend/src/pages/Resumes/filters.ts frontend/src/pages/Resumes/filters.test.ts frontend/src/pages/Resumes/List.tsx
git commit -m "feat: add instant resume position filters"
```

---

### Task 4: 全量回归与浏览器验收

**Files:**
- Verify only; no planned tracked file changes.

**Interfaces:**
- Consumes: Tasks 1-3 的后端筛选、部门选项、两个即时筛选栏和岗位列表列调整。
- Produces: 完整测试与浏览器验收记录。

- [ ] **Step 1: 运行后端全量测试**

Run: `cd backend && C:\Users\wb.yu\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q`

Expected: 全部测试通过；允许已有 warning 及新增测试触发现有 warning 类型，不允许本功能新增生产代码 warning 类型。

- [ ] **Step 2: 运行前端全量测试、构建和目标 lint**

Run: `cd frontend && npm test && npm run build && npx eslint src/pages/Positions/List.tsx src/pages/Positions/filters.ts src/pages/Positions/filters.test.ts src/pages/Resumes/List.tsx src/pages/Resumes/filters.ts src/pages/Resumes/filters.test.ts src/utils/latestRequest.ts`

Expected: 全部测试通过，构建成功，目标 lint 退出码 0；允许已有 Vite 大包体 advisory。

- [ ] **Step 3: 使用 Playwright/Chromium 做真实浏览器自动化验收**

在忽略目录 `.superpowers/sdd/` 创建临时脚本，启动本地 Vite 并通过 Playwright route interception 模拟认证与 API。实际断言：

1. 岗位和简历均使用卡片式横向筛选栏，均无“搜索”按钮且有“重置”。
2. 岗位筛选顺序为名称、部门、负责人、紧急度、状态；每项变化立即产生正确查询参数。
3. 岗位重置移除五项参数并恢复全部模拟岗位。
4. 岗位表头顺序严格为岗位名称、部门、招聘人数、招聘负责人、紧急度、状态、招聘进度、创建时间、操作，且无职位类型。
5. 简历筛选顺序为候选人、应聘岗位、状态；每项变化立即产生 `candidate_name`、`position_id`、`status`。
6. 简历重置移除三项筛选参数，面试官模拟请求仍保留 `reviewer_id`。
7. 制造乱序响应时，两个页面均只显示最新筛选结果。
8. 部门或负责人选项接口失败时，岗位列表仍可使用。

Expected: 浏览器脚本退出码 0，所有断言 PASS；临时脚本和截图不加入 git。

- [ ] **Step 4: 检查工作树和提交历史**

Run: `git status --short && git log -6 --oneline`

Expected: 没有本功能未提交文件；最近三个实现提交依次覆盖岗位后端筛选、岗位 UI/列、简历即时筛选。

# AI Interview API 接入文档

本接口用于将外部招聘系统、企业门户和业务应用接入 AI Interview，支持岗位查询、简历投递与解析、部门评审、面试、笔试、Offer 和招聘统计。使用受保护接口前，请先获取所属公司的账号并完成登录。

| 项目 | 内容 |
| --- | --- |
| 文档版本 | 1.0.0 |
| 接口版本 | 1.0.0 |
| 更新日期 | 2026 年 10 月 21 日 |
| 服务地址 | `https://interview.careray.com` |
| API 基础地址 | `https://interview.careray.com/api` |
| 传输方式 | HTTPS |
| 字符编码 | UTF-8 |
| 认证方式 | Bearer Token |

## 文档使用方式

本页提供接入步骤与常见业务示例。[完整接口手册](index.html#reference)提供每个接口的路径、权限、请求参数、请求体、响应结构和数据模型，可离线打开。[OpenAPI 文件](openapi.json)可导入 Postman 等 API 客户端。

本交付范围为公司账号权限内的招聘业务和公司管理接口。平台级公司开通、服务部署与运维接口不在本手册范围。接口是否可调用，取决于接入账号的角色、公司归属及具体资源授权。

## 接入准备

接入前，请向接口提供方确认服务地址、网络访问方式、公司代码、接入账号与权限。当前服务地址需在允许访问的网络内使用；API 地址本身不代表已开放公网访问。

当前服务使用内部 CA 签发的 HTTPS 证书。根证书由接口提供方提供，请导入调用环境的信任证书库，或在 HTTP 客户端中指定该证书。以下证书路径为示例，应替换为接入方本机的实际文件路径。

```bash
export API_BASE='https://interview.careray.com/api'
export CURL_CA_BUNDLE='/path/to/ai-interview-root-ca.crt'
```

下文命令使用 Bash、curl 和 jq。命令中的邮箱、公司代码、密码、UUID 和文件名均为示例，调用时须替换为实际值。连通性可通过公司列表或当前用户接口验证；涉及创建和发送的联调示例应使用约定的测试账号与业务数据。

## 认证与身份

### 查询可登录公司

```bash
curl --fail-with-body -sS "$API_BASE/auth/tenants" | jq
```

该接口无需登录，返回公司数组。以下为字段示意，UUID、名称等需以实际返回为准：

```json
[
  {
    "id": "11111111-1111-4111-8111-111111111111",
    "code": "your-company",
    "name": "示例公司",
    "logo_url": null,
    "primary_domain": null
  }
]
```

登录时使用 `code`，不要把公司名称或公司 UUID 填入 `tenant_code`。公司列表会变化，集成程序应查询接口获取。

### 公司账号登录

`POST /auth/login` 接收 JSON：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `tenant_code` | string | 是 | 公司代码，长度 1 到 64 个字符 |
| `email` | string | 是 | 当前公司下的登录邮箱 |
| `password` | string | 是 | 账号密码 |

创建 `login.json`，替换为实际账号：

```json
{
  "tenant_code": "your-company",
  "email": "your-account@example.com",
  "password": "请替换为实际密码"
}
```

调用并保存 Token：

```bash
LOGIN_RESPONSE=$(curl --fail-with-body -sS \
  -X POST "$API_BASE/auth/login" \
  -H 'Content-Type: application/json' \
  --data-binary @login.json) && \
TOKEN=$(printf '%s' "$LOGIN_RESPONSE" | jq -er '.access_token') && \
export TOKEN
```

成功响应：

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

后续受保护接口均携带请求头：

```http
Authorization: Bearer <access_token>
```

公司账号 Token 当前有效期为 30 天。密码变更后，旧 Token 会失效；收到 `401` 时应重新登录。客户端不要把密码、Token 或包含敏感信息的请求体提交到版本库。

登录响应不包含刷新令牌。调用方可在有效期内复用 Token，失效后重新登录，无需在每次业务请求前登录。

登录成功后保存 `access_token`；每次请求通过请求头传递，不在 URL 中传递账号 Token。

### 验证登录身份

```bash
curl --fail-with-body -sS "$API_BASE/auth/me" \
  -H "Authorization: Bearer $TOKEN" | jq
```

响应包含 `id`、`email`、`full_name`、`role`、`is_active` 和 `tenant`。后续示例中需要的当前用户 UUID 可取自 `id`。

公司账号角色为 `admin`、`hr`、`interviewer`。接口还会根据岗位负责人、评审分配、面试小组等条件限制数据范围，拥有 Token 不代表可以访问所有记录。

公司数据范围由 Token 决定，受保护接口无需另外传 `tenant_code`，传入其他公司代码也不能切换公司。使用公司专属域名时，域名绑定公司必须与 Token 中的公司一致。

## 请求和响应约定

| 项目 | 约定 |
| --- | --- |
| 路径 | 以下业务路径均相对于 `API_BASE`，例如 `/positions` 对应 `/api/positions` |
| JSON 请求 | 设置 `Content-Type: application/json` |
| 文件上传 | 使用 `multipart/form-data`；curl 使用 `-F`，由客户端自动生成 boundary |
| 普通表单 | 使用 `application/x-www-form-urlencoded`，例如指派部门评审人 |
| 标识符 | `position_id`、`resume_id`、`interview_id`、用户 ID 等为 UUID 字符串 |
| 日期时间 | 使用 ISO 8601，明确携带时区，例如 `2026-11-02T10:00:00+08:00` |
| 分页 | 常用列表使用 `skip` 和 `limit`；`skip` 从 0 开始，`limit` 至少为 1 |
| 列表响应 | 岗位、简历、面试列表直接返回 JSON 数组，不包含统一的 `data` 或 `total` 包装 |
| 成功响应 | 多数接口为 `200`；删除面试为 `204`，以具体接口定义为准 |

岗位、简历和面试列表未指定 `limit` 时可能返回全部可见记录，集成程序宜显式传入分页参数。Offer 列表使用另一种分页方式：`page` 默认 1，`page_size` 默认 10、最大 100；响应对象包含 `items`、`total`、`page`、`page_size` 和 `total_pages`。其他模块以具体接口定义为准。

## 岗位接口

### 查询岗位

`GET /positions`，要求公司管理员或 HR 身份。

```bash
curl --fail-with-body -sS --get "$API_BASE/positions" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'skip=0' \
  --data-urlencode 'limit=20' \
  --data-urlencode 'title=Python' | jq
```

常用过滤条件：

| 参数 | 说明 |
| --- | --- |
| `title` | 岗位标题搜索 |
| `status` | `open`、`published`、`paused`、`closed`、`cancelled` |
| `department` | 部门 |
| `hiring_manager_id` | 岗位负责人 UUID |
| `priority` | 优先级，1 到 5 |
| `category` | 岗位类别，取值见 OpenAPI 的 `PositionCategory` |
| `include_deleted`、`deleted_only` | 是否包含或仅查询已删除岗位；仅管理员可使用 |

每条岗位记录包含 `id`、`title`、`status` 等信息，以及 `stats` 招聘统计。

### 创建与更新岗位

`POST /positions`，要求公司管理员或 HR 身份。最小请求只需要 `title` 和 `description`：

```bash
curl --fail-with-body -sS -X POST "$API_BASE/positions" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Python 后端工程师",
    "description": "负责招聘系统后端开发与维护",
    "requirements": "熟悉 Python、FastAPI 和 PostgreSQL",
    "department": "研发部",
    "location": "上海",
    "status": "open",
    "priority": 3,
    "headcount": 1
  }' | jq
```

将返回的 `id` 保存为后续调用的岗位 ID：

```bash
export POSITION_ID='请替换为实际岗位UUID'
```

HR 创建岗位时，负责人自动设置为当前用户。`open` 状态的岗位尚未对外发布；如需公开投递，应按业务流程将状态改为 `published`。

```bash
curl --fail-with-body -sS -X PUT "$API_BASE/positions/$POSITION_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"requirements":"熟悉 Python、FastAPI，具有数据库调优经验"}' | jq
```

更新接口只需传入要修改的字段。其他常用路径：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/positions/{position_id}` | 岗位详情 |
| GET | `/positions/{position_id}/stats` | 岗位招聘统计 |
| GET | `/positions/hiring-managers` | 可选岗位负责人 |
| DELETE | `/positions/{position_id}` | 软删除岗位，受权限和业务条件限制 |

## 简历接口

### 公开岗位和单份投递

先读取指定公司的公开岗位，无需登录：

```bash
export TENANT_CODE='your-company'

curl --fail-with-body -sS --get "$API_BASE/public/$TENANT_CODE/positions" \
  --data-urlencode 'skip=0' \
  --data-urlencode 'limit=20' | jq
```

`POST /resumes` 是公开投递接口，使用表单上传，要求岗位已发布且未删除。在共享域名上需传入 `tenant_code`；后台 Token 不会代替该参数。

| 表单字段 | 必填 | 说明 |
| --- | --- | --- |
| `position_id` | 是 | 公开岗位 UUID |
| `tenant_code` | 共享域名下是 | 公司代码；公司专属域名可由域名解析公司 |
| `file` | 是 | PDF 文件，扩展名为 `.pdf`，Content-Type 为 `application/pdf`，单份不超过 10 MiB |
| `candidate_name` | 否 | 候选人姓名 |
| `email` | 否 | 候选人邮箱 |
| `contact` | 否 | 联系电话 |

```bash
curl --fail-with-body -sS -X POST "$API_BASE/resumes" \
  -F "position_id=$POSITION_ID" \
  -F "tenant_code=$TENANT_CODE" \
  -F 'candidate_name=示例候选人' \
  -F 'email=candidate@example.com' \
  -F 'contact=13800000000' \
  -F 'file=@./resume.pdf;type=application/pdf' | jq
```

该接口会创建真实投递记录。返回简历对象，其中 `id` 为简历 UUID。HTTP 成功表示记录已创建，AI 解析在后台继续执行。

### 后台上传简历

管理员或 HR 使用 `POST /resumes/batch`，携带 Token，可用于已有岗位的后台录入。文件字段名为 `files`，即使只上传一份也使用复数：

```bash
curl --fail-with-body -sS -X POST "$API_BASE/resumes/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -F "position_id=$POSITION_ID" \
  -F 'files=@./resume-a.pdf;type=application/pdf' \
  -F 'files=@./resume-b.pdf;type=application/pdf' | jq
```

返回简历数组，每份 PDF 同样不超过 10 MiB。当前服务单次上传请求体上限为 101 MiB，上传较多文件时应拆分请求。

### 查询简历与解析结果

```bash
curl --fail-with-body -sS --get "$API_BASE/resumes" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "position_id=$POSITION_ID" \
  --data-urlencode 'skip=0' \
  --data-urlencode 'limit=20' | jq

export RESUME_ID='请替换为实际简历UUID'

curl --fail-with-body -sS "$API_BASE/resumes/$RESUME_ID" \
  -H "Authorization: Bearer $TOKEN" | jq
```

简历列表还支持 `candidate_name`、`status` 和 `reviewer_id` 过滤。详情中的主要字段：

| 字段 | 用途 |
| --- | --- |
| `parse_status` | 解析进度，常见值为 `processing`、`success`、`completed`、`failed`；`success` 与 `completed` 均表示解析完成 |
| `parse_error` | 解析失败原因 |
| `parsed_data` | 结构化解析数据 |
| `match_score`、`ai_review` | 岗位匹配评分和 AI 评价 |
| `status`、`screening_result` | 招聘流程状态和初筛结果 |
| `file_id` | 原始简历文件 UUID，用于受保护的下载接口 |

需要等待解析结果时，可每隔几秒查询一次详情，设置总等待时限；不要把上传响应当作最终解析结果。解析失败可由有权限的管理员或 HR 调用 `POST /resumes/{resume_id}/reparse` 重新解析。

### 指派部门评审

`POST /resumes/{resume_id}/department-reviews` 接收普通表单，要求管理员或 HR 身份：

```bash
export REVIEWER_ID='请替换为当前公司评审人UUID'

curl --fail-with-body -sS -X POST \
  "$API_BASE/resumes/$RESUME_ID/department-reviews" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "reviewer_id=$REVIEWER_ID" | jq
```

`/public/review/{token}` 系列接口仍要求评审人登录，并校验链接是否属于该账号；只有链接 Token 不能完成部门评审。

## 面试接口

### 查询面试

```bash
curl --fail-with-body -sS --get "$API_BASE/interviews" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'skip=0' \
  --data-urlencode 'limit=20' \
  --data-urlencode 'start=2026-11-01T00:00:00+08:00' \
  --data-urlencode 'end=2026-12-01T00:00:00+08:00' | jq
```

日期参数名是 `start` 和 `end`。`status` 可选值为 `scheduled`、`in_progress`、`analyzing`、`completed`、`cancelled`。返回结果按当前用户的可见范围过滤。

### 安排面试

`POST /interviews`，要求管理员或 HR 身份。创建 `interview.json`：

```json
{
  "resume_id": "请替换为实际简历UUID",
  "position_id": "请替换为该简历当前岗位UUID",
  "panel_members": ["请替换为当前公司面试官UUID"],
  "interview_time": "2026-11-02T10:00:00+08:00",
  "interview_end_time": "2026-11-02T11:00:00+08:00",
  "round": 1,
  "interview_type": "onsite",
  "interview_category": "technical",
  "interview_location": "上海办公室会议室 A",
  "question_count": 5,
  "skip_ai_questions": true,
  "skip_email": true
}
```

```bash
curl --fail-with-body -sS -X POST "$API_BASE/interviews" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @interview.json | jq
```

开始和结束时间必须位于同一北京时间自然日，结束时间晚于开始时间，分钟为 15 分钟刻度且秒为 0。岗位必须与简历当前岗位一致；面试官不可重复，排期冲突也会导致请求失败。

`onsite` 面试必须填写 `interview_location`；`video` 面试必须填写 `meeting_link`；另支持 `phone`。日期和用户 UUID 均应替换为实际值。

示例设置 `skip_ai_questions=true` 和 `skip_email=true`，会跳过 AI 生成题目和邀请邮件；需要这两项功能时，将对应值改为 `false`，并确保模型与邮件已配置。创建面试后，通过 `GET /interviews/{interview_id}` 查询详情和后续分析状态。

录音、人工评审、AI 分析和最终决策有各自的接口及状态要求。完整参数见 [接口手册](index.html#reference)。录音需按“预约会话、确认开始、发送心跳、分片上传、结束面试、封存录音”的顺序调用，并使用服务返回的 `session_id`。

## 文件和统计接口

### 下载受保护文件

使用简历返回的 `file_id` 下载文件，不能直接把 `file_path` 当作公开下载 URL：

```bash
export FILE_ID='请替换为实际文件UUID'

curl --fail-with-body -sS "$API_BASE/files/$FILE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -o resume-downloaded.pdf
```

需要临时分享文件时，有权限的用户可创建限时链接：

```bash
curl --fail-with-body -sS -X POST "$API_BASE/files/$FILE_ID/public-token" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"ttl_seconds":900}' | jq
```

`ttl_seconds` 默认 900，范围为 60 到 86400 秒。响应包含 `token`、`url` 和 `expires_at`。返回的 `url` 为 `/api/public/files/...` 相对路径，应拼接系统域名 `https://interview.careray.com`，无需再加一次 `/api`。链接在有效期内允许持有者下载，应按文件的实际可分享范围分发。

### 查询招聘统计

```bash
curl --fail-with-body -sS "$API_BASE/dashboard/stats" \
  -H "Authorization: Bearer $TOKEN" | jq

curl --fail-with-body -sS "$API_BASE/dashboard/funnel" \
  -H "Authorization: Bearer $TOKEN" | jq
```

`/dashboard/stats` 返回 `stats`、`recent_activities` 和 `interview_trends`。统计范围受当前用户权限限制。

## 异步与流式响应

简历解析、面试题生成和面试分析包含后台处理。收到创建成功响应后，应保存资源 ID，再通过详情接口查询处理状态。调用方应设置总等待时限，处理中不重复创建资源。

岗位描述的两个流式接口 `/positions/generate-jd-stream` 和 `/positions/chat-jd-stream` 返回 `text/event-stream`。每条 SSE 事件以空行分隔，`data:` 后为 JSON：

```text
data: {"content":"岗位职责内容片段"}

data: {"done":true}

```

按顺序拼接 `content`，收到 `done=true` 时结束。流内失败通过 `{"error":"AI 服务暂时不可用"}` 传递，因此收到 HTTP `200` 后仍需检查事件内容。不要对整个响应直接调用一次 JSON 解析。

## Python 调用示例

安装 `requests` 后运行下列代码。通过环境变量设置账号和密码；当前部署如未安装系统根证书，还需设置 `REQUESTS_CA_BUNDLE`。

```bash
export TENANT_CODE='your-company'
export API_EMAIL='你的登录邮箱'
# API_PASSWORD 由运行环境或交互输入设置
read -r -s -p '登录密码: ' API_PASSWORD
export API_PASSWORD
export REQUESTS_CA_BUNDLE='/path/to/ai-interview-root-ca.crt'
```

```python
import os
import requests

base = os.environ.get("API_BASE", "https://interview.careray.com/api").rstrip("/")
session = requests.Session()

response = session.post(
    f"{base}/auth/login",
    json={
        "tenant_code": os.environ["TENANT_CODE"],
        "email": os.environ["API_EMAIL"],
        "password": os.environ["API_PASSWORD"],
    },
    timeout=30,
)
response.raise_for_status()
session.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

response = session.get(f"{base}/auth/me", timeout=30)
response.raise_for_status()
print(response.json())

response = session.get(
    f"{base}/positions", params={"skip": 0, "limit": 20}, timeout=30
)
response.raise_for_status()
for position in response.json():
    print(position["id"], position["title"])
```

岗位列表示例使用管理员或 HR 账号。若业务请求超时，应先查询资源或任务状态，确认是否已经执行，再决定是否重试；创建、上传、发送邮件等请求不应直接重复提交。

## 错误处理

常见业务错误格式：

```json
{"detail":"公司、账号或密码错误"}
```

`detail` 也可能为结构化对象，例如排期冲突时包含 `message` 和 `conflicts`。调用方需按字段的实际类型处理。

参数校验错误通常返回 `422`，`detail` 为错误数组：

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "tenant_code"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

| 状态或现象 | 常见原因与处理 |
| --- | --- |
| curl 证书校验失败 | 信任公司根证书或指定正确的 CA 文件 |
| `400` | 业务校验失败，例如文件格式不符、岗位与简历不匹配；读取 `detail` |
| `401` | 登录失败、未携带 Token、Token 过期或凭据已更新；检查账号公司并重新登录 |
| `403` | 角色或资源权限不足、账号或公司被禁用、域名与公司不匹配 |
| `404` | 资源不存在、公开岗位未发布、链接无效，或资源不在当前可访问范围 |
| `409` | 业务冲突，例如重复资源或排期冲突；按响应说明调整请求 |
| `410` | 入口已停用，应向接口提供方确认当前业务流程 |
| `413` | 请求体或文件过大；减小单个文件或拆分批次 |
| `422` | 必填字段缺失、UUID 或日期错误、JSON 与表单类型不匹配 |
| `429` | 触发限流；按响应头 `Retry-After` 指定的秒数等待 |
| `500`、`502`、`504` | 后端异常、代理或上游服务异常；记录请求时间、路径和请求 ID 排查 |
| 返回 HTML 而非 JSON | 检查是否遗漏 `/api` 或拼错路径，按完整接口手册核对 URL |

后端响应提供 `X-Request-ID`，也可在请求中传入有效的 `X-Request-ID` 便于关联日志：

```bash
curl --fail-with-body -sS -D - "$API_BASE/auth/me" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Request-ID: integration-check-001'
```

登录、公开投递和公开笔试执行等接口有独立限流策略，具体阈值可由部署配置调整。

## 接口手册与客户端导入

[完整接口手册](index.html#reference)包含按业务模块整理的请求和响应字段。每个接口同时列明参数位置、类型、必填项、默认值、约束及可用角色；嵌套字段可通过数据模型链接查看。

将交付包中的 `openapi.json` 导入 Postman、Apifox 或支持 OpenAPI 3.1 的客户端，服务地址选择 `https://interview.careray.com`。定义已包含 `/api` 路径，不要在服务地址后重复追加 `/api`。登录后在客户端的 Bearer Token 设置中填写 `access_token`。

本交付包可离线查阅，不依赖在线 Swagger 页面。实际接口调用仍需要网络访问条件与相应账号权限。

## 联调与问题反馈

建议依次完成连通性检查、登录、身份确认、查询岗位，再在约定的测试账号和业务数据范围内验证写入流程。

出现问题时，请向接口提供方提交请求时间与时区、HTTP 方法、接口路径、HTTP 状态码、脱敏后的响应内容及响应头 `X-Request-ID`。不要提供密码、完整 Token、候选人原始简历或其他无关个人信息。

接口请求超时不代表操作未执行。对创建、投递、发送邮件和最终决策等操作，应先查询业务状态，避免重复执行。收到 `429` 时遵守 `Retry-After`；遇到参数和权限错误时，修正请求后再重试。

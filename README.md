# AI Interview

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Backend](https://img.shields.io/badge/backend-FastAPI-009688.svg)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-646CFF.svg)
![Database](https://img.shields.io/badge/database-PostgreSQL-336791.svg)
![AI](https://img.shields.io/badge/AI-OpenAI%20SDK%20compatible-7C3AED.svg)

AI Interview 是一个面向招聘团队的开源智能招聘管理系统。它把岗位发布、简历 AI 解析、候选人匹配评分、部门评审、AI 面试助手、在线笔试、Offer 管理、招聘漏斗和可视化工作流放进同一个产品里。

项目适合作为企业内部招聘中台的起点，也适合二次开发成 AI 面试、人才测评、招聘自动化或垂直行业人才管理产品。

![AI Interview 数据分析仪表盘](docs/assets/screenshots/dashboard.png)

## 为什么做这个项目

招聘流程里最耗时间的部分，往往不是点击按钮，而是反复阅读、整理和同步信息：简历要读，岗位要对齐，面试题要准备，面试反馈要汇总，候选人状态要推进，管理者还要看到漏斗数据。

AI Interview 的设计目标是让 AI 进入这些真实工作环节：

- 从简历中提取候选人画像，而不是只保存附件。
- 结合岗位要求生成匹配评分、风险点和面试关注点。
- 根据候选人背景生成结构化面试题。
- 汇总面试官评分、文字评价和转写内容，生成 AI 综合面试分析。
- 通过模型配置、提示词配置和工作流编排，让团队可以持续调优招聘策略。

## AI 能力展示

### 简历 AI 解析与匹配评分

上传简历后，系统会生成候选人基本信息、技能标签、岗位匹配分、初筛建议、风险提醒和可追问方向。HR 可以基于 AI 建议继续推进、转岗、淘汰或发起部门评审。

![简历 AI 分析结果](docs/assets/screenshots/resume-ai-analysis.png)

### AI 面试助手

面试评分页将候选人简历最大化展示在左侧，右侧提供 AI 生成的结构化题目、参考答案、评分标准和面试小组提交状态。面试官可以边看简历边评分，也可以上传录音并进入后续分析。

![AI 面试评分界面](docs/assets/screenshots/interview-score.png)

### 面试结果 AI 分析

面试完成后，系统会汇总多位面试官评分、评价文本、面试题表现和综合建议，生成可追踪的候选人评估报告，帮助 HR 和用人部门减少信息丢失。

![面试结果 AI 分析](docs/assets/screenshots/interview-ai-result.png)

### 模型与提示词可配置

系统支持 OpenAI SDK 兼容接口，默认适配 DashScope，也可以连接 OpenAI 或企业内部模型网关。管理员可以在页面中维护模型、Base URL、API Key 和不同任务的提示词模板。

![AI 模型配置](docs/assets/screenshots/ai-model-settings.png)

![AI 提示词配置](docs/assets/screenshots/prompt-settings.png)

## 功能亮点

| 模块 | 能力 |
| --- | --- |
| 岗位管理 | 岗位创建、公开发布、JD 生成、岗位统计、公开职位页 |
| 简历管理 | 单个/批量上传、重复检查、PDF 预览、AI 解析、匹配评分、转岗重评 |
| AI 初筛 | 候选人画像、初筛建议、风险点、岗位匹配解释、人工确认闭环 |
| 协同评审 | 用人部门评审链接、技术评价、HR 综合决策、淘汰原因归档 |
| 面试管理 | 多轮面试、面试小组、AI 题目生成、评分标准、录音上传、转写与综合评价 |
| 在线笔试 | 算法题、选择题、问答题、公开答题链接、代码运行和 AI 评价 |
| Offer 管理 | Offer 模板、发送、接受/拒绝确认、状态流转 |
| 招聘仪表盘 | 招聘漏斗、岗位分析、面试官分析、时间线趋势 |
| 工作流引擎 | React Flow 可视化编排，内置 LLM、条件、邮件、HTTP 等节点 |
| 系统设置 | LLM 配置、邮件配置、提示词管理、用户与角色管理 |

## 产品截图

### 候选人与岗位流程

![简历管理](docs/assets/screenshots/resumes.png)

![岗位管理](docs/assets/screenshots/positions.png)

![公开职位页](docs/assets/screenshots/public-job.png)

### 面试、笔试和自动化

![面试管理](docs/assets/screenshots/interviews.png)

![在线笔试](docs/assets/screenshots/coding-tests.png)

![工作流编排](docs/assets/screenshots/workflows.png)

## 技术栈

- 前端：React 19、Vite、TypeScript、Ant Design、React Router、Recharts、React Flow
- 后端：FastAPI、SQLAlchemy、Alembic、Pydantic、JWT、Background Tasks
- 数据库：PostgreSQL 15
- AI：OpenAI SDK 兼容接口，支持 DashScope、OpenAI 或企业内部兼容模型网关
- 文档与部署：Docker Compose、Nginx、GitHub Actions

![系统架构](docs/assets/architecture.svg)

## 快速开始

### 环境要求

- Node.js 20+
- Python 3.11+
- Docker Desktop 或本地 PostgreSQL 15+
- FFmpeg（用于音频处理；Docker 镜像已内置）

### 1. 准备环境变量

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

根据需要修改 `backend/.env` 中的 `SECRET_KEY`、`DATABASE_URL`、`INITIAL_ADMIN_PASSWORD`、`OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。LLM 也可以登录后在“系统设置”页面配置。

### 2. 启动数据库

```bash
docker compose up -d postgres
```

### 3. 启动后端

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端 API 文档：<http://localhost:8000/docs>

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。开发环境默认管理员为 `admin@example.com / admin123`，也可以通过 `INITIAL_ADMIN_EMAIL` 和 `INITIAL_ADMIN_PASSWORD` 自定义。

## 演示数据与截图

项目内置了演示数据、测试简历 PDF 和截图脚本，便于生成 README、博客或发布页素材。

```bash
# 1. 准备一个演示数据库
docker exec ai_interview_db sh -c "createdb -U postgres ai_interview_demo" || true

# 2. 写入岗位、候选人、AI 分析、面试、笔试、工作流等演示数据
cd backend
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/ai_interview_demo python scripts/seed_demo_data.py

# 3. 生成真实感测试简历 PDF
cd ..
node scripts/generate-demo-resume-pdfs.mjs

# 4. 启动前后端后，重新截取全部宣传图
node scripts/capture-demo-screenshots.mjs
```

截图会输出到 `docs/assets/screenshots/`。脚本默认使用 `admin@example.com / admin123` 登录本地应用，并覆盖生成仪表盘、简历 AI 分析、AI 面试评分、面试结果分析、模型配置、提示词配置等截图。

## Docker 部署

生产部署建议先修改根目录 `.env`，至少设置高强度 `SECRET_KEY` 和 `INITIAL_ADMIN_PASSWORD`。

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

默认访问地址为 <http://localhost>。前端 Nginx 会代理 `/api` 和 `/uploads` 到后端服务。

## 常用命令

```bash
make db              # 启动 PostgreSQL
make dev-backend     # 启动 FastAPI
make dev-frontend    # 启动 Vite
make test-backend    # 运行后端测试
make build-frontend  # 构建前端
make docker-prod     # 构建并启动生产 Compose
```

## 项目结构

```text
.
├── backend/                 # FastAPI API、模型、服务、路由、Alembic 迁移
├── frontend/                # React + Vite 前端应用
├── docs/                    # 宣传博客、产品图和架构图
├── scripts/                 # 演示简历 PDF 与截图生成脚本
├── docker-compose.yml       # 开发数据库
├── docker-compose.prod.yml  # 生产编排
└── Makefile                 # 常用开发命令
```

## 配置说明

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | 后端数据库连接串 |
| `SECRET_KEY` | JWT 签名密钥，生产环境必须设置 |
| `INITIAL_ADMIN_EMAIL` | 首次启动创建的管理员邮箱 |
| `INITIAL_ADMIN_PASSWORD` | 首次启动创建的管理员密码 |
| `CORS_ORIGINS` | 允许跨域来源，多个值用逗号分隔 |
| `OPENAI_API_KEY` | 兼容 OpenAI SDK 的模型服务密钥 |
| `OPENAI_BASE_URL` | 模型服务 Base URL |
| `LLM_PROVIDER` | 模型提供方标识，默认 `dashscope` |
| `LLM_MODEL` | 默认模型名 |
| `VITE_API_URL` | 前端 API 地址，默认 `/api` |

## 测试与质量

```bash
cd backend && pytest
cd frontend && npm run build
```

GitHub Actions 会在推送和 Pull Request 时运行后端测试与前端构建。

## 安全建议

- 生产环境务必修改 `SECRET_KEY`、管理员初始密码和数据库密码。
- 不要提交 `.env`、上传简历、音频、数据库文件或本地虚拟环境。
- 公开部署前建议接入 HTTPS、对象存储、日志审计和更细粒度的数据权限。
- AI 解析简历和面试内容时，请遵守候选人隐私、数据保留和本地法规要求。

## 路线图

- 多租户与组织隔离
- 更完整的权限策略和审计日志
- 简历解析队列的可观测性面板
- 更多招聘渠道集成
- 工作流节点插件市场
- 国际化和暗色模式

## 贡献

欢迎通过 Issue、Discussion 和 Pull Request 参与。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。

## License

MIT

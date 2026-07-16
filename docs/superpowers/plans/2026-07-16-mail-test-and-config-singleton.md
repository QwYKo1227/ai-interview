# 测试邮件与系统配置单例实施计划

> **面向执行智能体：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务执行；所有步骤使用复选框跟踪。

**目标：** 让管理员可通过 SMTP SSL 或 STARTTLS 向指定地址发送真实测试邮件，并将系统配置收敛为数据库强制保证的单例。

**架构：** 新增系统配置访问服务作为唯一配置读写入口；Alembic 迁移负责合并现有记录并建立单例约束。邮件服务根据持久化的安全模式选择 SSL 或 STARTTLS，设置页提交测试收件人并展示真实发送结果。

**技术栈：** FastAPI、SQLAlchemy、Alembic、Pydantic、Python `smtplib`/`ssl`、React、TypeScript、Ant Design、pytest、Vite。

## 全局约束

- 所有设计与代码注释使用中文；不记录或返回 SMTP 密码。
- `smtp_security` 只允许 `ssl` 和 `starttls`；存量记录默认 `ssl`。
- 测试收件人只用于当前请求，绝不持久化。
- 所有新增后端行为先写失败测试，再实现最小代码。
- 数据库迁移必须先合并重复记录，再建立唯一约束。

---

### 任务 1：系统配置单例模型、访问器与迁移

**文件：**
- 新建：`backend/app/services/system_config_service.py`
- 新建：`backend/alembic/versions/k1l2m3n4o5p6_make_system_config_singleton.py`
- 修改：`backend/app/models/models.py:404-430`
- 修改：`backend/app/routes/settings.py:1-190`
- 修改：`backend/app/services/mail_service.py:20-65`
- 修改：`backend/app/services/ai_service.py:1-40`
- 修改：`backend/app/utils/prompt_manager.py:235-250`
- 修改：`backend/app/routes/offers.py:88-100`
- 修改：`backend/app/services/resume_service.py:505-530`
- 修改：`backend/app/services/workflow_service.py:1-30`
- 测试：`backend/tests/test_system_config_service.py`

**接口：**
- 新增 `get_system_config(db: Session) -> SystemConfig`：返回唯一配置；不存在时创建。
- 新增 `consolidate_system_configs(db: Session) -> SystemConfig`：保留 `updated_at` 最新记录，补全其空字段并删除其余记录。
- `SystemConfig.singleton_key: bool`：唯一且恒为 `True`。
- `SystemConfig.smtp_security: str`：默认值 `"ssl"`。

- [ ] **步骤 1：写出单例访问器的失败测试**

在 `backend/tests/test_system_config_service.py` 创建两条配置：较新的记录缺少 `smtp_host`，较旧记录包含 `smtp_host`。断言调用 `consolidate_system_configs(db)` 后只剩一条记录，保留较新记录的 `id`，并得到较旧记录的 `smtp_host`。

```python
def test_consolidate_keeps_latest_config_and_fills_missing_values(db):
    older = SystemConfig(smtp_host="smtp.example.com", mail_enabled=True)
    newer = SystemConfig(mail_enabled=False)
    db.add_all([older, newer])
    db.commit()
    newer.updated_at = datetime.utcnow() + timedelta(seconds=1)
    db.commit()

    canonical = consolidate_system_configs(db)

    assert canonical.id == newer.id
    assert canonical.smtp_host == "smtp.example.com"
    assert db.query(SystemConfig).count() == 1
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_system_config_service.py -v`

预期：失败，提示无法导入 `consolidate_system_configs`。

- [ ] **步骤 3：实现访问器和模型字段**

在 `models.py` 的 `SystemConfig` 中加入：

```python
singleton_key = Column(Boolean, nullable=False, default=True, unique=True)
smtp_security = Column(String, nullable=False, default="ssl")
```

在 `system_config_service.py` 实现：按 `updated_at.desc(), id.desc()` 获取记录；对 `smtp_host`、`smtp_port`、`smtp_username`、`smtp_password`、`mail_from`、`mail_from_name`、`mail_enabled`、`smtp_security`、`frontend_url`、LLM 字段和 `prompt_configs` 执行“仅在主记录为空时补值”；删除其他记录；创建时捕获 `IntegrityError` 并重新读取唯一记录。将列出的所有 `.query(SystemConfig).first()` 替换为 `get_system_config(db)`。

- [ ] **步骤 4：编写并执行迁移**

迁移按以下顺序执行：添加可空 `singleton_key` 与带服务端默认值的 `smtp_security`；读取全部配置并保留最近更新的一条；从旧记录补齐空字段；删除旧记录；将保留记录的 `singleton_key` 更新为 `True`；将字段改为非空并增加唯一约束；在降级中删除约束和字段。

运行：`cd backend && alembic upgrade head`

预期：命令退出码为 0，`system_configs` 只剩一条记录。

- [ ] **步骤 5：运行单例测试并提交**

运行：`cd backend && pytest tests/test_system_config_service.py -v`

预期：所有测试通过。

```bash
git add backend/app backend/alembic/versions/k1l2m3n4o5p6_make_system_config_singleton.py backend/tests/test_system_config_service.py
git commit -m "fix: enforce a singleton system configuration"
```

### 任务 2：安全 SMTP 传输与真实测试邮件接口

**文件：**
- 修改：`backend/app/schemas/settings.py:15-40`
- 修改：`backend/app/services/mail_service.py:1-145`
- 修改：`backend/app/routes/settings.py:100-200`
- 测试：`backend/tests/test_settings_mail.py`

**接口：**
- 新增 `MailTestRequest(BaseModel)`，字段为 `recipient: EmailStr`。
- 新增 `MailService.send_test_email(recipient: str) -> bool`。
- `POST /api/settings/mail/test` 接收 `MailTestRequest`；成功返回 `{ "message": "测试邮件已发送" }`，SMTP 失败返回 HTTP 502。

- [ ] **步骤 1：写出 SSL、STARTTLS 和路由的失败测试**

在 `test_settings_mail.py` 中 monkeypatch `smtplib.SMTP_SSL` 与 `smtplib.SMTP`。SSL 用例断言前者被调用且 `starttls` 未被调用；STARTTLS 用例断言 `ehlo()`、`starttls(context=ANY)`、第二次 `ehlo()`、`login()` 和 `sendmail()` 都被调用。为管理员请求 `POST /api/settings/mail/test`，验证合法 `recipient` 返回 200、非法邮箱返回 422、模拟发送失败返回 502。

```python
def test_test_mail_route_sends_to_requested_recipient(client, db, admin_headers, monkeypatch):
    service = MagicMock()
    service.send_test_email.return_value = True
    monkeypatch.setattr("app.routes.settings.get_mail_service", lambda _db: service)

    response = client.post(
        "/api/settings/mail/test",
        headers=admin_headers,
        json={"recipient": "recipient@example.com"},
    )

    assert response.status_code == 200
    service.send_test_email.assert_called_once_with("recipient@example.com")
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_settings_mail.py -v`

预期：失败，提示请求体模型、`send_test_email` 或 502 响应尚不存在。

- [ ] **步骤 3：实现传输选择和测试邮件**

在 `MailConfigResponse` 和 `MailConfigUpdate` 中增加：

```python
smtp_security: Literal["ssl", "starttls"] = "ssl"
```

在 `MailService` 新增连接工厂：`ssl` 使用 `smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15)`；`starttls` 使用 `smtplib.SMTP(host, port, timeout=15)`，随后执行 `ehlo()`、`starttls(context=ssl.create_default_context())`、`ehlo()`。两种模式均执行 `login()` 和 `sendmail()`，并在 `finally` 中调用 `quit()`。`send_test_email` 使用固定主题“AI Interview SMTP 测试邮件”和 UTF-8 HTML 正文后调用现有发送逻辑。路由在 `False` 时抛出 `HTTPException(status_code=502, detail="SMTP 连接、认证或发送失败，请检查服务器日志和邮件设置")`。

- [ ] **步骤 4：运行邮件测试**

运行：`cd backend && pytest tests/test_settings_mail.py -v`

预期：所有用例通过，且测试过程不连接真实 SMTP 服务。

- [ ] **步骤 5：提交**

```bash
git add backend/app/schemas/settings.py backend/app/services/mail_service.py backend/app/routes/settings.py backend/tests/test_settings_mail.py
git commit -m "feat: send real SMTP test emails with SSL or STARTTLS"
```

### 任务 3：邮件设置页面

**文件：**
- 修改：`frontend/src/pages/Settings/System.tsx:10-40, 130-170, 300-335, 450-590`

**接口：**
- `MailSettings.smtp_security: "ssl" | "starttls"`。
- `mailForm.test_recipient: string` 仅作为测试请求数据。
- `testMail()` 调用 `request.post('/settings/mail/test', { recipient })`。

- [ ] **步骤 1：写出前端类型检查失败条件**

先在 `MailSettings` 和保存载荷中引用 `smtp_security`，并在 `testMail` 中引用尚未声明的 `test_recipient`。运行构建以确认 TypeScript 报错。

运行：`cd frontend && npm run build`

预期：失败，提示 `smtp_security` 或 `test_recipient` 不存在。

- [ ] **步骤 2：实现表单和真实测试请求**

导入 `Select`。加载设置时写入 `smtp_security: res.smtp_security || 'ssl'`；保存设置时提交 `smtp_security: values.smtp_security || 'ssl'`。在端口字段后插入 `Form.Item name="smtp_security"`，选项为 `ssl`（SMTP SSL）和 `starttls`（STARTTLS/TLS）。在配置表单末尾新增 `Form.Item name="test_recipient"`，规则为必填且 `type: 'email'`。把按钮文字改为“发送测试邮件”，`testMail` 先执行 `mailForm.validateFields(['test_recipient'])`，再发送 `{ recipient: values.test_recipient.trim() }`；成功提示“测试邮件已提交给 SMTP 服务端”。

- [ ] **步骤 3：构建前端**

运行：`cd frontend && npm run build`

预期：退出码为 0。

- [ ] **步骤 4：提交**

```bash
git add frontend/src/pages/Settings/System.tsx
git commit -m "feat: add configurable recipients for SMTP tests"
```

### 任务 4：完整验证与部署说明

**文件：**
- 修改：`README.md: Docker 部署章节`

- [ ] **步骤 1：执行后端完整测试**

运行：`cd backend && pytest -q`

预期：退出码为 0。

- [ ] **步骤 2：执行前端构建**

运行：`cd frontend && npm run build`

预期：退出码为 0。

- [ ] **步骤 3：以 Compose 验证迁移和容器健康**

运行：`docker compose -f docker-compose.prod.yml up -d --build && docker compose -f docker-compose.prod.yml ps`

预期：PostgreSQL 和后端健康，前端运行；执行 `docker compose -f docker-compose.prod.yml exec backend alembic upgrade head` 后系统配置仅有一条。

- [ ] **步骤 4：补充运维说明并提交**

在 README 写明：选择 SSL/465 或 STARTTLS/587；测试邮件会真实发往填写的收件人；更新部署时先执行 `alembic upgrade head`。

```bash
git add README.md
git commit -m "docs: describe secure SMTP test configuration"
```

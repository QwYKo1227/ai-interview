# 内网 Caddy HTTPS 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `https://interview.careray.com` 配置受客户端信任的内网 HTTPS，使浏览器允许面试录音页面访问麦克风。

**Architecture:** Caddy 容器占用宿主机 80/443，使用 `tls internal` 签发内网证书，并反向代理到同一 Compose 网络内的前端容器。Caddy 数据卷持久化内部 CA；将根证书导出并安装到访问终端的信任库。

**Tech Stack:** Docker Compose、Caddy 2、Caddyfile、现有 Nginx 前端容器、Linux、浏览器 WebRTC。

## 全局约束

- 域名固定为 `interview.careray.com`，DNS 必须解析到 `10.10.10.42`。
- 使用 Caddy `tls internal`，不得用浏览器忽略证书错误作为长期方案。
- Caddy 根证书仅通过内部受控渠道分发，不提交到 Git 仓库。
- 客户端未信任根证书前，不应将麦克风测试视为通过。
- 所有设计、部署说明和新增注释使用中文。

---

### 任务 1：新增 Caddy 反向代理与持久化 CA

**文件：**

- 创建：`Caddyfile`
- 修改：`docker-compose.prod.yml`
- 测试：`docker compose -f docker-compose.prod.yml config --no-interpolate`

**接口：**

- Caddy 对外监听 `80:80` 与 `443:443`。
- Caddy 将 HTTPS 请求转发至 Compose 服务 `frontend:80`。
- 前端服务不再直接向宿主机暴露 80 端口。

- [ ] **步骤 1：先验证当前编排不具备 HTTPS 入口**

运行：

```bash
docker compose -f docker-compose.prod.yml config --no-interpolate
```

预期：仅 `frontend` 服务映射 `80:80`，不存在 `caddy` 服务和 443 映射。

- [ ] **步骤 2：创建 Caddyfile**

写入：

```caddyfile
http://interview.careray.com {
    redir https://interview.careray.com{uri} permanent
}

https://interview.careray.com {
    tls internal
    header Permissions-Policy "microphone=(self)"
    reverse_proxy frontend:80
}
```

- [ ] **步骤 3：修改生产 Compose 编排**

将 `frontend` 服务中的端口映射删除，并新增：

```yaml
  caddy:
    image: caddy:2-alpine
    container_name: ai_interview_caddy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - frontend
    restart: always
```

在顶层 `volumes:` 中加入：

```yaml
  caddy_data:
  caddy_config:
```

- [ ] **步骤 4：验证编排**

运行：

```bash
docker compose -f docker-compose.prod.yml config --no-interpolate
```

预期：命令退出码为 0，`caddy` 映射 80/443，`frontend` 不再映射宿主机端口。

- [ ] **步骤 5：提交配置改动**

```bash
git add Caddyfile docker-compose.prod.yml
git commit -m "feat: add internal Caddy HTTPS proxy"
```

### 任务 2：编写根证书分发与客户端信任说明

**文件：**

- 创建：`docs/deployment/internal-caddy-ca.md`
- 修改：`.gitignore`
- 测试：检查证书导出目录未被 Git 跟踪。

**接口：**

- Caddy 容器中的 `/data/caddy/pki/authorities/local/root.crt` 是要分发的根证书。
- 导出的根证书保存到部署主机 `certs/caddy-local-root.crt`，该目录被 Git 忽略。

- [ ] **步骤 1：写出失败前置检查**

运行：

```bash
test -f certs/caddy-local-root.crt
```

预期：首次部署前退出码非 0，因为 Caddy 尚未签发内部 CA。

- [ ] **步骤 2：新增忽略规则与中文部署说明**

在 `.gitignore` 增加：

```gitignore
certs/
```

在说明中写明以下准确命令：

```bash
docker compose -f docker-compose.prod.yml cp caddy:/data/caddy/pki/authorities/local/root.crt certs/caddy-local-root.crt
```

并分别提供 Windows“受信任的根证书颁发机构”、macOS“系统钥匙串（始终信任）”、Linux 系统 CA 目录的安装步骤，以及“关闭并重启浏览器后再测试”的要求。

- [ ] **步骤 3：验证忽略规则**

运行：

```bash
git check-ignore certs/caddy-local-root.crt
```

预期：输出 `certs/caddy-local-root.crt`。

- [ ] **步骤 4：提交文档改动**

```bash
git add .gitignore docs/deployment/internal-caddy-ca.md
git commit -m "docs: document internal Caddy CA trust setup"
```

### 任务 3：部署、导出根证书并验证麦克风前置条件

**文件：**

- 使用：`Caddyfile`
- 使用：`docker-compose.prod.yml`
- 生成（不提交）：`certs/caddy-local-root.crt`

**接口：**

- 内网 DNS：`interview.careray.com -> 10.10.10.42`。
- HTTPS：`https://interview.careray.com`。
- 响应头：`Permissions-Policy: microphone=(self)`。

- [ ] **步骤 1：验证 DNS 与端口冲突**

在服务器运行：

```bash
getent hosts interview.careray.com
sudo ss -ltnp | grep -E ':(80|443)\s' || true
```

预期：DNS 返回 `10.10.10.42`；确认没有非本项目服务占用 443。

- [ ] **步骤 2：部署 Caddy**

在项目目录运行：

```bash
sudo docker compose -f docker-compose.prod.yml up --build -d
sudo docker compose -f docker-compose.prod.yml ps
```

预期：`ai_interview_caddy`、前端、后端和数据库均处于运行状态。

- [ ] **步骤 3：导出根证书**

运行：

```bash
mkdir -p certs
sudo docker compose -f docker-compose.prod.yml cp caddy:/data/caddy/pki/authorities/local/root.crt certs/caddy-local-root.crt
sudo chown "$USER":"$USER" certs/caddy-local-root.crt
test -s certs/caddy-local-root.crt
```

预期：`certs/caddy-local-root.crt` 存在且文件大小大于 0。

- [ ] **步骤 4：验证 HTTPS 和安全响应头**

在服务器运行：

```bash
curl -k -I https://interview.careray.com
curl -I http://interview.careray.com
```

预期：HTTPS 返回 200 且包含 `Permissions-Policy: microphone=(self)`；HTTP 返回 301 或 308 并跳转到 HTTPS。

- [ ] **步骤 5：完成客户端验证**

在一台已导入根证书的客户端浏览器中打开 `https://interview.careray.com`，在控制台执行：

```javascript
window.isSecureContext
```

预期：返回 `true`。进入面试评分页点击“开始录音”，浏览器显示麦克风权限提示；选择允许后录音开始。

- [ ] **步骤 6：提交部署说明中的最终状态**

```bash
git status --short
```

预期：只存在被忽略的 `certs/` 文件，不提交根证书或任何私钥。

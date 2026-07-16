# 任务 1 报告：内网 Caddy HTTPS 反向代理

## 变更

- 新增 `Caddyfile`：将 `http://interview.careray.com` 永久重定向至 HTTPS；HTTPS 站点使用 `tls internal`、限制麦克风权限策略，并反向代理至 `frontend:80`。
- 更新 `docker-compose.prod.yml`：移除 `frontend` 的宿主机 `80:80` 端口映射；新增 `caddy:2-alpine` 服务（容器名 `ai_interview_caddy`），公开 `80:80` 和 `443:443`，依赖 `frontend`，并使用 `restart: always`。
- 挂载只读 Caddyfile 与持久化 `caddy_data`、`caddy_config` 顶层卷，保存内部 CA 和 Caddy 配置状态。

## 验证

执行：

```powershell
docker compose -f docker-compose.prod.yml config --no-interpolate
```

结果：退出码 `0`。渲染配置包含 `caddy` 服务、镜像 `caddy:2-alpine`、容器名 `ai_interview_caddy`、宿主机发布端口 `80` 与 `443`、Caddyfile 只读绑定挂载、`caddy_data`/`caddy_config` 卷，以及对 `frontend` 的依赖；渲染后的 `frontend` 服务不含 `ports`。

另执行本地静态断言，逐项核对 Caddyfile 所需指令和上述渲染拓扑，结果：`PASS: required Caddyfile content and rendered Compose topology verified.`。`git diff --check` 未报告空白错误。

## 自审结论

变更范围仅限任务要求的 Caddyfile、生产 Compose 与本报告；未修改业务代码、Nginx、邮件或数据库配置，且未执行任何远程部署命令。Compose 输出有既有 `version` 字段已过时的警告；本任务未修改该无关字段。

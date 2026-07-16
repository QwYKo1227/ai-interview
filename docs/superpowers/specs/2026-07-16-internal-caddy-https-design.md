# 内网 Caddy HTTPS 与麦克风访问设计

## 目标

为内网域名 `interview.careray.com` 提供可信 HTTPS，使浏览器将面试录音页面视为安全上下文，从而允许调用麦克风。

## 现状与原因

现有部署仅暴露 80 端口，前端 Nginx 只提供 HTTP。浏览器在 HTTP 页面上会拒绝 `getUserMedia()`，而本地 `localhost` 属于浏览器的安全上下文例外，因此本地开发正常、Linux 部署访问失败。

## 架构

1. 新增 Caddy 容器，独占宿主机 80 和 443 端口。
2. Caddy 对 `http://interview.careray.com` 返回 HTTPS 重定向；对 `https://interview.careray.com` 使用 `tls internal` 签发证书，并反向代理到同一 Compose 网络中的前端容器。
3. 前端容器不再映射宿主机端口，仅允许 Caddy 在容器网络内访问其 80 端口；前端原有 Nginx 继续将 `/api` 和 `/uploads` 代理到后端。
4. Caddy 返回 `Permissions-Policy: microphone=(self)`，明确允许当前站点请求麦克风。
5. Caddy 的数据和配置目录使用具名卷持久化，确保内部 CA 根证书和站点证书在容器重建后保持稳定。

## 信任链与使用方式

`tls internal` 的证书由 Caddy 内部 CA 签发，不会自动受所有客户端信任。部署后从 Caddy 数据卷导出 `root.crt`，由 IT 或管理员安装到每台访问终端的受信任根证书库。

- Windows：导入“受信任的根证书颁发机构”。
- macOS：导入“系统”钥匙串并设为始终信任。
- Linux：安装至系统 CA 目录并更新证书库。

客户端完成信任后，通过 `https://interview.careray.com` 访问系统；浏览器会显示麦克风授权提示，用户选择允许即可录音。

## 验证与回滚

验证：确认 DNS 指向服务器；80/443 监听正常；HTTPS 证书链受终端信任；`window.isSecureContext` 为 `true`；浏览器可以请求并使用麦克风。

回滚：停止并移除 Caddy 服务、恢复前端的 80 端口映射。回滚会恢复 HTTP，但录音功能仍会被浏览器限制，因此仅用于紧急恢复页面访问。

# Caddy 内部根证书分发与客户端信任

本环境的 HTTPS 证书由 Caddy 的内部 CA 签发。客户端必须先信任该 CA 的根证书，才能正确使用受保护的页面功能（包括麦克风权限）。

## 导出根证书

Caddy 内部根证书位于容器中的以下路径：

```text
/data/caddy/pki/authorities/local/root.crt
```

在部署服务器上执行以下命令，将根证书导出到受控的本地目录：

```bash
mkdir -p certs
sudo docker compose -f docker-compose.prod.yml cp caddy:/data/caddy/pki/authorities/local/root.crt certs/caddy-local-root.crt
sudo chown "$USER":"$USER" certs/caddy-local-root.crt
```

根证书不得提交到 Git。请仅通过受控的内部渠道向需要访问该环境的用户分发 `certs/caddy-local-root.crt`。

## 客户端导入

### Windows

打开根证书文件，选择“安装证书”，将证书存储位置设为“本地计算机”（按组织权限要求操作），并导入到“受信任的根证书颁发机构”。完成后重启浏览器。

### macOS

在“钥匙串访问”中导入根证书到“系统”钥匙串。双击该证书，展开“信任”，将“使用此证书时”设置为“始终信任”，然后关闭并重新打开浏览器。

### Ubuntu/Debian

将证书复制到系统 CA 目录后更新证书存储：

```bash
sudo cp certs/caddy-local-root.crt /usr/local/share/ca-certificates/caddy-local-root.crt
sudo update-ca-certificates
```

完成后关闭并重新打开浏览器。

## 验证

客户端必须使用 `https://interview.careray.com` 访问应用。关闭并重新启动浏览器后，在开发者工具控制台确认：

```js
window.isSecureContext === true
```

结果应为 `true`。若不是，请确认访问地址、根证书的导入位置和浏览器重启步骤。

## 回滚

如需回滚，停止 Caddy 并恢复此前端口 `80` 映射即可恢复 HTTP。请注意：虽然页面可经 HTTP 访问，但浏览器仍会限制麦克风功能。

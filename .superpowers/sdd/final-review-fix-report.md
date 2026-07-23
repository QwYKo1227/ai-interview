# 平台控制台最终审查修复报告

日期：2026-07-23
分支：`codex/multi-tenant-saas`
审查基线：`e237cab`
实现提交：`3669deb fix: harden platform tenant console flows`

## 范围与约束核对

- 仅修改平台租户 onboarding schema、平台请求拦截器、公司列表、域名详情抽屉及其聚焦测试。
- 未修改 Docker、数据库 schema 或迁移，未运行迁移，未创建真实平台管理员、公司或持久化数据库数据。
- 平台请求仍只读取/清理 `platform_token`；测试显式验证公司 `token` 不被清理。
- 未回退或改写既有提交；独立提交 `a63b2b7` 保留在当前分支历史中。
- 保留 `TenantDetailDrawer` 既有 `scopeVersion`、`requestVersion` 与 `currentScope` 异步保护，没有放宽旧租户操作的 UI 写入条件。

## 逐项 TDD 记录

### 1. 前后端 UTF-8 密码契约一致

根因：`TenantOnboardingRequest.admin_password` 使用 `Field(min_length=12)` 按字符数预先拒绝输入，而自定义 validator 只检查 UTF-8 字节上限；`密A1abcdefg` 为 10 个字符、恰好 12 个 UTF-8 字节，因此在 validator 前被错误拒绝。

RED：

- 命令：`E:\ai-interview-main\.uv-cache\archive-v0\E6QG1lrDH-xh7Q-k\Scripts\python.exe -m pytest tests/test_tenant_onboarding.py -k "password_accepts_exactly_twelve_utf8_bytes or passwords_outside_utf8_byte_range or password_rejects_values_outside_utf8_byte_range" -q`
- 结果：`1 failed, 4 passed, 29 deselected`；schema 用例以 Pydantic `string_too_short` 失败。
- 命令：`E:\ai-interview-main\.uv-cache\archive-v0\E6QG1lrDH-xh7Q-k\Scripts\python.exe -m pytest tests/test_tenant_onboarding.py::test_platform_create_accepts_exactly_twelve_utf8_byte_password -q`
- 结果：`1 failed`；API 返回 `422`，预期 `201`。
- 环境说明：首次误用默认 Hermes Python 执行时提示 `No module named pytest`，该次未进入测试、不计作 RED；随后统一使用项目已有 uv 缓存环境。

最小修复：移除 `admin_password` 的字符数 `Field` 限制，由同一个 validator 统一检查 12–72 UTF-8 字节，再检查字母与数字字符类；新增的字节边界错误文案使用中文。

GREEN：

- 命令：`E:\ai-interview-main\.uv-cache\archive-v0\E6QG1lrDH-xh7Q-k\Scripts\python.exe -m pytest tests/test_tenant_onboarding.py -k "twelve_utf8 or utf8_byte_range" -q`
- 结果：`6 passed, 28 deselected`；覆盖 schema/API 的恰好 12 字节、少于 12 字节、超过 72 字节。

### 2. 平台 403 会话失效

根因：`platformRequest` 响应拦截器只把 401 视为会话失效，403 即使携带与当前 `platform_token` 相同的失败 Bearer 也不会清理或跳转。旧 token 和匿名登录端点保护原本由 Bearer 精确匹配与登录请求移除 Authorization 实现。

RED：

- 命令：`npm test -- --run src/utils/platformRequest.test.ts`
- 结果：`1 failed, 6 passed`；唯一失败为匹配当前 Bearer 的 403 未清理 `platform_token`。

最小修复：将会话失效状态扩展为 401 或 403，保留失败 Bearer 必须与当前 `platform_token` 相等的条件，继续只清理 `platform_token` 并跳转 `/platform/login`。

GREEN：

- 命令：`npm test -- --run src/utils/platformRequest.test.ts`
- 结果：`7 passed`；覆盖 401/403、公司 `token` 隔离、旧平台 token 的 403、平台登录匿名端点的 401/403。

### 3. 公司列表加载乱序保护

根因：每次 `loadTenants()` 都无条件更新 `tenants`、`hasError` 和 `loading`；旧请求的 `try/catch/finally` 可以在更新请求之后覆盖三组 state，effect 清理也没有使未完成请求失效。

RED：

- 命令：`npm test -- --run src/pages/Platform/Tenants.test.tsx -t "newest registry|settles after unmount"`
- 结果：选中的乱序成功用例 `1 failed`，卸载用例 `1 passed`；旧成功响应把“新公司”覆盖为“旧公司”。
- 命令：`npm test -- --run src/pages/Platform/Tenants.test.tsx -t "older load rejects last"`
- 结果：`1 failed, 17 skipped`；旧失败响应把最新成功列表替换成加载错误状态。

最小修复：增加 `loadGenerationRef`；每次加载取得新 generation，只有当前 generation 能更新 `tenants`、`hasError`、`loading`，组件卸载时递增 generation 使所有未完成请求失效。

GREEN：

- 命令：`npm test -- --run src/pages/Platform/Tenants.test.tsx -t "newest registry|successful registry|settles after unmount"`
- 结果：`3 passed, 15 skipped`；新请求先完成后，旧成功/旧失败均不能污染数据或错误态，卸载后的完成被忽略。

### 4. 域名管理能力完整

根因：新增域名保存分支把 `is_primary` 固定为 `false`；列表对主域名传入 `actions={undefined}`，在禁止删除/设主的同时也错误移除了编辑能力。

RED：

- 命令：`npm test -- --run src/pages/Platform/TenantDetailDrawer.test.tsx -t "adds a new domain as primary|edits the primary domain"`
- 结果：`2 failed, 15 skipped`；新增弹窗找不到“设为主域名”复选框，主域名条目找不到“编辑”按钮。

最小修复：仅在新增模式显示默认未选中的“设为主域名”，POST 透传 `{ domain, is_primary }`；所有域名保留编辑，只有备用域名追加“设为主域名”和“删除”，编辑 PATCH 仍只发送 `{ domain }`。

GREEN：

- 命令：`npm test -- --run src/pages/Platform/TenantDetailDrawer.test.tsx -t "adds a new domain as primary|edits the primary domain"`
- 结果：`2 passed, 15 skipped`。
- 兼容调整：主域名新增编辑后，5 个既有测试的全局唯一“编辑”选择器变为歧义；将这些测试收窄到 `careers.careray.com` 所属列表项，没有修改生产逻辑。
- 命令：`npm test -- --run src/pages/Platform/TenantDetailDrawer.test.tsx`
- 结果：`17 passed`；既有租户切换、关闭、延迟成功/失败竞态保护继续通过。

### 5. 新建公司成功反馈

根因：POST 成功路径已有表单重置、弹窗关闭和列表刷新，但没有任何成功反馈。

RED：

- 命令：`npm test -- --run src/pages/Platform/Tenants.test.tsx -t "shows success feedback"`
- 结果：`1 failed, 18 skipped`；找不到“公司创建成功”。

最小修复：POST 返回后先设置页面级中文 success Alert“公司创建成功”，再沿用表单重置、关闭弹窗、刷新列表的顺序；开始新提交或重新打开弹窗时清除旧反馈。

GREEN：

- 第一次 GREEN 复跑时成功消息已出现，但 jsdom 不会完成 Ant Design CSS 离场动画，物理节点仍以 `ant-zoom-leave` 暂留；将测试的关闭断言改为离场状态，继续验证刷新次数与重开后的空表单。这是测试环境适配，不是产品修复。
- 命令：`npm test -- --run src/pages/Platform/Tenants.test.tsx -t "shows success feedback"`
- 结果：`1 passed, 18 skipped`。

## 最终验证

### 后端聚焦 schema/API

- 命令：`E:\ai-interview-main\.uv-cache\archive-v0\E6QG1lrDH-xh7Q-k\Scripts\python.exe -m pytest tests/test_tenant_onboarding.py -q`
- 结果：`34 passed, 2 warnings`，退出码 0。
- 警告：既有 SQLAlchemy `declarative_base()` 和 PyPDF2 弃用警告；未由本次改动引入。

### 前端定向

- 命令：`npm test -- --run src/utils/platformRequest.test.ts src/pages/Platform/Tenants.test.tsx src/pages/Platform/TenantDetailDrawer.test.tsx`
- 结果：`3 test files passed, 43 tests passed`，退出码 0。
- 输出中两次 `Not implemented: navigation to another Document` 来自 jsdom 对现有 `window.location.href` 跳转的提示；401/403 token 行为断言均通过。

### 完整前端

- 命令：`npm test`
- 结果：`11 test files passed, 74 tests passed`，退出码 0。

### 构建

- 命令：`npm run build`
- 结果：TypeScript 与 Vite 构建通过，`4547 modules transformed`，退出码 0。
- 警告：主 bundle 超过 Vite 500 kB 提示阈值，为既有打包关注点，不属于本次平台修复范围。

### Diff 检查

- 命令：`git diff --check fa78459..HEAD`
- 结果：退出码 0；检查范围覆盖 `fa78459` 到最终修复提交，避免干净工作树下无范围命令漏检已提交内容。
- 实现提交前 staged 检查：`git diff --cached --check`，退出码 0。

### 文档格式复审修复

- 移除平台控制台设计文档和本报告 EOF 的多余空白行。
- 最终提交后使用 `git diff --check fa78459..HEAD` 复验累计提交范围，并单独核对 `git status --short` 为空。

## 提交

- `3669deb fix: harden platform tenant console flows`：8 个实现/测试文件，覆盖五项最终审查修复。
- 本报告单独提交；其提交哈希见最终回执（报告无法稳定自引用自身提交哈希）。

## 自审结论与关注点

- 五项验收条件均有聚焦回归测试，并实际观察到与缺陷一致的 RED 后完成最小修复与 GREEN。
- 最新列表 generation 同时保护 `tenants`、`hasError`、`loading`，effect 清理使卸载后的请求失效。
- 域名修改继续受租户 scope/version 保护；新能力没有绕过或替换既有竞态保护。
- 平台 401/403 只清理匹配失败 Bearer 的 `platform_token`，不触碰公司 `token`；旧 token 与匿名登录请求均受保护。
- 新增用户可见文案均为中文。
- 无剩余功能阻塞。非阻塞关注点仅为既有依赖/Ant Design 弃用提示、jsdom 导航提示和 Vite 大 chunk 警告。

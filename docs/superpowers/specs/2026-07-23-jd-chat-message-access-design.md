# JD 对话消息访问错误修复设计

## 背景与根因

`POST /api/positions/chat-jd-stream` 使用 `JDChatRequest` 校验请求。Pydantic 会将 `messages` 中的每个元素解析成 `JDChatMessage` 实例，但 `chat_jd_stream()` 当前仍以 `msg["role"]` 和 `msg["content"]` 的字典方式读取消息，因而在调用大模型之前抛出 `TypeError: 'JDChatMessage' object is not subscriptable`。

## 方案比较

1. 在服务层使用 `JDChatMessage` 的属性访问。改动最小，类型语义明确，且与路由实际传入的数据一致。采用此方案。
2. 在路由层先对所有消息调用 `model_dump()`。可以继续让服务层接收字典，但会在路由与服务之间增加不必要的转换，并保留宽泛的 `list` 接口。
3. 让服务层同时兼容字典和 Pydantic 对象。兼容面更大，但当前没有字典调用方，会引入无需求支持的分支。

## 设计

- 将 `chat_jd_stream()` 的消息参数标注为 `List[JDChatMessage]`。
- 构造 OpenAI 消息时通过 `msg.role` 和 `msg.content` 读取字段。
- 不修改请求 JSON、SSE 响应格式、前端状态管理或提示文案。
- 保留当前异常捕获行为，避免把本次类型修复扩展为错误处理重构。

## 测试

- 新增服务层回归测试，传入真实 `JDChatMessage` 实例。
- 替换配置和模型客户端依赖，使测试只验证消息转换和流式输出，不访问数据库或外部 AI 服务。
- 修复前，测试应收到包含 `not subscriptable` 的 SSE 错误；修复后，应确认模型客户端收到系统消息和用户消息，并正常输出完成事件。
- 运行新增测试及后端完整测试集，确认没有回归。

## 成功标准

用户生成 JD 后发送修改要求时，后端能够把 Pydantic 消息对象正确转换为模型消息，不再返回 `JDChatMessage object is not subscriptable`，且既有接口协议保持不变。

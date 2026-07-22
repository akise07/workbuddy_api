# CodeBuddy CN -> OpenAI Compatible API Proxy

将腾讯云 CodeBuddy CN 的聊天 API 封装为标准 OpenAI 兼容格式，可接入任何支持 OpenAI API 的客户端。

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

## 配置

### 1. OAuth2 登录获取 Token

浏览器访问：`http://localhost:8000/auth/start`

复制返回的 `auth_url` 在浏览器中打开，登录你的 CodeBuddy 账号并授权。

### 2. 轮询获取 Token

浏览器访问返回的 `poll_url`，看到 `"status": "success"` 即表示 Token 已保存。

### 3. 开始使用

```bash
# 非流式
curl http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"deepseek-v3\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}"

# 流式
curl http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"deepseek-v3\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}],\"stream\":true}"
```

### Python SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="any")
resp = client.chat.completions.create(
    model="deepseek-v3",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)
```

## 可用模型

| 模型 | 状态 |
|------|------|
| `deepseek-v3` | ✅ 可用 |
| `claude-4.0` | ✅ 可用 |
- 注：CN支持什么模型就能用什么模型！


## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/auth/start` | GET | 启动 OAuth2 登录 |
| `/auth/poll?auth_state=xxx` | GET | 轮询获取 Token |
| `/auth/manual` | POST | 手动设置 Bearer Token |
| `/auth/status` | GET | 查看凭证状态 |
| `/v1/chat/completions` | POST | 聊天补全（OpenAI 兼容） |
| `/v1/models` | GET | 模型列表 |

## 环境变量

```env
PORT=8000              # 服务端口
API_PASSWORD=           # 代理访问密码（可选）
```

## 兼容客户端

支持所有 OpenAI 兼容客户端：ChatGPT-Next-Web、LobeChat、Cherry Studio、Cursor 等。

## 免责声明

本项目仅供学习交流使用，使用请遵守腾讯云 CodeBuddy 相关服务条款。
开发者不对因使用本项目导致的账号封禁、API 限制等后果承担责任。

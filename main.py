"""
CodeBuddy CN to OpenAI Compatible API Proxy v3

Authentication: OAuth2 Device Flow via copilot.tencent.com/v2/plugin/auth/state
Upstream: copilot.tencent.com/v2/chat/completions

Usage:
  1. Start server: python main.py
  2. Visit: http://localhost:8000/auth/start
  3. Open the returned auth_url in browser, login
  4. Poll: http://localhost:8000/auth/poll?auth_state=xxx
  5. Use: POST http://localhost:8000/v1/chat/completions
"""

import sys
import os

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import time
import uuid
import secrets
import logging
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from contextlib import asynccontextmanager

load_dotenv()

# ─── Config ─────────────────────────────────────────────
PORT = int(os.getenv("PORT", "8000"))
API_PASSWORD = os.getenv("API_PASSWORD", "")
CK_API_KEY = os.getenv("CODEBUDDY_API_KEY", "")

CODEBUDDY_BASE = "https://copilot.tencent.com"
AUTH_STATE_URL = f"{CODEBUDDY_BASE}/v2/plugin/auth/state"
AUTH_TOKEN_URL = f"{CODEBUDDY_BASE}/v2/plugin/auth/token"
CHAT_URL = f"{CODEBUDDY_BASE}/v2/chat/completions"

CREDS_DIR = Path(os.getenv("CREDS_DIR", ".codebuddy_creds"))
CREDENTIALS_FILE = CREDS_DIR / "token.json"

# ─── Logging ────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Models ─────────────────────────────────────────────
AVAILABLE_MODELS = [
    {"id": "deepseek-v3", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
    {"id": "claude-4.0", "object": "model", "created": 1700000000, "owned_by": "anthropic"},
    {"id": "gpt-4o", "object": "model", "created": 1700000000, "owned_by": "openai"},
    {"id": "gpt-5", "object": "model", "created": 1700000000, "owned_by": "openai"},
    {"id": "o4-mini", "object": "model", "created": 1700000000, "owned_by": "openai"},
    {"id": "gemini-2.5-pro", "object": "model", "created": 1700000000, "owned_by": "google"},
    {"id": "gemini-2.5-flash", "object": "model", "created": 1700000000, "owned_by": "google"},
]

# ─── Token Management ──────────────────────────────────
def load_token():
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(CREDENTIALS_FILE.read_text("utf-8"))
        bearer = data.get("bearer_token") or data.get("access_token")
        if not bearer:
            return None
        expires = data.get("expires_at", 0)
        if expires and time.time() > expires:
            logger.info("Token expired")
            return None
        return data
    except Exception:
        return None

def save_token(data):
    CREDS_DIR.mkdir(exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

def get_bearer_token():
    data = load_token()
    return data.get("bearer_token") or data.get("access_token") if data else None

def get_user_id():
    data = load_token()
    return data.get("user_id", "") if data else ""

# ─── HTTP Client ───────────────────────────────────────
http_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0, read=300.0, write=30.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=True,
    )
    logger.info("CodeBuddy CN -> OpenAI API Proxy v3 started at http://0.0.0.0:%d", PORT)
    if load_token():
        logger.info("Token loaded from disk")
    else:
        logger.info("No token. Visit /auth/start to login via OAuth2")
    yield
    await http_client.aclose()

app = FastAPI(title="CodeBuddy CN to OpenAI API", version="3.0.0", lifespan=lifespan)

# ─── API Key Auth ───────────────────────────────────────
async def verify_api_key(request: Request):
    if not API_PASSWORD:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if auth[7:] != API_PASSWORD:
        raise HTTPException(status_code=403, detail="Invalid API key")

# ─── Auth Headers (from codebuddyCN2api source) ────────
def _auth_start_headers():
    return {
        "Host": "copilot.tencent.com",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "close",
        "X-Requested-With": "XMLHttpRequest",
        "X-Domain": "copilot.tencent.com",
        "X-No-Authorization": "true",
        "X-No-User-Id": "true",
        "X-No-Enterprise-Id": "true",
        "X-No-Department-Info": "true",
        "User-Agent": "CLI/1.0.8 CodeBuddy/1.0.8",
        "X-Product": "SaaS",
        "X-Request-ID": str(uuid.uuid4()).replace("-", ""),
    }

def _auth_poll_headers():
    rid = str(uuid.uuid4()).replace("-", "")
    span = secrets.token_hex(8)
    return {
        "Host": "copilot.tencent.com",
        "Accept": "application/json, text/plain, */*",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "close",
        "X-Requested-With": "XMLHttpRequest",
        "X-Request-ID": rid,
        "b3": "{}-{}-1-".format(rid, span),
        "X-B3-TraceId": rid,
        "X-B3-ParentSpanId": "",
        "X-B3-SpanId": span,
        "X-B3-Sampled": "1",
        "X-No-Authorization": "true",
        "X-No-User-Id": "true",
        "X-No-Enterprise-Id": "true",
        "X-No-Department-Info": "true",
        "X-Domain": "copilot.tencent.com",
        "User-Agent": "CLI/1.0.8 CodeBuddy/1.0.8",
        "X-Product": "SaaS",
    }

# ─── OAuth2 Device Flow ───────────────────────────────
@app.get("/auth/start")
async def auth_start():
    """Step 1: Get auth state and verification URL"""
    try:
        nonce = secrets.token_hex(8)
        url = "{}?platform=CLI&nonce={}".format(AUTH_STATE_URL, nonce)
        headers = _auth_start_headers()

        resp = await http_client.post(url, json={"nonce": nonce}, headers=headers)
        data = resp.json()
        logger.info("auth/state response: %s", json.dumps(data, ensure_ascii=False)[:200])

        if resp.status_code == 200 and data.get("code") == 0 and data.get("data"):
            d = data["data"]
            auth_state = d.get("state")
            auth_url = d.get("authUrl")
            if auth_state and auth_url:
                return {
                    "success": True,
                    "auth_state": auth_state,
                    "auth_url": auth_url,
                    "message": "Please open auth_url in browser and login",
                    "poll_url": "http://localhost:{}/auth/poll?auth_state={}".format(PORT, auth_state),
                }

        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "auth_start_failed",
            "detail": data,
        })
    except Exception as e:
        logger.error("auth start error: %s", str(e))
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.get("/auth/poll")
async def auth_poll(auth_state: str):
    """Step 2: Poll for token after user logs in"""
    try:
        url = "{}?state={}".format(AUTH_TOKEN_URL, auth_state)
        headers = _auth_poll_headers()

        resp = await http_client.get(url, headers=headers)
        data = resp.json()

        if data.get("code") == 11217:
            return {"status": "pending", "message": "Waiting for login...", "code": 11217}

        if data.get("code") == 0 and data.get("data"):
            d = data["data"]
            access_token = d.get("accessToken")
            if access_token:
                token_data = {
                    "bearer_token": access_token,
                    "access_token": access_token,
                    "refresh_token": d.get("refreshToken"),
                    "token_type": d.get("tokenType", "Bearer"),
                    "expires_in": d.get("expiresIn"),
                    "domain": d.get("domain"),
                    "session_state": d.get("sessionState"),
                    "created_at": int(time.time()),
                    "expires_at": int(time.time()) + (d.get("expiresIn") or 3600),
                    "user_id": d.get("domain", ""),
                }
                # Try to extract user info from JWT
                try:
                    parts = access_token.split(".")
                    if len(parts) >= 2:
                        import base64
                        payload_b64 = parts[1]
                        payload_b64 += "=" * (4 - len(payload_b64) % 4)
                        jwt_data = json.loads(base64.urlsafe_b64decode(payload_b64))
                        token_data["user_id"] = (
                            jwt_data.get("email")
                            or jwt_data.get("preferred_username")
                            or jwt_data.get("sub")
                            or d.get("domain", "")
                        )
                except Exception:
                    pass

                save_token(token_data)
                return {
                    "status": "success",
                    "message": "Login success! Token saved.",
                    "user_id": token_data["user_id"],
                    "expires_at": token_data["expires_at"],
                }

        return JSONResponse(status_code=400, content={
            "status": "error",
            "detail": data,
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/auth/manual")
async def auth_manual(request: Request):
    """Manually set a bearer token (e.g., captured from browser)"""
    body = await request.json()
    bearer_token = body.get("bearer_token", "").strip()
    if not bearer_token:
        return JSONResponse(status_code=400, content={"error": "bearer_token is required"})
    token_data = {
        "bearer_token": bearer_token,
        "access_token": bearer_token,
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + 86400,
    }
    try:
        import base64
        parts = bearer_token.split(".")
        if len(parts) >= 2:
            p = parts[1] + "=" * (4 - len(parts[1]) % 4)
            jwt_data = json.loads(base64.urlsafe_b64decode(p))
            token_data["user_id"] = jwt_data.get("email") or jwt_data.get("sub", "")
            exp = jwt_data.get("exp")
            if exp:
                token_data["expires_at"] = exp
    except Exception:
        pass
    save_token(token_data)
    return {"status": "success", "message": "Token saved", "user_id": token_data.get("user_id", "")}

@app.get("/auth/status")
async def auth_status():
    token = load_token()
    if not token:
        return {"has_token": False, "message": "No token. Visit /auth/start"}
    return {
        "has_token": True,
        "user_id": token.get("user_id", ""),
        "expires_at": token.get("expires_at", 0),
        "created_at": token.get("created_at", 0),
    }

# ─── Build Upstream Headers ───────────────────────────
def build_upstream_headers(model):
    return {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-B3-ParentSpanId": "",
        "X-B3-Sampled": "1",
        "X-Agent-Intent": "CodeCompletion",
        "X-Env-ID": "production",
        "X-Domain": "copilot.tencent.com",
        "X-Product": "SaaS",
        "X-User-Id": get_user_id(),
        "X-Machine-Id": str(uuid.uuid4()),
        "X-Request-ID": str(uuid.uuid4()),
    }

# ─── Models Endpoint ───────────────────────────────────
@app.get("/v1/models", dependencies=[Depends(verify_api_key)])
async def list_models():
    return {"object": "list", "data": AVAILABLE_MODELS}

# ─── Chat Completions ─────────────────────────────────
@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request):
    bearer = get_bearer_token()
    if not bearer:
        return JSONResponse(status_code=401, content={
            "error": {"message": "No token. Visit /auth/start to login first.", "type": "auth_required"}
        })

    body = await request.json()
    is_stream = body.get("stream", False)
    model = body.get("model", "auto-chat")
    messages = body.get("messages", [])

    payload = {"model": model, "messages": messages, "stream": True}
    for k in ("temperature", "max_tokens", "tools", "tool_choice"):
        if k in body:
            payload[k] = body[k]

    # Pass through reasoning/thinking parameters to enable thinking mode
    for k in ("reasoning_effort", "thinking", "reasoning"):
        if k in body:
            payload[k] = body[k]

    # Ensure at least 2 messages
    if len(payload["messages"]) < 2:
        payload["messages"].insert(0, {"role": "system", "content": "You are a helpful assistant."})

    headers = build_upstream_headers(model)
    headers["Authorization"] = "Bearer {}".format(bearer)

    if is_stream:
        return StreamingResponse(
            _stream_response(payload, headers, model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    else:
        return await _non_stream_response(payload, headers, model)

async def _stream_response(payload, headers, model):
    request_id = "chatcmpl-{}".format(uuid.uuid4().hex[:12])
    try:
        async with http_client.stream("POST", CHAT_URL, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                err_text = err.decode("utf-8", errors="replace")[:300]
                logger.error("upstream error %s: %s", resp.status_code, err_text)
                yield "data: {}\n\n".format(json.dumps({
                    "error": {"message": "upstream {}: {}".format(resp.status_code, err_text), "type": "upstream_error"}
                }, ensure_ascii=False))
                yield "data: [DONE]\n\n"
                return
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data_str = line
                if data_str.startswith("data: "):
                    data_str = data_str[6:]
                elif data_str.startswith("data:"):
                    data_str = data_str[5:]
                if not data_str or data_str.strip() == "[DONE]":
                    if data_str.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                    continue
                try:
                    chunk = json.loads(data_str)
                    if "choices" in chunk:
                        chunk["model"] = model
                        if not chunk.get("id"):
                            chunk["id"] = request_id
                        yield "data: {}\n\n".format(json.dumps(chunk, ensure_ascii=False))
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.error("stream error: %s", str(e))
        yield "data: {}\n\n".format(json.dumps({
            "error": {"message": str(e), "type": "proxy_error"}
        }, ensure_ascii=False))
        yield "data: [DONE]\n\n"

async def _non_stream_response(payload, headers, model):
    request_id = "chatcmpl-{}".format(uuid.uuid4().hex[:12])
    content_parts = []
    reasoning_parts = []
    tool_calls = []
    finish_reason = "stop"
    prompt_tokens = 0
    completion_tokens = 0

    try:
        async with http_client.stream("POST", CHAT_URL, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                err_text = err.decode("utf-8", errors="replace")[:300]
                logger.error("upstream error %s: %s", resp.status_code, err_text)
                return JSONResponse(status_code=resp.status_code, content={
                    "error": {"message": err_text, "type": "upstream_error"}
                })
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data_str = line
                if data_str.startswith("data: "):
                    data_str = data_str[6:]
                elif data_str.startswith("data:"):
                    data_str = data_str[5:]
                if not data_str or data_str.strip() == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data_str)
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        c = delta.get("content")
                        if c:
                            content_parts.append(c)
                        # Accumulate reasoning_content from delta
                        rc = delta.get("reasoning_content")
                        if rc:
                            reasoning_parts.append(rc)
                        tc = delta.get("tool_calls")
                        if tc:
                            for t in tc:
                                idx = t.get("index", len(tool_calls))
                                while len(tool_calls) <= idx:
                                    tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                                if t.get("id"):
                                    tool_calls[idx]["id"] = t["id"]
                                if t.get("function"):
                                    f = t["function"]
                                    if f.get("name"):
                                        tool_calls[idx]["function"]["name"] += f["name"]
                                    if f.get("arguments"):
                                        tool_calls[idx]["function"]["arguments"] += f["arguments"]
                        fr = choice.get("finish_reason")
                        if fr:
                            finish_reason = fr
                    u = chunk.get("usage")
                    if u:
                        prompt_tokens = u.get("prompt_tokens", prompt_tokens)
                        completion_tokens = u.get("completion_tokens", completion_tokens)
                except json.JSONDecodeError:
                    pass

        msg = {"role": "assistant", "content": "".join(content_parts) or None}
        if reasoning_parts:
            msg["reasoning_content"] = "".join(reasoning_parts)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return JSONResponse(content={
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        })
    except Exception as e:
        logger.error("non-stream error: %s", str(e))
        return JSONResponse(status_code=500, content={
            "error": {"message": str(e), "type": "proxy_error"}
        })

# ─── Health & Root ────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "codebuddy-cn2openai", "version": "3.0.0"}

@app.get("/")
async def root():
    return {
        "service": "CodeBuddy CN -> OpenAI API Proxy",
        "version": "3.0.0",
        "upstream": CHAT_URL,
        "auth": "OAuth2 Device Flow",
        "has_token": load_token() is not None,
        "endpoints": {
            "auth_start": "GET /auth/start",
            "auth_poll": "GET /auth/poll?auth_state=xxx",
            "auth_manual": "POST /auth/manual  (set bearer token directly)",
            "auth_status": "GET /auth/status",
            "chat": "POST /v1/chat/completions",
            "models": "GET /v1/models",
        },
        "usage": {"base_url": "http://localhost:{}/v1".format(PORT)},
    }

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 50)
    print("  CodeBuddy CN -> OpenAI API Proxy v3")
    print("  URL: http://localhost:{}".format(PORT))
    print("  Auth: http://localhost:{}/auth/start".format(PORT))
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT)

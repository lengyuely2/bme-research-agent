"""Account model discovery and safe API diagnostics. Never stringify SDK error bodies."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .safety import SafetyError

MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

QUOTA_CODES = {"insufficient_quota", "billing_hard_limit_reached", "credit_balance_exhausted"}
SPEND_CODES = {"organization_spend_limit_exceeded", "project_spend_limit_exceeded"}
USAGE_CODES = {"organization_usage_limit_exceeded"}
RATE_CODES = {"rate_limit_exceeded", "slow_down"}
SAFE_CODES = QUOTA_CODES | SPEND_CODES | USAGE_CODES | RATE_CODES | {
    "model_not_found", "invalid_api_key", "permission_denied", "unsupported_parameter",
    "invalid_request_error", "server_error", "server_is_overloaded", "context_length_exceeded",
    "invalid_prompt", "content_policy_violation", "max_output_tokens", "insufficient_permissions",
}


class RemoteAPIError(Exception):
    """Carry structured stream failure fields without keeping the remote message or payload."""

    def __init__(self, error=None, *, request_id="", status=None):
        super().__init__("Remote API response failed")
        read = error.get if isinstance(error, dict) else lambda key, default=None: getattr(error, key, default)
        code, error_type = read("code"), read("type")
        self.body = {"code": code if isinstance(code, str) and code in SAFE_CODES else "",
                     "type": error_type if isinstance(error_type, str) and error_type in {"insufficient_quota", "rate_limit_error"} else ""}
        self.request_id = request_id
        self.status_code = status if isinstance(status, int) and 400 <= status <= 599 else None


def normalize_key(value: str) -> str:
    if not isinstance(value, str):
        raise SafetyError("API Key 必须是文本。")
    value = value.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if (not 12 <= len(value) <= 512 or not value.isascii()
            or any(c.isspace() for c in value) or "://" in value):
        raise SafetyError("请输入完整的 API Key 本身；不要填 API 网址、引号或空格。")
    return value


def discover_models(client) -> tuple[str, ...]:
    blocked = ("audio", "realtime", "transcrib", "tts", "image", "embedding", "moderation", "search-preview")
    items = []
    today = datetime.now(timezone.utc).date().isoformat()
    for item in client.models.list():
        name = item.id
        if (MODEL_ID.fullmatch(name) and not name.startswith("sk-")
                and (name.startswith(("gpt-", "chatgpt-")) or re.match(r"o[1-9](?:-|$)", name))
                and not any(word in name.lower() for word in blocked)
                and not (isinstance(getattr(item, "shutdown_date", None), str)
                         and item.shutdown_date[:10] <= today)):
            items.append((name, getattr(item, "created", 0)))
    items.sort(key=lambda pair: (bool(re.search(r"-\d{4}-\d{2}-\d{2}$", pair[0])), -pair[1], pair[0]))
    return tuple(dict.fromkeys(name for name, _ in items))


def error_details(exc: Exception) -> dict:
    name = type(exc).__name__
    body = getattr(exc, "body", None)
    body = body.get("error", body) if isinstance(body, dict) else {}
    code = body.get("code", "") if isinstance(body, dict) else ""
    code = code if isinstance(code, str) and code in SAFE_CODES else ""
    error_type = body.get("type", "") if isinstance(body, dict) else ""
    status = getattr(exc, "status_code", None)
    message = "本地接口处理异常，请复制诊断信息以定位原因。"
    kind = "operation_error"
    if isinstance(exc, SafetyError):
        kind, message = "validation", str(exc)
    elif name == "AuthenticationError" or code == "invalid_api_key" or status == 401:
        kind, message = "authentication", "API Key 无效或已失效。请确认使用 OpenAI Platform 的 API Key，并重新加载模型。"
    elif name == "PermissionDeniedError" or code in {"permission_denied", "insufficient_permissions"} or status == 403:
        kind, message = "permission", "账户、项目、地区或密钥权限不允许此请求，请在 OpenAI Platform 检查访问权限。"
    elif name == "NotFoundError" or code == "model_not_found":
        kind, message = "model_not_found", "当前模型不存在、已停用或本项目无权使用。请重新加载账户模型列表并选择其中的模型，不要使用旧版默认名称。"
    elif code in QUOTA_CODES or (not code and error_type == "insufficient_quota"):
        kind, message = "quota", "API 余额或可用额度不足。请检查 OpenAI Platform 的 Billing 和额度；重复点击、等待或换模型通常不能解决余额问题。"
    elif code in SPEND_CODES:
        kind, message = "spend_limit", "项目或组织已达到消费上限。请在 OpenAI Platform 检查对应的消费限制。"
    elif code in USAGE_CODES:
        kind, message = "usage_limit", "组织已达到平台分配的用量上限。请检查 Limits 或申请提高额度。"
    elif code in RATE_CODES or name == "RateLimitError" or status == 429 or error_type == "rate_limit_error":
        kind, message = "rate_limit", "请求达到速率限制，请按提示稍后重试，并检查项目的模型速率额度；不要连续点击发送。"
    elif name in {"APIConnectionError", "APITimeoutError"}:
        kind, message = "network", "无法连接 OpenAI API 或请求超时。当前使用直连官方 API；请检查网络是否能访问 api.openai.com。"
    elif name in {"InternalServerError"} or (isinstance(status, int) and status >= 500) or code in {"server_error", "server_is_overloaded"}:
        kind, message = "server", "OpenAI 服务暂时出错或繁忙，请稍后重试。"
    elif code == "context_length_exceeded":
        kind, message = "context_limit", "问题与上下文超过模型限制，请新建任务或减少资料后重试。"
    elif name == "BadRequestError" or status == 400 or code in {"unsupported_parameter", "invalid_request_error"}:
        kind, message = "request", "模型可见，但不接受当前 Responses/工具调用参数。请使用“发送测试请求”检查兼容性，或选择其他文本模型。"
    elif name in {"RuntimeError", "ValueError"}:
        kind, message = "incomplete", "模型输出未完整完成，或本地数据不符合操作要求。请缩小问题或检查数据后重试。"
    elif name in {"APIError", "RemoteAPIError"}:
        kind, message = "api_error", "API 在生成过程中返回错误。请复制下方诊断信息，其中包含可安全显示的错误代码。"
    elif name in {"ModuleNotFoundError", "ImportError"}:
        kind, message = "installation", "本地运行库不完整，请使用新版程序的完整文件夹，不能只复制 EXE。"
    request_id = getattr(exc, "request_id", "") or ""
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{0,100}", request_id):
        request_id = ""
    return {"kind": kind, "message": message, "code": code,
            "status": status if isinstance(status, int) else None, "request_id": request_id,
            "exception": name if name in {"APIError", "RemoteAPIError", "RateLimitError", "BadRequestError",
                "NotFoundError", "AuthenticationError", "PermissionDeniedError", "APIConnectionError",
                "APITimeoutError", "InternalServerError", "RuntimeError", "ValueError", "TypeError",
                "AttributeError", "KeyError", "IndexError", "AssertionError", "ModuleNotFoundError",
                "ImportError", "OSError", "SafetyError", "APIStatusError"} else "UnknownError"}

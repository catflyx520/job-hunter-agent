"""从数据库设定建出 provider，并依任务路由选模型。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.llm.api_providers import AnthropicProvider, OllamaProvider, OpenAICompatibleProvider, OpenAIProvider
from app.llm.base import EMBEDDING_KINDS, Capabilities, LLMError, LLMProvider
from app.llm.cli_providers import ClaudeCliProvider, CodexCliProvider
from app.models import LLMProvider as ProviderRow
from app.models import TaskRoute

TASK_LABELS = {
    "resume_parse": "履历结构化",
    "resume_review": "履历评分",
    "job_extract": "职位资料抽取",
    "match_score": "匹配评分",
    "sponsor_entity": "雇主实体比对",
    "cover_letter": "Cover letter",
    "qa": "申请问答",
    "search": "职位搜索",
    "embedding": "Embedding",
}


class NoProviderConfigured(LLMError):
    pass


def build_provider(row: ProviderRow, model: str | None = None) -> LLMProvider:
    model = model or row.default_model
    caps = Capabilities.model_validate(row.capabilities)
    key = decrypt_secret(row.api_key_encrypted) if row.api_key_encrypted else ""
    match row.kind:
        case "openai":
            return OpenAIProvider(model, key, capabilities=caps)
        case "openai_compatible":
            return OpenAICompatibleProvider(model, key, base_url=row.base_url, capabilities=caps)
        case "anthropic":
            return AnthropicProvider(model, key, capabilities=caps)
        case "ollama":
            return OllamaProvider(model, row.base_url, capabilities=caps)
        case "claude_cli":
            return ClaudeCliProvider(model, capabilities=caps)
        case "codex_cli":
            return CodexCliProvider(model, capabilities=caps)
    raise LLMError(f"不支援的 provider 类型：{row.kind}")


def provider_for_task(db: Session, task: str) -> LLMProvider:
    """有路由就用路由；没有的话用第一个启用的 provider（embedding 除外，必须明确指定）。"""
    route = db.get(TaskRoute, task)
    if route is not None:
        if not route.provider.enabled:
            raise NoProviderConfigured(f"「{TASK_LABELS[task]}」指定的模型连接已停用，请到设置页修改。")
        return build_provider(route.provider, route.model)
    if task == "embedding":
        raise NoProviderConfigured(
            "尚未指定 embedding 模型（需要 OpenAI、OpenAI 兼容端点或 Ollama），请到设置页的任务路由设定。"
        )
    row = db.scalars(select(ProviderRow).where(ProviderRow.enabled.is_(True)).order_by(ProviderRow.created_at)).first()
    if row is None:
        raise NoProviderConfigured("尚未设定任何模型连接，请先到设置页新增。")
    return build_provider(row)


def supports_embedding(kind: str) -> bool:
    return kind in EMBEDDING_KINDS

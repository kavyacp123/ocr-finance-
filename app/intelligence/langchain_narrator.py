"""Optional LangChain narration over verified finance results.

The deterministic planner, tools, calculations, and evidence remain authoritative.
This adapter only turns those results into clearer prose and fails closed.
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.config import settings
from app.intelligence.schemas import FinanceAnswer, QueryPlan, ToolResult, Evidence
from app.investigations.schemas import InvestigationReport
from app.utils.logging import logger


class CopilotNarration(BaseModel):
    answer: str = Field(min_length=1)


class InvestigationNarration(BaseModel):
    summary: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)


class LangChainNarrator:
    """Opt-in grounded narrator backed by an OpenAI-compatible chat model."""

    def __init__(self, model: Any = None):
        self.model = model
        self.enabled = bool(settings.LANGCHAIN_ENABLED)

    @classmethod
    def from_settings(cls) -> "LangChainNarrator":
        if not settings.LANGCHAIN_ENABLED:
            return cls()

        provider = settings.LANGCHAIN_MODEL_PROVIDER.lower().strip()
        if provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError:
                logger.warning("LANGCHAIN: Gemini provider selected but langchain-google-genai is not installed; using deterministic responses.")
                return cls()
            api_key = settings.GEMINI_API_KEY or settings.LANGCHAIN_API_KEY
            if not api_key:
                logger.warning("LANGCHAIN: Gemini provider has no API key; using deterministic responses.")
                return cls()
            try:
                model = ChatGoogleGenerativeAI(
                    model=settings.LANGCHAIN_MODEL or "gemini-2.5-flash",
                    google_api_key=api_key,
                    temperature=settings.LANGCHAIN_TEMPERATURE,
                    max_output_tokens=settings.LANGCHAIN_MAX_TOKENS,
                    timeout=settings.LANGCHAIN_TIMEOUT_SECONDS,
                    max_retries=0,
                )
                logger.info("LANGCHAIN: grounded narration enabled with Gemini model '%s'.", settings.LANGCHAIN_MODEL)
                return cls(model=model)
            except Exception as exc:
                logger.warning("LANGCHAIN: Gemini initialization failed; using deterministic responses: %s", exc)
                return cls()

        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            logger.warning("LANGCHAIN: enabled but langchain-openai is not installed; using deterministic responses.")
            return cls()

        if provider == "xai":
            base_url = settings.LANGCHAIN_BASE_URL or "https://api.x.ai/v1"
            api_key = settings.XAI_API_KEY or settings.LANGCHAIN_API_KEY
            model_name = settings.LANGCHAIN_MODEL or "grok-4.6"
        else:
            base_url = settings.LANGCHAIN_BASE_URL or settings.COPILOT_LLM_BASE_URL
            api_key = settings.LANGCHAIN_API_KEY or settings.VLLM_API_KEY
            model_name = settings.LANGCHAIN_MODEL

        if not api_key:
            logger.warning("LANGCHAIN: provider '%s' has no API key; using deterministic responses.", provider)
            return cls()
        try:
            model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=settings.LANGCHAIN_TEMPERATURE,
                max_tokens=settings.LANGCHAIN_MAX_TOKENS,
                timeout=settings.LANGCHAIN_TIMEOUT_SECONDS,
                max_retries=0,
            )
            logger.info("LANGCHAIN: grounded narration enabled with provider '%s' and model '%s'.", provider, model_name)
            return cls(model=model)
        except Exception as exc:
            logger.warning("LANGCHAIN: initialization failed; using deterministic responses: %s", exc)
            return cls()

    @property
    def available(self) -> bool:
        return self.enabled and self.model is not None

    async def narrate_copilot(
        self,
        question: str,
        plan: QueryPlan,
        answer: FinanceAnswer,
        tool_results: List[ToolResult],
        evidence: List[Evidence],
    ) -> Optional[str]:
        if not self.available or (settings.LANGCHAIN_REQUIRE_EVIDENCE and not evidence):
            return None

        payload = self._bounded_json({
            "question": question,
            "plan": plan.model_dump(mode="json"),
            "deterministic_answer": answer.answer,
            "metrics": answer.metrics,
            "findings": answer.findings,
            "tool_results": [self._tool_result_summary(result) for result in tool_results],
            "evidence": [item.model_dump(mode="json") for item in evidence[:settings.COPILOT_MAX_CONTEXT_RESULTS]],
        })
        prompt = (
            "You are a finance intelligence narrator. Rewrite the deterministic answer into concise, "
            "clear prose for a finance user. Use only the supplied verified data and evidence. "
            "Preserve every number, date, identifier, and relationship exactly. Do not invent or "
            "calculate new values. If the evidence is insufficient, say so. Return only the answer.\n\n"
            f"VERIFIED CONTEXT:\n{payload}"
        )
        try:
            structured = self.model.with_structured_output(CopilotNarration)
            result = await structured.ainvoke(prompt)
            return result.answer.strip()
        except Exception as exc:
            logger.warning("LANGCHAIN: Copilot narration failed; retaining deterministic answer: %s", exc)
            return None

    async def narrate_investigation(
        self,
        question: str,
        report: InvestigationReport,
    ) -> Optional[InvestigationNarration]:
        if not self.available or (settings.LANGCHAIN_REQUIRE_EVIDENCE and not report.evidence):
            return None

        payload = self._bounded_json({
            "question": question,
            "report": report.model_dump(mode="json"),
        })
        prompt = (
            "You are a finance investigation narrator. Improve only the summary and conclusion of "
            "the supplied report. All calculations, findings, amounts, dates, and evidence are "
            "authoritative and must remain unchanged. Do not add causes that are not supported. "
            "Mention limitations when evidence is incomplete. Return JSON with summary and conclusion.\n\n"
            f"VERIFIED REPORT:\n{payload}"
        )
        try:
            structured = self.model.with_structured_output(InvestigationNarration)
            return await structured.ainvoke(prompt)
        except Exception as exc:
            logger.warning("LANGCHAIN: Investigation narration failed; retaining deterministic report: %s", exc)
            return None

    @staticmethod
    def _tool_result_summary(result: ToolResult) -> Dict[str, Any]:
        return {
            "tool": result.tool.value,
            "operation": result.operation.value,
            "success": result.success,
            "data": result.data,
            "record_count": result.record_count,
            "error": result.error,
        }

    @staticmethod
    def _bounded_json(value: Dict[str, Any], max_chars: int = 30000) -> str:
        encoded = json.dumps(value, default=str, ensure_ascii=True)
        return encoded[:max_chars]

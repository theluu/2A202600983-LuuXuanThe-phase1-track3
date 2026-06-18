from __future__ import annotations
import json
import os
import time
from functools import cached_property

from dotenv import load_dotenv

from .runtime import BaseRuntime, CallStats
from .schemas import QAExample, JudgeResult, ReflectionEntry
from .prompts import ACTOR_SYSTEM, EVALUATOR_SYSTEM, REFLECTOR_SYSTEM

load_dotenv()


class LLMConfigError(RuntimeError):
    """Lỗi cấu hình/billing (hết quota, sai key...) — không phải lỗi code."""


def _format_context(example: QAExample) -> str:
    return "\n".join(f"[{c.title}] {c.text}" for c in example.context)


def _extract_json(text: str) -> dict:
    """Lấy JSON object đầu tiên trong text (phòng khi model thêm chữ thừa)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


class OpenAIRuntime(BaseRuntime):
    """Runtime gọi LLM thật qua OpenAI API (hoặc bất kỳ endpoint
    OpenAI-compatible nào qua OPENAI_BASE_URL)."""
    name = "openai"

    def __init__(self) -> None:
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    @cached_property
    def _client(self):
        from openai import OpenAI
        # OPENAI_API_KEY (và tùy chọn OPENAI_BASE_URL) đọc từ env / .env
        return OpenAI()

    def _create_with_retry(self, kwargs: dict, max_retries: int = 4):
        """Gọi API có retry (backoff) khi nghẽn tạm thời; báo lỗi gọn khi hết quota/sai key."""
        import openai
        delay = 2.0
        for attempt in range(max_retries):
            try:
                start = time.perf_counter()
                resp = self._client.chat.completions.create(**kwargs)
                return resp, int((time.perf_counter() - start) * 1000)
            except openai.AuthenticationError as ex:
                raise LLMConfigError(
                    "API key không hợp lệ (401). Kiểm tra OPENAI_API_KEY trong .env "
                    f"(và OPENAI_BASE_URL nếu dùng Groq/Ollama). Chi tiết: {ex}"
                ) from None
            except openai.RateLimitError as ex:
                msg = str(ex)
                if "insufficient_quota" in msg or "exceeded your current quota" in msg:
                    raise LLMConfigError(
                        "Hết quota/billing — đây KHÔNG phải lỗi code. Hãy nạp credit, "
                        "đổi key còn quota, hoặc chuyển sang Groq/Ollama (xem .env). "
                        f"Chi tiết: {ex}"
                    ) from None
                # rate limit tạm thời -> chờ rồi thử lại
                if attempt == max_retries - 1:
                    raise LLMConfigError(f"Bị giới hạn tốc độ liên tục sau {max_retries} lần thử. {ex}") from None
                time.sleep(delay); delay *= 2
            except (openai.APIConnectionError, openai.APITimeoutError) as ex:
                if attempt == max_retries - 1:
                    raise LLMConfigError(f"Lỗi kết nối tới API sau {max_retries} lần thử. {ex}") from None
                time.sleep(delay); delay *= 2

    def _chat(self, system: str, user: str, json_mode: bool = False) -> tuple[str, CallStats]:
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._create_with_retry(kwargs)
        latency_ms = resp[1]
        resp = resp[0]
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        tokens = getattr(usage, "total_tokens", 0) or 0
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        return text, CallStats(tokens=tokens, latency_ms=latency_ms,
                               prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    def actor_answer(self, example, attempt_id, agent_type, reflection_memory):
        parts = [
            f"CÂU HỎI:\n{example.question}",
            f"\nCONTEXT:\n{_format_context(example)}",
        ]
        if reflection_memory:
            lessons = "\n".join(f"- {m}" for m in reflection_memory)
            parts.append(f"\nREFLECTION (bài học từ các lần thử trước):\n{lessons}")
        parts.append("\nĐÁP ÁN CUỐI CÙNG (chỉ một cụm ngắn, không giải thích):")
        text, stats = self._chat(ACTOR_SYSTEM, "\n".join(parts))
        return text, stats

    def evaluator(self, example, answer):
        user = (
            f"CÂU HỎI:\n{example.question}\n\n"
            f"ĐÁP ÁN ĐÚNG (gold):\n{example.gold_answer}\n\n"
            f"ĐÁP ÁN DỰ ĐOÁN (predicted):\n{answer}"
        )
        text, stats = self._chat(EVALUATOR_SYSTEM, user, json_mode=True)
        data = _extract_json(text)
        judge = JudgeResult(
            score=int(data.get("score", 0)),
            reason=str(data.get("reason", "")),
            missing_evidence=list(data.get("missing_evidence", []) or []),
            spurious_claims=list(data.get("spurious_claims", []) or []),
        )
        return judge, stats

    def reflector(self, example, attempt_id, judge):
        user = (
            f"CÂU HỎI:\n{example.question}\n\n"
            f"ĐÁP ÁN SAI vừa rồi đã bị chấm 0.\n"
            f"NHẬN XÉT CỦA GIÁM KHẢO:\n"
            f"- reason: {judge.reason}\n"
            f"- missing_evidence: {judge.missing_evidence}\n"
            f"- spurious_claims: {judge.spurious_claims}"
        )
        text, stats = self._chat(REFLECTOR_SYSTEM, user, json_mode=True)
        data = _extract_json(text)
        entry = ReflectionEntry(
            attempt_id=attempt_id,
            failure_reason=str(data.get("failure_reason", judge.reason)),
            lesson=str(data.get("lesson", "")),
            next_strategy=str(data.get("next_strategy", "")),
        )
        return entry, stats

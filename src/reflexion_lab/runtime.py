from __future__ import annotations
import os
from dataclasses import dataclass
from .schemas import QAExample, JudgeResult, ReflectionEntry


@dataclass
class CallStats:
    """Số liệu thật của một lần gọi runtime (token + latency)."""
    tokens: int = 0            # tổng token (prompt + completion)
    latency_ms: int = 0
    prompt_tokens: int = 0     # token đầu vào (để tính cost chính xác)
    completion_tokens: int = 0  # token sinh ra


class BaseRuntime:
    """Giao diện chung cho mock runtime và LLM runtime thật.

    Mỗi hàm trả về (giá_trị, CallStats) để agents.py có thể ghi nhận
    token/latency THẬT thay vì hardcode.
    """
    name = "base"

    def actor_answer(self, example: QAExample, attempt_id: int, agent_type: str,
                     reflection_memory: list[str]) -> tuple[str, CallStats]:
        raise NotImplementedError

    def evaluator(self, example: QAExample, answer: str) -> tuple[JudgeResult, CallStats]:
        raise NotImplementedError

    def reflector(self, example: QAExample, attempt_id: int,
                  judge: JudgeResult) -> tuple[ReflectionEntry, CallStats]:
        raise NotImplementedError

    def classify_failure(self, example: QAExample, judge: JudgeResult | None) -> str:
        """Suy ra failure_mode từ kết quả chấm điểm cuối cùng."""
        if judge is None or judge.score == 1:
            return "none"
        if judge.missing_evidence:
            return "incomplete_multi_hop"
        if judge.spurious_claims:
            return "entity_drift"
        return "wrong_final_answer"


def get_runtime(name: str | None = None) -> BaseRuntime:
    """Chọn runtime theo tham số hoặc biến môi trường REFLEXION_RUNTIME.

    "mock" (mặc định) -> deterministic, không cần API key (cho autograding).
    "openai"/"llm"/"real" -> gọi LLM thật qua OpenAI API.
    """
    name = (name or os.getenv("REFLEXION_RUNTIME", "mock")).lower()
    if name in ("openai", "llm", "real"):
        from .llm_runtime import OpenAIRuntime
        return OpenAIRuntime()
    from .mock_runtime import MockRuntime
    return MockRuntime()

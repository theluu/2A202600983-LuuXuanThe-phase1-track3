from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional
from .runtime import BaseRuntime, get_runtime
from .schemas import AttemptTrace, JudgeResult, QAExample, ReflectionEntry, RunRecord


# Extension: adaptive_max_attempts — câu khó được thử nhiều hơn câu dễ.
_DIFFICULTY_ATTEMPTS = {"easy": 2, "medium": 3, "hard": 4}


@dataclass
class BaseAgent:
    agent_type: Literal["react", "reflexion"]
    max_attempts: int = 1
    runtime: Optional[BaseRuntime] = None
    adaptive: bool = False

    def _rt(self) -> BaseRuntime:
        if self.runtime is None:
            self.runtime = get_runtime()
        return self.runtime

    def _effective_max(self, example: QAExample) -> int:
        if self.agent_type == "reflexion" and self.adaptive:
            # Giới hạn theo độ khó nhưng không vượt quá ngân sách max_attempts.
            return min(self.max_attempts, _DIFFICULTY_ATTEMPTS.get(example.difficulty, self.max_attempts))
        return self.max_attempts

    def run(self, example: QAExample) -> RunRecord:
        rt = self._rt()
        max_attempts = self._effective_max(example)
        reflection_memory: list[str] = []
        reflections: list[ReflectionEntry] = []
        traces: list[AttemptTrace] = []
        final_answer = ""
        final_score = 0
        last_judge: Optional[JudgeResult] = None

        for attempt_id in range(1, max_attempts + 1):
            # 1) Actor trả lời (có thể tham khảo reflection_memory)
            answer, actor_stats = rt.actor_answer(example, attempt_id, self.agent_type, reflection_memory)
            # 2) Evaluator chấm điểm
            judge, eval_stats = rt.evaluator(example, answer)

            # Token + latency THẬT từ runtime (gộp actor + evaluator)
            token_estimate = actor_stats.tokens + eval_stats.tokens
            latency_ms = actor_stats.latency_ms + eval_stats.latency_ms

            trace = AttemptTrace(attempt_id=attempt_id, answer=answer, score=judge.score,
                                 reason=judge.reason, token_estimate=token_estimate, latency_ms=latency_ms,
                                 prompt_tokens=actor_stats.prompt_tokens + eval_stats.prompt_tokens,
                                 completion_tokens=actor_stats.completion_tokens + eval_stats.completion_tokens)
            final_answer = answer
            final_score = judge.score
            last_judge = judge

            if judge.score == 1:
                traces.append(trace)
                break

            # ---- Reflexion loop ----
            # Chỉ reflexion agent mới phản chiếu, và chỉ khi còn lượt thử.
            if self.agent_type == "reflexion" and attempt_id < max_attempts:
                reflection, refl_stats = rt.reflector(example, attempt_id, judge)
                reflections.append(reflection)
                trace.reflection = reflection
                # Cộng dồn chi phí của bước reflector vào trace hiện tại.
                trace.token_estimate += refl_stats.tokens
                trace.latency_ms += refl_stats.latency_ms
                trace.prompt_tokens += refl_stats.prompt_tokens
                trace.completion_tokens += refl_stats.completion_tokens
                # Đưa chiến thuật mới vào bộ nhớ để Actor dùng cho lần sau.
                reflection_memory.append(reflection.next_strategy)

            traces.append(trace)

        total_tokens = sum(t.token_estimate for t in traces)
        total_latency = sum(t.latency_ms for t in traces)
        total_prompt = sum(t.prompt_tokens for t in traces)
        total_completion = sum(t.completion_tokens for t in traces)
        failure_mode = rt.classify_failure(example, last_judge)
        return RunRecord(qid=example.qid, question=example.question, gold_answer=example.gold_answer,
                         agent_type=self.agent_type, predicted_answer=final_answer,
                         is_correct=bool(final_score), attempts=len(traces), token_estimate=total_tokens,
                         latency_ms=total_latency, prompt_tokens=total_prompt, completion_tokens=total_completion,
                         failure_mode=failure_mode, reflections=reflections, traces=traces)


class ReActAgent(BaseAgent):
    def __init__(self, runtime: Optional[BaseRuntime] = None) -> None:
        super().__init__(agent_type="react", max_attempts=1, runtime=runtime)


class ReflexionAgent(BaseAgent):
    def __init__(self, max_attempts: int = 3, runtime: Optional[BaseRuntime] = None,
                 adaptive: bool = False) -> None:
        super().__init__(agent_type="reflexion", max_attempts=max_attempts, runtime=runtime, adaptive=adaptive)

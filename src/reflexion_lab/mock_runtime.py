from __future__ import annotations
import hashlib
from .runtime import BaseRuntime, CallStats
from .schemas import QAExample, JudgeResult, ReflectionEntry
from .utils import normalize_answer

# Các failure mode mock có thể "dàn dựng" một cách deterministic.
_FAILURE_CYCLE = [
    "incomplete_multi_hop",
    "entity_drift",
    "wrong_final_answer",
    "looping",
    "reflection_overfit",
]
# Những mode mà Reflexion KHÔNG sửa được -> minh hoạ giới hạn của reflexion.
_STUBBORN = {"looping", "reflection_overfit"}


def _stats(tokens: int, latency_ms: int) -> CallStats:
    """Tách prompt/completion deterministic (~80%/20%) cho mock."""
    prompt = int(tokens * 0.8)
    return CallStats(tokens=tokens, latency_ms=latency_ms,
                     prompt_tokens=prompt, completion_tokens=tokens - prompt)


def _hash(qid: str) -> int:
    return int(hashlib.sha1(qid.encode("utf-8")).hexdigest(), 16)


def _planned_failure(qid: str) -> str | None:
    """Gán deterministic một failure mode cho ~45% câu hỏi (theo hash của qid)."""
    h = _hash(qid)
    if h % 100 >= 45:
        return None  # câu này Actor trả lời đúng ngay lần đầu
    return _FAILURE_CYCLE[h % len(_FAILURE_CYCLE)]


class MockRuntime(BaseRuntime):
    """Runtime giả lập deterministic — dùng để hiểu flow và để autograding
    không tốn chi phí API. Sinh đa dạng failure mode trên dataset bất kỳ."""
    name = "mock"

    def actor_answer(self, example, attempt_id, agent_type, reflection_memory):
        mode = _planned_failure(example.qid)
        stats = _stats(320 + attempt_id * 65, 160 + attempt_id * 40)
        if mode is None:
            return example.gold_answer, stats
        wrong = f"{example.gold_answer} [mock-{mode}]"  # khác gold sau khi normalize
        if agent_type == "react":
            return wrong, stats
        # Reflexion: lần đầu (chưa có reflection) trả lời sai; các lần sau đã có
        # bài học -> sửa được, TRỪ các mode "cứng đầu".
        if attempt_id == 1 and not reflection_memory:
            return wrong, stats
        if mode in _STUBBORN:
            return wrong, stats
        return example.gold_answer, stats

    def evaluator(self, example, answer):
        stats = _stats(180, 120)
        if normalize_answer(example.gold_answer) == normalize_answer(answer):
            return JudgeResult(score=1, reason="Đáp án khớp gold answer sau khi chuẩn hoá."), stats
        mode = _planned_failure(example.qid) or "wrong_final_answer"
        if mode == "incomplete_multi_hop":
            return JudgeResult(score=0, reason="Câu trả lời dừng ở hop đầu, chưa hoàn thành hop thứ hai.",
                               missing_evidence=["Cần hoàn thành bước suy luận thứ hai để tới đáp án cuối."]), stats
        if mode in ("entity_drift", "looping"):
            return JudgeResult(score=0, reason="Câu trả lời chọn sai thực thể ở hop thứ hai.",
                               missing_evidence=["Cần đối chiếu với đoạn context thứ hai."],
                               spurious_claims=[answer]), stats
        return JudgeResult(score=0, reason="Đáp án cuối không đúng.",
                           spurious_claims=[answer]), stats

    def reflector(self, example, attempt_id, judge):
        stats = _stats(210, 150)
        entry = ReflectionEntry(
            attempt_id=attempt_id,
            failure_reason=judge.reason,
            lesson="Một đáp án một-hop là chưa đủ; đáp án cuối phải hoàn thành tất cả các hop.",
            next_strategy="Xác định thực thể trung gian trước, rồi đối chiếu đoạn context thứ hai trước khi chốt đáp án.",
        )
        return entry, stats

    def classify_failure(self, example, judge):
        if judge is None or judge.score == 1:
            return "none"
        return _planned_failure(example.qid) or "wrong_final_answer"

from __future__ import annotations
import os

# Giá tham khảo (USD trên 1 TRIỆU token) — chỉnh theo bảng giá hiện hành nếu cần.
# (input = prompt tokens, output = completion tokens)
PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    # Groq (free tier) — đặt 0 để cost table phản ánh đúng là không tốn tiền.
    "llama-3.1-8b-instant": {"input": 0.0, "output": 0.0},
    "llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},
    "llama3-8b-8192": {"input": 0.0, "output": 0.0},
    # runtime mock không tốn tiền
    "mock": {"input": 0.0, "output": 0.0},
}

_DEFAULT = {"input": 0.15, "output": 0.60}  # mặc định theo gpt-4o-mini


def rates_for(model: str) -> dict[str, float]:
    if model in PRICING:
        return PRICING[model]
    # cho phép ghi đè qua env nếu dùng model lạ
    env_in = os.getenv("PRICE_INPUT_PER_1M")
    env_out = os.getenv("PRICE_OUTPUT_PER_1M")
    if env_in and env_out:
        return {"input": float(env_in), "output": float(env_out)}
    return _DEFAULT


def estimate_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    r = rates_for(model)
    return round(prompt_tokens / 1_000_000 * r["input"]
                 + completion_tokens / 1_000_000 * r["output"], 6)

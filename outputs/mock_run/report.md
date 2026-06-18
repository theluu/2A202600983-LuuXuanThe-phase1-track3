# Lab 16 Benchmark Report

## Metadata
- Dataset: benchmark_set.json
- Mode: mock
- Model: mock
- Records: 120
- Agents: react, reflexion

## So sánh ReAct vs Reflexion
| Metric | ReAct | Reflexion | Δ (Refl−ReAct) |
|---|---:|---:|---:|
| EM (accuracy) | 0.6 | 0.85 | 0.25 |
| Avg attempts | 1 | 1.5667 | 0.5667 |
| Avg tokens/q | 565 | 1055.08 | 490.08 |
| Avg latency (ms) | 320 | 617.67 | 297.67 |

## Chi phí & thời gian chạy (model=mock, giá USD/1M token: input 0.0 / output 0.0)
| Agent | Total tokens | Prompt | Completion | Est. cost (USD) | Compute time | Avg/question |
|---|---:|---:|---:|---:|---:|---:|
| react | 33,900 | 27,120 | 6,780 | $0.000000 | 19.2s | 0.32s |
| reflexion | 63,305 | 50,644 | 12,661 | $0.000000 | 37.06s | 0.618s |

- **Tổng chi phí ước tính: $0.0**
- Wall-clock time: 0.01s

## Failure modes
```json
{
  "reflection_overfit": {
    "total": 8,
    "react": 4,
    "reflexion": 4
  },
  "incomplete_multi_hop": {
    "total": 7,
    "react": 7,
    "reflexion": 0
  },
  "none": {
    "total": 87,
    "react": 36,
    "reflexion": 51
  },
  "wrong_final_answer": {
    "total": 4,
    "react": 4,
    "reflexion": 0
  },
  "looping": {
    "total": 10,
    "react": 5,
    "reflexion": 5
  },
  "entity_drift": {
    "total": 4,
    "react": 4,
    "reflexion": 0
  }
}
```

## Extensions implemented
- structured_evaluator
- reflection_memory
- benchmark_report_json
- mock_mode_for_autograding
- adaptive_max_attempts

## Discussion
Chạy ở chế độ 'mock' (model=mock). Exact-match: ReAct=0.6 so với Reflexion=0.85 (delta EM=0.25). Reflexion giúp ích rõ nhất khi lần thử đầu dừng ở hop thứ nhất (incomplete_multi_hop) hoặc chọn nhầm thực thể ở hop thứ hai (entity_drift): vòng phản chiếu cập nhật next_strategy vào reflection_memory để Actor sửa lỗi ở lượt sau. Cái giá phải trả là số attempt, token, latency và CHI PHÍ tăng (delta attempts=0.5667, delta tokens=490.08, delta latency=297.67 ms; tổng chi phí ước tính $0.0). Các failure mode còn sót lại ở Reflexion: looping, reflection_overfit — chủ yếu là looping và reflection_overfit, cho thấy giới hạn khi reflection lặp lại hoặc bám sai hướng; chất lượng của Evaluator là trần trên cho mức cải thiện. Khi base model đã mạnh và câu hỏi dễ, Reflexion gần như không tăng EM mà chỉ thêm chi phí.

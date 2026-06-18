# Lab 16 Benchmark Report

## Metadata
- Dataset: hotpot_100.json
- Mode: openai
- Model: gpt-4o-mini
- Records: 200
- Agents: react, reflexion

## So sánh ReAct vs Reflexion
| Metric | ReAct | Reflexion | Δ (Refl−ReAct) |
|---|---:|---:|---:|
| EM (accuracy) | 0.64 | 0.76 | 0.12 |
| Avg attempts | 1 | 1.87 | 0.87 |
| Avg tokens/q | 2009.55 | 4200.79 | 2191.24 |
| Avg latency (ms) | 2183.46 | 6762.12 | 4578.66 |

## Chi phí & thời gian chạy (model=gpt-4o-mini, giá USD/1M token: input 0.15 / output 0.6)
| Agent | Total tokens | Prompt | Completion | Est. cost (USD) | Compute time | Avg/question |
|---|---:|---:|---:|---:|---:|---:|
| react | 200,955 | 195,243 | 5,712 | $0.032714 | 218.35s | 2.183s |
| reflexion | 420,079 | 399,316 | 20,763 | $0.072355 | 676.21s | 6.762s |

- **Tổng chi phí ước tính: $0.105069**
- Wall-clock time: 895.85s

## Failure modes
```json
{
  "incomplete_multi_hop": {
    "total": 49,
    "react": 31,
    "reflexion": 18
  },
  "entity_drift": {
    "total": 9,
    "react": 4,
    "reflexion": 5
  },
  "none": {
    "total": 140,
    "react": 64,
    "reflexion": 76
  },
  "wrong_final_answer": {
    "total": 2,
    "react": 1,
    "reflexion": 1
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
Chạy ở chế độ 'openai' (model=gpt-4o-mini). Exact-match: ReAct=0.64 so với Reflexion=0.76 (delta EM=0.12). Reflexion giúp ích rõ nhất khi lần thử đầu dừng ở hop thứ nhất (incomplete_multi_hop) hoặc chọn nhầm thực thể ở hop thứ hai (entity_drift): vòng phản chiếu cập nhật next_strategy vào reflection_memory để Actor sửa lỗi ở lượt sau. Cái giá phải trả là số attempt, token, latency và CHI PHÍ tăng (delta attempts=0.87, delta tokens=2191.24, delta latency=4578.66 ms; tổng chi phí ước tính $0.105069). Các failure mode còn sót lại ở Reflexion: entity_drift, incomplete_multi_hop, wrong_final_answer — chủ yếu là looping và reflection_overfit, cho thấy giới hạn khi reflection lặp lại hoặc bám sai hướng; chất lượng của Evaluator là trần trên cho mức cải thiện. Khi base model đã mạnh và câu hỏi dễ, Reflexion gần như không tăng EM mà chỉ thêm chi phí.

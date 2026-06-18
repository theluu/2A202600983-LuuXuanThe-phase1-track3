# Lab 16 Benchmark Report

## Metadata
- Dataset: hotpot_mini.json
- Mode: mock
- Records: 16
- Agents: react, reflexion

## Summary
| Metric | ReAct | Reflexion | Delta |
|---|---:|---:|---:|
| EM | 0.625 | 0.625 | 0.0 |
| Avg attempts | 1 | 1.75 | 0.75 |
| Avg token estimate | 565 | 1227.5 | 662.5 |
| Avg latency (ms) | 320 | 722.5 | 402.5 |

## Failure modes
```json
{
  "reflection_overfit": {
    "total": 4,
    "react": 2,
    "reflexion": 2
  },
  "none": {
    "total": 10,
    "react": 5,
    "reflexion": 5
  },
  "looping": {
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
Chạy ở chế độ 'mock'. Exact-match: ReAct=0.625 so với Reflexion=0.625 (delta EM=0.0). Reflexion giúp ích rõ nhất khi lần thử đầu dừng ở hop thứ nhất (incomplete_multi_hop) hoặc chọn nhầm thực thể ở hop thứ hai (entity_drift): vòng phản chiếu cập nhật next_strategy vào reflection_memory để Actor sửa lỗi ở lượt sau. Cái giá phải trả là số attempt, token và latency tăng (delta attempts=0.75, delta tokens=662.5, delta latency=402.5 ms). Các failure mode còn sót lại ở Reflexion: looping, reflection_overfit — chủ yếu là looping và reflection_overfit, cho thấy giới hạn khi reflection lặp lại hoặc bám sai hướng; chất lượng của Evaluator là trần trên cho mức cải thiện.

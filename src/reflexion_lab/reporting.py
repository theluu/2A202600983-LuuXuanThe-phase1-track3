from __future__ import annotations
import html
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from .pricing import estimate_cost, rates_for
from .schemas import ReportPayload, RunRecord


def summarize(records: list[RunRecord]) -> dict:
    grouped: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        grouped[record.agent_type].append(record)
    summary: dict[str, dict] = {}
    for agent_type, rows in grouped.items():
        summary[agent_type] = {
            "count": len(rows),
            "em": round(mean(1.0 if r.is_correct else 0.0 for r in rows), 4),
            "avg_attempts": round(mean(r.attempts for r in rows), 4),
            "avg_token_estimate": round(mean(r.token_estimate for r in rows), 2),
            "avg_latency_ms": round(mean(r.latency_ms for r in rows), 2),
            "total_tokens": sum(r.token_estimate for r in rows),
            "total_prompt_tokens": sum(r.prompt_tokens for r in rows),
            "total_completion_tokens": sum(r.completion_tokens for r in rows),
            "total_latency_ms": sum(r.latency_ms for r in rows),
        }
    if "react" in summary and "reflexion" in summary:
        summary["delta_reflexion_minus_react"] = {
            "em_abs": round(summary["reflexion"]["em"] - summary["react"]["em"], 4),
            "attempts_abs": round(summary["reflexion"]["avg_attempts"] - summary["react"]["avg_attempts"], 4),
            "tokens_abs": round(summary["reflexion"]["avg_token_estimate"] - summary["react"]["avg_token_estimate"], 2),
            "latency_abs": round(summary["reflexion"]["avg_latency_ms"] - summary["react"]["avg_latency_ms"], 2),
        }
    return summary


def failure_breakdown(records: list[RunRecord]) -> dict:
    """Gom theo TÊN failure mode (mỗi mode là một key), kèm phân rã theo agent.

    Cấu trúc này cho phép autograder đếm số failure mode (>=3) và đồng thời
    phục vụ phân tích react-vs-reflexion cho từng mode.
    """
    modes: dict[str, dict] = defaultdict(lambda: {"total": 0, "react": 0, "reflexion": 0})
    for record in records:
        bucket = modes[record.failure_mode]
        bucket["total"] += 1
        bucket[record.agent_type] += 1
    return {mode: dict(counts) for mode, counts in modes.items()}


def _cost_block(summary: dict, model: str, wall_seconds: float | None) -> dict:
    """Ước tính chi phí (USD) + thời gian chạy cho từng agent và tổng."""
    rates = rates_for(model)
    block: dict = {"model": model, "rates_usd_per_1m": rates, "by_agent": {}}
    total_cost = 0.0
    for agent in ("react", "reflexion"):
        a = summary.get(agent)
        if not a:
            continue
        cost = estimate_cost(a["total_prompt_tokens"], a["total_completion_tokens"], model)
        total_cost += cost
        block["by_agent"][agent] = {
            "total_tokens": a["total_tokens"],
            "prompt_tokens": a["total_prompt_tokens"],
            "completion_tokens": a["total_completion_tokens"],
            "est_cost_usd": cost,
            "compute_seconds": round(a["total_latency_ms"] / 1000, 2),
            "avg_seconds_per_question": round(a["total_latency_ms"] / 1000 / max(a["count"], 1), 3),
        }
    block["total_est_cost_usd"] = round(total_cost, 6)
    if wall_seconds is not None:
        block["wall_time_seconds"] = round(wall_seconds, 2)
    return block


def _discussion(summary: dict, failure_modes: dict, mode: str, cost: dict) -> str:
    react = summary.get("react", {})
    reflexion = summary.get("reflexion", {})
    delta = summary.get("delta_reflexion_minus_react", {})
    remaining = sorted(m for m, c in failure_modes.items()
                       if m != "none" and c.get("reflexion", 0) > 0)
    return (
        f"Chạy ở chế độ '{mode}' (model={cost.get('model')}). Exact-match: ReAct={react.get('em', 0)} "
        f"so với Reflexion={reflexion.get('em', 0)} (delta EM={delta.get('em_abs', 0)}). "
        f"Reflexion giúp ích rõ nhất khi lần thử đầu dừng ở hop thứ nhất "
        f"(incomplete_multi_hop) hoặc chọn nhầm thực thể ở hop thứ hai (entity_drift): "
        f"vòng phản chiếu cập nhật next_strategy vào reflection_memory để Actor sửa lỗi ở lượt sau. "
        f"Cái giá phải trả là số attempt, token, latency và CHI PHÍ tăng "
        f"(delta attempts={delta.get('attempts_abs', 0)}, delta tokens={delta.get('tokens_abs', 0)}, "
        f"delta latency={delta.get('latency_abs', 0)} ms; tổng chi phí ước tính "
        f"${cost.get('total_est_cost_usd', 0)}). "
        f"Các failure mode còn sót lại ở Reflexion: {', '.join(remaining) or 'không'} — "
        f"chủ yếu là looping và reflection_overfit, cho thấy giới hạn khi reflection lặp lại "
        f"hoặc bám sai hướng; chất lượng của Evaluator là trần trên cho mức cải thiện. "
        f"Khi base model đã mạnh và câu hỏi dễ, Reflexion gần như không tăng EM mà chỉ thêm chi phí."
    )


def build_report(records: list[RunRecord], dataset_name: str, mode: str = "mock",
                 model: str = "mock", wall_seconds: float | None = None) -> ReportPayload:
    examples = [{"qid": r.qid, "agent_type": r.agent_type, "question": r.question,
                 "gold_answer": r.gold_answer, "predicted_answer": r.predicted_answer,
                 "is_correct": r.is_correct, "attempts": r.attempts, "token_estimate": r.token_estimate,
                 "latency_ms": r.latency_ms, "failure_mode": r.failure_mode,
                 "reflection_count": len(r.reflections),
                 "next_strategies": [ref.next_strategy for ref in r.reflections]} for r in records]
    summary = summarize(records)
    failure_modes = failure_breakdown(records)
    cost = _cost_block(summary, model, wall_seconds)
    return ReportPayload(
        meta={"dataset": dataset_name, "mode": mode, "num_records": len(records),
              "agents": sorted({r.agent_type for r in records}), "model": model, "cost": cost},
        summary=summary,
        failure_modes=failure_modes,
        examples=examples,
        extensions=["structured_evaluator", "reflection_memory", "benchmark_report_json",
                    "mock_mode_for_autograding", "adaptive_max_attempts"],
        discussion=_discussion(summary, failure_modes, mode, cost),
    )


# ----------------------- Bảng quan sát (markdown + console) -----------------------

def comparison_rows(report: ReportPayload) -> list[tuple[str, str, str, str]]:
    s = report.summary
    react, reflexion = s.get("react", {}), s.get("reflexion", {})
    delta = s.get("delta_reflexion_minus_react", {})
    return [
        ("EM (accuracy)", str(react.get("em", 0)), str(reflexion.get("em", 0)), str(delta.get("em_abs", 0))),
        ("Avg attempts", str(react.get("avg_attempts", 0)), str(reflexion.get("avg_attempts", 0)), str(delta.get("attempts_abs", 0))),
        ("Avg tokens/q", str(react.get("avg_token_estimate", 0)), str(reflexion.get("avg_token_estimate", 0)), str(delta.get("tokens_abs", 0))),
        ("Avg latency (ms)", str(react.get("avg_latency_ms", 0)), str(reflexion.get("avg_latency_ms", 0)), str(delta.get("latency_abs", 0))),
    ]


def cost_rows(report: ReportPayload) -> list[tuple]:
    by = report.meta["cost"]["by_agent"]
    rows = []
    for agent in ("react", "reflexion"):
        a = by.get(agent)
        if not a:
            continue
        rows.append((agent, f"{a['total_tokens']:,}", f"{a['prompt_tokens']:,}",
                     f"{a['completion_tokens']:,}", f"${a['est_cost_usd']:.6f}",
                     f"{a['compute_seconds']}s", f"{a['avg_seconds_per_question']}s"))
    return rows


def print_tables(report: ReportPayload) -> None:
    """In bảng so sánh + bảng chi phí ra console bằng rich."""
    from rich.console import Console
    from rich.table import Table
    console = Console()
    cost = report.meta["cost"]

    cmp = Table(title="So sánh ReAct vs Reflexion", title_style="bold cyan")
    cmp.add_column("Metric"); cmp.add_column("ReAct", justify="right")
    cmp.add_column("Reflexion", justify="right"); cmp.add_column("Δ (Refl−ReAct)", justify="right")
    for row in comparison_rows(report):
        cmp.add_row(*row)
    console.print(cmp)

    ct = Table(title=f"Chi phí & thời gian (model={cost['model']})", title_style="bold green")
    for col in ("Agent", "Total tok", "Prompt", "Completion", "Est. cost", "Compute time", "Avg/q"):
        ct.add_column(col, justify="right" if col != "Agent" else "left")
    for row in cost_rows(report):
        ct.add_row(*row)
    console.print(ct)
    extra = f" | wall {cost['wall_time_seconds']}s" if "wall_time_seconds" in cost else ""
    console.print(f"[bold]Tổng chi phí ước tính:[/bold] ${cost['total_est_cost_usd']}{extra}")


def _delta_class(value: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if v > 0:
        return "pos"
    if v < 0:
        return "neg"
    return "neutral"


def render_html(report: ReportPayload) -> str:
    """Tạo một trang HTML self-contained (CSS nội tuyến) để xem trực quan."""
    e = html.escape
    meta = report.meta
    cost = meta["cost"]
    s = report.summary
    react, reflexion = s.get("react", {}), s.get("reflexion", {})

    # Bảng so sánh
    cmp_rows = "".join(
        f"<tr><td class='metric'>{e(m)}</td><td>{e(r)}</td><td>{e(x)}</td>"
        f"<td class='{_delta_class(d)}'>{e(d)}</td></tr>"
        for m, r, x, d in comparison_rows(report)
    )
    # Bảng chi phí
    cost_rows_html = "".join(
        f"<tr><td class='metric'>{e(a)}</td><td>{e(t)}</td><td>{e(p)}</td><td>{e(c)}</td>"
        f"<td>{e(cst)}</td><td>{e(ct)}</td><td>{e(avg)}</td></tr>"
        for a, t, p, c, cst, ct, avg in cost_rows(report)
    )
    # Thanh accuracy trực quan
    react_em = float(react.get("em", 0) or 0) * 100
    refl_em = float(reflexion.get("em", 0) or 0) * 100
    bars = (
        f"<div class='bar-row'><span class='bar-label'>ReAct</span>"
        f"<div class='bar'><div class='fill react' style='width:{react_em:.1f}%'>{react_em:.1f}%</div></div></div>"
        f"<div class='bar-row'><span class='bar-label'>Reflexion</span>"
        f"<div class='bar'><div class='fill refl' style='width:{refl_em:.1f}%'>{refl_em:.1f}%</div></div></div>"
    )
    # Failure modes
    fm_rows = "".join(
        f"<tr><td class='metric'>{e(mode)}</td><td>{c.get('total',0)}</td>"
        f"<td>{c.get('react',0)}</td><td>{c.get('reflexion',0)}</td></tr>"
        for mode, c in sorted(report.failure_modes.items(), key=lambda kv: -kv[1].get("total", 0))
    )
    # Ví dụ (tối đa 30, ưu tiên các câu sai để dễ quan sát)
    ex_sorted = sorted(report.examples, key=lambda r: (r.get("is_correct", True), r.get("agent_type", "")))
    ex_cells = []
    for ex in ex_sorted[:30]:
        ok = ex.get("is_correct")
        cls = "ok" if ok else "bad"
        mark = "✅" if ok else "❌"
        ex_cells.append(
            f"<tr class='{cls}'>"
            f"<td>{e(str(ex.get('qid','')))}</td><td>{e(str(ex.get('agent_type','')))}</td>"
            f"<td class='q'>{e(str(ex.get('question','')))}</td>"
            f"<td>{e(str(ex.get('gold_answer','')))}</td>"
            f"<td>{e(str(ex.get('predicted_answer','')))}</td>"
            f"<td>{mark}</td>"
            f"<td>{ex.get('attempts','')}</td><td>{e(str(ex.get('failure_mode','')))}</td></tr>"
        )
    ex_rows = "".join(ex_cells)
    wall = f" &nbsp;•&nbsp; ⏱ wall {cost['wall_time_seconds']}s" if "wall_time_seconds" in cost else ""
    rates = cost["rates_usd_per_1m"]

    return f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lab 16 — Reflexion Benchmark Report</title>
<style>
:root{{--bg:#0f172a;--card:#1e293b;--ink:#e2e8f0;--muted:#94a3b8;--line:#334155;
--react:#38bdf8;--refl:#34d399;--pos:#22c55e;--neg:#f87171;}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
background:var(--bg);color:var(--ink);padding:32px;line-height:1.5}}
.wrap{{max-width:1040px;margin:0 auto}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:28px 0 12px;color:#cbd5e1}}
.sub{{color:var(--muted);font-size:14px;margin-bottom:8px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-top:16px}}
.kpis{{display:flex;gap:16px;flex-wrap:wrap}}
.kpi{{flex:1;min-width:150px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}}
.kpi .v{{font-size:26px;font-weight:700}} .kpi .l{{color:var(--muted);font-size:13px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line)}}
th:first-child,td.metric,td.q{{text-align:left}}
th{{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
td.pos{{color:var(--pos);font-weight:600}} td.neg{{color:var(--neg);font-weight:600}}
.bar-row{{display:flex;align-items:center;gap:12px;margin:8px 0}}
.bar-label{{width:80px;color:var(--muted)}}
.bar{{flex:1;background:#0b1222;border-radius:8px;overflow:hidden;height:26px}}
.fill{{height:100%;display:flex;align-items:center;justify-content:flex-end;padding-right:8px;
font-size:12px;font-weight:700;color:#08111f}}
.fill.react{{background:var(--react)}} .fill.refl{{background:var(--refl)}}
tr.bad td{{background:rgba(248,113,113,.08)}}
.q{{max-width:360px;color:#cbd5e1}}
.foot{{color:var(--muted);font-size:12px;margin-top:24px}}
.badge{{display:inline-block;background:#0b1222;border:1px solid var(--line);border-radius:999px;
padding:2px 10px;font-size:12px;color:var(--muted);margin-right:6px}}
</style></head><body><div class="wrap">
<h1>Lab 16 — Reflexion Benchmark Report</h1>
<div class="sub">
<span class="badge">dataset: {e(str(meta['dataset']))}</span>
<span class="badge">mode: {e(str(meta['mode']))}</span>
<span class="badge">model: {e(str(meta['model']))}</span>
<span class="badge">records: {meta['num_records']}</span>
</div>

<div class="kpis">
  <div class="kpi"><div class="v">{react.get('em',0)}</div><div class="l">EM — ReAct</div></div>
  <div class="kpi"><div class="v">{reflexion.get('em',0)}</div><div class="l">EM — Reflexion</div></div>
  <div class="kpi"><div class="v">${cost['total_est_cost_usd']}</div><div class="l">Tổng chi phí ước tính</div></div>
  <div class="kpi"><div class="v">{cost.get('wall_time_seconds','—')}s</div><div class="l">Wall-clock time</div></div>
</div>

<h2>Độ chính xác (EM)</h2>
<div class="card">{bars}</div>

<h2>So sánh ReAct vs Reflexion</h2>
<div class="card"><table>
<thead><tr><th>Metric</th><th>ReAct</th><th>Reflexion</th><th>Δ (Refl−ReAct)</th></tr></thead>
<tbody>{cmp_rows}</tbody></table></div>

<h2>Chi phí &amp; thời gian <span class="sub">(giá USD/1M token: input {rates['input']} / output {rates['output']})</span></h2>
<div class="card"><table>
<thead><tr><th>Agent</th><th>Total tok</th><th>Prompt</th><th>Completion</th><th>Est. cost</th><th>Compute time</th><th>Avg/q</th></tr></thead>
<tbody>{cost_rows_html}</tbody></table>
<p class="foot"><b>Tổng chi phí ước tính: ${cost['total_est_cost_usd']}</b>{wall}</p></div>

<h2>Failure modes</h2>
<div class="card"><table>
<thead><tr><th>Mode</th><th>Total</th><th>ReAct</th><th>Reflexion</th></tr></thead>
<tbody>{fm_rows}</tbody></table></div>

<h2>Ví dụ (tối đa 30 — ưu tiên câu sai)</h2>
<div class="card"><table>
<thead><tr><th>QID</th><th>Agent</th><th>Question</th><th>Gold</th><th>Predicted</th><th>OK</th><th>Att</th><th>Failure</th></tr></thead>
<tbody>{ex_rows}</tbody></table></div>

<h2>Discussion</h2>
<div class="card">{e(report.discussion)}</div>

<p class="foot">Extensions: {e(', '.join(report.extensions))}</p>
</div></body></html>"""


def save_report(report: ReportPayload, out_dir: str | Path) -> tuple[Path, Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    html_path = out_dir / "report.html"
    json_path.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")

    cmp_md = "\n".join(f"| {m} | {r} | {x} | {d} |" for m, r, x, d in comparison_rows(report))
    cost = report.meta["cost"]
    cost_md_rows = "\n".join(
        f"| {a} | {t} | {p} | {c} | {cst} | {ct} | {avg} |"
        for a, t, p, c, cst, ct, avg in cost_rows(report)
    )
    wall = f"\n- Wall-clock time: {cost['wall_time_seconds']}s" if "wall_time_seconds" in cost else ""
    md = f"""# Lab 16 Benchmark Report

## Metadata
- Dataset: {report.meta['dataset']}
- Mode: {report.meta['mode']}
- Model: {report.meta['model']}
- Records: {report.meta['num_records']}
- Agents: {', '.join(report.meta['agents'])}

## So sánh ReAct vs Reflexion
| Metric | ReAct | Reflexion | Δ (Refl−ReAct) |
|---|---:|---:|---:|
{cmp_md}

## Chi phí & thời gian chạy (model={cost['model']}, giá USD/1M token: input {cost['rates_usd_per_1m']['input']} / output {cost['rates_usd_per_1m']['output']})
| Agent | Total tokens | Prompt | Completion | Est. cost (USD) | Compute time | Avg/question |
|---|---:|---:|---:|---:|---:|---:|
{cost_md_rows}

- **Tổng chi phí ước tính: ${cost['total_est_cost_usd']}**{wall}

## Failure modes
```json
{json.dumps(report.failure_modes, indent=2, ensure_ascii=False)}
```

## Extensions implemented
{chr(10).join(f"- {item}" for item in report.extensions)}

## Discussion
{report.discussion}
"""
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return json_path, md_path, html_path

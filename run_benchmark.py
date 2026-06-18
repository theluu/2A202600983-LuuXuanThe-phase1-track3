from __future__ import annotations
import time
from pathlib import Path
import typer
from rich import print
from src.reflexion_lab.agents import ReActAgent, ReflexionAgent
from src.reflexion_lab.reporting import build_report, print_tables, save_report
from src.reflexion_lab.runtime import get_runtime
from src.reflexion_lab.utils import load_dataset, save_jsonl
app = typer.Typer(add_completion=False)

@app.command()
def main(dataset: str = "data/hotpot_mini.json", out_dir: str = "outputs/sample_run",
         reflexion_attempts: int = 4, runtime: str = "mock", adaptive: bool = True) -> None:
    """Chạy benchmark ReAct + Reflexion và in bảng so sánh + bảng chi phí.

    Ví dụ chạy golden test set:
        python run_benchmark.py --dataset data/golden.json --runtime openai --out-dir outputs/golden_run
    runtime: "mock" (deterministic, không cần API key) hoặc "openai" (LLM thật).
    """
    examples = load_dataset(dataset)
    rt = get_runtime(runtime)
    model = getattr(rt, "model", rt.name)
    react = ReActAgent(runtime=rt)
    reflexion = ReflexionAgent(max_attempts=reflexion_attempts, runtime=rt, adaptive=adaptive)

    print(f"[cyan]Dataset:[/cyan] {dataset} ({len(examples)} câu) | [cyan]runtime:[/cyan] {rt.name} | [cyan]model:[/cyan] {model}")
    start = time.perf_counter()
    try:
        react_records = [react.run(example) for example in examples]
        reflexion_records = [reflexion.run(example) for example in examples]
    except Exception as ex:
        from src.reflexion_lab.llm_runtime import LLMConfigError
        if isinstance(ex, LLMConfigError):
            print(f"\n[bold red]Không chạy được LLM:[/bold red] {ex}")
            raise typer.Exit(code=1)
        raise
    wall_seconds = time.perf_counter() - start
    all_records = react_records + reflexion_records

    out_path = Path(out_dir)
    save_jsonl(out_path / "react_runs.jsonl", react_records)
    save_jsonl(out_path / "reflexion_runs.jsonl", reflexion_records)
    report = build_report(all_records, dataset_name=Path(dataset).name, mode=rt.name,
                          model=model, wall_seconds=wall_seconds)
    json_path, md_path, html_path = save_report(report, out_path)

    print_tables(report)
    print(f"[green]Saved[/green] {json_path}")
    print(f"[green]Saved[/green] {md_path}")
    print(f"[green]Saved[/green] {html_path}  [dim](mở bằng trình duyệt để xem trực quan)[/dim]")

if __name__ == "__main__":
    app()

from __future__ import annotations

from typing import Any

from ..db import Database


def compare_eval_runs(db: Database, run_ids: list[int]) -> dict[str, Any]:
    if len(set(run_ids)) < 2:
        raise ValueError("At least two different evaluation runs are required")
    runs = []
    for run_id in run_ids:
        run = db.get_eval_run(run_id)
        if not run:
            raise ValueError(f"Evaluation run {run_id} not found")
        if run["status"] != "COMPLETED":
            raise ValueError(f"Evaluation run {run_id} is not completed")
        runs.append(run)

    case_ids = {int(run["eval_case_id"]) for run in runs}
    if len(case_ids) != 1:
        raise ValueError("Evaluation runs must use the same evaluation case")
    metric_sets = {str(run["config"].get("metric_set", "")) for run in runs}
    if len(metric_sets) != 1:
        raise ValueError("Evaluation runs must use the same metric set")

    score_maps: list[dict[tuple[str, str, str], dict[str, Any]]] = []
    for run in runs:
        score_maps.append(
            {
                (score["metric_name"], score["evaluator"], score["version"]): score
                for score in run["scores"]
            }
        )
    metric_keys = sorted(set().union(*(score_map.keys() for score_map in score_maps)))
    metrics = []
    baseline_map = score_maps[0]
    for key in metric_keys:
        baseline_score = baseline_map.get(key)
        baseline_value = float(baseline_score["value"]) if baseline_score else None
        values = []
        for run, score_map in zip(runs, score_maps):
            score = score_map.get(key)
            value = float(score["value"]) if score else None
            values.append(
                {
                    "eval_run_id": run["id"],
                    "value": value,
                    "passed": score["passed"] if score else None,
                    "delta_from_baseline": None if value is None or baseline_value is None else round(value - baseline_value, 6),
                }
            )
        metrics.append(
            {
                "metric_name": key[0],
                "evaluator": key[1],
                "version": key[2],
                "values": values,
            }
        )

    return {
        "eval_case_id": runs[0]["eval_case_id"],
        "metric_set": runs[0]["config"].get("metric_set"),
        "baseline_run_id": runs[0]["id"],
        "runs": [
            {
                "id": run["id"],
                "generation_run_id": run["generation_run_id"],
                "started_at": run["started_at"],
                "completed_at": run["completed_at"],
            }
            for run in runs
        ],
        "metrics": metrics,
    }

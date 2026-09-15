#!/usr/bin/env python3
"""Chạy bộ đánh giá LLM tiếng Việt và xuất báo cáo JSON/Markdown."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from providers import ModelClient, ProviderError


CRITERIA = ("dung_y", "tieng_viet", "khong_bia", "giu_ngu_canh")
CRITERIA_VI = {
    "dung_y": "Đúng ý",
    "tieng_viet": "Tiếng Việt",
    "khong_bia": "Không bịa",
    "giu_ngu_canh": "Giữ ngữ cảnh",
}
JUDGE_SYSTEM = """Bạn là giám khảo nghiêm khắc cho hội thoại AI tiếng Việt.
Chấm từng tiêu chí bằng số nguyên 1-5:
- dung_y: trả lời đúng yêu cầu và tiêu chí riêng của task.
- tieng_viet: tiếng Việt tự nhiên, rõ ràng, phù hợp ngữ cảnh.
- khong_bia: không tự tạo dữ kiện, chính sách, giá hoặc nguồn không có căn cứ.
- giu_ngu_canh: hiểu và giữ đúng thông tin xuyên suốt các lượt.

Chỉ trả về một JSON hợp lệ đúng dạng:
{"scores":{"dung_y":1,"tieng_viet":1,"khong_bia":1,"giu_ngu_canh":1},"verdict":"pass|weak|fail","note":"nhận xét ngắn"}
Không thêm markdown hay nội dung ngoài JSON."""


def parse_args() -> argparse.Namespace:
    """Đọc tham số CLI."""
    parser = argparse.ArgumentParser(
        description="Chạy và tự chấm bộ test LLM tiếng Việt MONA AI Lab."
    )
    parser.add_argument("--provider", required=True, choices=("openai", "anthropic"))
    parser.add_argument("--model", required=True, help="Model ID cần đánh giá")
    parser.add_argument(
        "--judge-provider", required=True, choices=("anthropic", "openai")
    )
    parser.add_argument("--judge-model", required=True, help="Model ID dùng để chấm")
    parser.add_argument("--tasks", default="tasks/", help="Thư mục chứa các file .jsonl")
    parser.add_argument("--out", default="out/", help="Thư mục ghi báo cáo")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout API, giây")
    parser.add_argument("--retries", type=int, default=3, help="Số lần thử mỗi API call")
    args = parser.parse_args()
    if args.timeout <= 0 or args.retries < 1:
        parser.error("--timeout phải > 0 và --retries phải >= 1")
    return args


def load_tasks(directory: Path) -> list[dict[str, Any]]:
    """Đọc và kiểm tra sơ bộ mọi dòng JSONL theo thứ tự tên file."""
    files = sorted(directory.glob("*.jsonl"))
    if not files:
        raise ValueError(f"Không tìm thấy file .jsonl trong {directory}")

    tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                try:
                    task = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"JSON lỗi tại {path}:{line_no}: {exc}") from exc
                required = ("id", "category", "system", "turns", "checks", "judge")
                missing = [key for key in required if key not in task]
                if missing:
                    raise ValueError(f"{path}:{line_no} thiếu trường: {', '.join(missing)}")
                if not isinstance(task["turns"], list) or not task["turns"]:
                    raise ValueError(f"{path}:{line_no} cần ít nhất một phần tử turns")
                if not isinstance(task["checks"], list):
                    raise ValueError(f"{path}:{line_no} checks phải là một mảng")
                if task["id"] in seen_ids:
                    raise ValueError(f"Task ID bị trùng: {task['id']}")
                seen_ids.add(task["id"])
                task["source"] = f"{path}:{line_no}"
                tasks.append(task)
    if not tasks:
        raise ValueError(f"Không có task hợp lệ trong {directory}")
    return tasks


def run_conversation(task: dict[str, Any], client: ModelClient, model: str) -> list[dict[str, str]]:
    """Chạy lần lượt từng turn và giữ toàn bộ lịch sử."""
    history: list[dict[str, str]] = []
    transcript = [{"role": "system", "content": str(task["system"])}]
    for turn in task["turns"]:
        user_message = {"role": "user", "content": str(turn)}
        history.append(user_message)
        transcript.append(user_message.copy())
        answer = client.generate(model, history, system=str(task["system"]))
        assistant_message = {"role": "assistant", "content": answer}
        history.append(assistant_message)
        transcript.append(assistant_message.copy())
    return transcript


def run_checks(checks: list[dict[str, Any]], answer: str) -> list[dict[str, Any]]:
    """Chạy regex checks trên câu trả lời cuối."""
    results = []
    for check in checks:
        check_type = check.get("type")
        pattern = check.get("value")
        error = None
        matched = False
        try:
            if not isinstance(pattern, str):
                raise ValueError("value phải là chuỗi regex")
            matched = re.search(pattern, answer, flags=re.IGNORECASE | re.MULTILINE) is not None
            if check_type == "must_not_contain":
                passed = not matched
            elif check_type in ("must_contain", "regex_ok"):
                passed = matched
            else:
                raise ValueError(f"check type không hỗ trợ: {check_type}")
        except (re.error, ValueError) as exc:
            passed = False
            error = str(exc)
        results.append(
            {
                "type": check_type,
                "value": pattern,
                "passed": passed,
                "matched": matched,
                **({"error": error} if error else {}),
            }
        )
    return results


def extract_json(text: str) -> dict[str, Any]:
    """Đọc JSON kể cả khi model vô tình bọc trong code fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Judge không trả về JSON")
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Kết quả judge phải là JSON object")
    return value


def validate_judgement(value: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hoá và xác thực kết quả judge."""
    scores = value.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("Judge thiếu scores")
    normalized_scores = {}
    for criterion in CRITERIA:
        score = scores.get(criterion)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 1 <= score <= 5:
            raise ValueError(f"Điểm {criterion} phải nằm trong 1-5")
        normalized_scores[criterion] = int(score) if float(score).is_integer() else float(score)
    verdict = value.get("verdict")
    if verdict not in ("pass", "weak", "fail"):
        raise ValueError("verdict phải là pass, weak hoặc fail")
    return {
        "scores": normalized_scores,
        "verdict": verdict,
        "note": str(value.get("note", "")).strip(),
    }


def judge_task(
    task: dict[str, Any], transcript: list[dict[str, str]], client: ModelClient, model: str
) -> dict[str, Any]:
    """Gửi transcript và tiêu chí riêng cho LLM judge."""
    payload = {
        "task_id": task["id"],
        "tieu_chi_rieng": task["judge"],
        "transcript": transcript,
    }
    prompt = "Hãy chấm hội thoại sau theo rubric trong system prompt:\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )
    raw = client.generate(
        model, [{"role": "user", "content": prompt}], system=JUDGE_SYSTEM, json_mode=True
    )
    result = validate_judgement(extract_json(raw))
    result["raw"] = raw
    return result


def check_rate(checks: list[dict[str, Any]]) -> float:
    """Tính tỷ lệ check; task không có check được xem là 100%."""
    return sum(item["passed"] for item in checks) / len(checks) if checks else 1.0


def normalized_score(judgement: dict[str, Any], checks: list[dict[str, Any]]) -> float | None:
    """Chuẩn hoá: judge 80 điểm và rule-check 20 điểm."""
    if "scores" not in judgement:
        return None
    judge_average = sum(judgement["scores"].values()) / len(CRITERIA)
    return round((judge_average / 5 * 80) + (check_rate(checks) * 20), 2)


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Tổng hợp theo category và toàn bộ bộ test."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        groups[result["category"]].append(result)
    groups["__overall__"] = results

    output = {}
    for name, items in groups.items():
        judged = [item for item in items if "scores" in item.get("llm_judge", {})]
        all_checks = [check for item in items for check in item.get("checks", [])]
        scores = {
            criterion: round(
                sum(item["llm_judge"]["scores"][criterion] for item in judged) / len(judged), 2
            )
            if judged
            else None
            for criterion in CRITERIA
        }
        verdicts = {verdict: 0 for verdict in ("pass", "weak", "fail")}
        for item in judged:
            verdicts[item["llm_judge"]["verdict"]] += 1
        task_scores = [item["score_100"] for item in items if item.get("score_100") is not None]
        output[name] = {
            "tasks": len(items),
            "completed": len(judged),
            "errors": sum("error" in item for item in items),
            "average_scores": scores,
            "check_pass_percent": round(
                100 * sum(check["passed"] for check in all_checks) / len(all_checks), 2
            )
            if all_checks
            else 100.0,
            "verdicts": verdicts,
            "score_100": round(sum(task_scores) / len(task_scores), 2) if task_scores else None,
        }
    return {"overall": output.pop("__overall__"), "by_category": output}


def markdown_report(report: dict[str, Any]) -> str:
    """Tạo báo cáo Markdown tiếng Việt."""
    meta, overall = report["meta"], report["aggregate"]["overall"]
    lines = [
        "# Báo cáo đánh giá LLM tiếng Việt",
        "",
        f"- Model mục tiêu: `{meta['provider']}/{meta['model']}`",
        f"- Model chấm: `{meta['judge_provider']}/{meta['judge_model']}`",
        f"- Số task: {overall['tasks']} (hoàn tất: {overall['completed']}, lỗi: {overall['errors']})",
        f"- Điểm tổng hợp: **{overall['score_100'] if overall['score_100'] is not None else 'N/A'}/100**",
        "- Công thức: 80% điểm trung bình LLM-judge + 20% tỷ lệ rule-check.",
        "",
        "## Tổng hợp",
        "",
        "| Phạm vi | Task | Đúng ý | Tiếng Việt | Không bịa | Giữ ngữ cảnh | Check pass | Verdict P/W/F | Điểm /100 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def row(name: str, data: dict[str, Any]) -> str:
        scores = data["average_scores"]
        shown = ["N/A" if scores[key] is None else str(scores[key]) for key in CRITERIA]
        verdicts = data["verdicts"]
        final_score = "N/A" if data["score_100"] is None else data["score_100"]
        return (
            f"| {name} | {data['tasks']} | {' | '.join(shown)} | "
            f"{data['check_pass_percent']}% | {verdicts['pass']}/{verdicts['weak']}/{verdicts['fail']} | {final_score} |"
        )

    lines.append(row("Tổng", overall))
    for category, data in sorted(report["aggregate"]["by_category"].items()):
        lines.append(row(category, data))

    lines.extend(
        [
            "",
            "## Chi tiết từng task",
            "",
            "| Task | Category | Check pass | Verdict | Điểm /100 | Ghi chú |",
            "|---|---|---:|---|---:|---|",
        ]
    )
    for item in report["tasks"]:
        checks = item.get("checks", [])
        passed = f"{sum(check['passed'] for check in checks)}/{len(checks)}" if checks else "—"
        judgement = item.get("llm_judge", {})
        note = str(judgement.get("note", item.get("error", ""))).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {item['id']} | {item['category']} | {passed} | "
            f"{judgement.get('verdict', 'error')} | {item.get('score_100', 'N/A')} | {note} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    """Điều phối chạy task, chấm và ghi hai báo cáo."""
    args = parse_args()
    try:
        tasks = load_tasks(Path(args.tasks))
        target_client = ModelClient(args.provider, args.timeout, args.retries)
        judge_client = ModelClient(args.judge_provider, args.timeout, args.retries)
    except (OSError, ValueError, ProviderError) as exc:
        print(f"Lỗi khởi tạo: {exc}", file=sys.stderr)
        return 2

    results = []
    total = len(tasks)
    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{total}] Đang chạy {task['id']}...", flush=True)
        result: dict[str, Any] = {
            "id": task["id"],
            "category": task["category"],
            "source": task["source"],
        }
        try:
            transcript = run_conversation(task, target_client, args.model)
            answer = transcript[-1]["content"]
            checks = run_checks(task["checks"], answer)
            result.update(
                {"final_answer": answer, "transcript": transcript, "checks": checks}
            )
            judgement = judge_task(task, transcript, judge_client, args.judge_model)
            result.update(
                {
                    "llm_judge": judgement,
                    "score_100": normalized_score(judgement, checks),
                }
            )
            print(f"[{index}/{total}] Xong {task['id']}: {result['score_100']}/100", flush=True)
        except Exception as exc:
            result["error"] = str(exc)
            result.setdefault("checks", [])
            print(f"[{index}/{total}] Lỗi {task['id']}: {exc}", file=sys.stderr, flush=True)
        results.append(result)

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": args.provider,
            "model": args.model,
            "judge_provider": args.judge_provider,
            "judge_model": args.judge_model,
            "tasks_directory": str(Path(args.tasks)),
            "score_formula": "80% judge average (1-5) + 20% rule-check pass rate",
        },
        "tasks": results,
        "aggregate": aggregate(results),
    }
    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out_dir / "report.md").write_text(markdown_report(report), encoding="utf-8")
    except OSError as exc:
        print(f"Không thể ghi báo cáo: {exc}", file=sys.stderr)
        return 2

    print(f"Đã ghi {out_dir / 'report.json'} và {out_dir / 'report.md'}")
    return 1 if any("error" in item for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

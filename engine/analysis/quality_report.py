import json
from pathlib import Path

from engine.analysis.visual_analyzer import VisualAnalysis, analyze_visual_quality, grade_label, risk_label
from engine.config import EnhancementProfile
from engine.config.processing_strategy import ProcessingStrategy
from engine.rules.rule_loader import RuleSet


def build_quality_report(
    image,
    profile: EnhancementProfile,
    rule_pack: dict | None = None,
    analysis: VisualAnalysis | dict | None = None,
    after_analysis: VisualAnalysis | dict | None = None,
    strategy: ProcessingStrategy | dict | None = None,
    rules: RuleSet | dict | None = None,
) -> dict:
    if analysis is None:
        analysis_obj = analyze_visual_quality(image, rule_pack)
    elif isinstance(analysis, VisualAnalysis):
        analysis_obj = analysis
    else:
        analysis_obj = VisualAnalysis(**analysis)

    if after_analysis is None:
        after_obj = analyze_visual_quality(image, rule_pack)
    elif isinstance(after_analysis, VisualAnalysis):
        after_obj = after_analysis
    else:
        after_obj = VisualAnalysis(**after_analysis)

    if isinstance(strategy, ProcessingStrategy):
        strategy_data = strategy.to_dict()
    elif isinstance(strategy, dict):
        strategy_data = strategy
    else:
        strategy_data = {}

    if isinstance(rules, RuleSet):
        rules_applied = rules.source_paths()
    elif isinstance(rules, dict):
        rules_applied = rules.get("source_paths", [])
    else:
        rules_applied = []

    return {
        "premium_score": int(after_obj.premium_score),
        "ai_noise_risk": risk_label(after_obj.ai_dirty_score),
        "high_frequency_risk": risk_label(after_obj.high_frequency_pollution),
        "mid_frequency_score": round(after_obj.mid_frequency_score * 100),
        "highlight_risk": risk_label(after_obj.highlight_risk),
        "color_harmony_score": round((1.0 - after_obj.color_pollution) * 100),
        "atmosphere_score": round((1.0 - after_obj.atmosphere_deficiency) * 100),
        "recommended_mode": analysis_obj.recommended_mode,
        "selected_mode": profile.name,
        "problems_detected": after_obj.problems_detected,
        "next_actions": after_obj.next_actions,
        "strategy_used": strategy_data,
        "rules_applied": rules_applied,
        "before_scores": analysis_obj.visual_scores,
        "after_scores": after_obj.visual_scores,
        "visual_diagnosis": after_obj.detected_issues,
        "commercial_recommendation": after_obj.next_actions,
        "diagnostics": {
            "high_frequency_pollution": round(after_obj.high_frequency_pollution, 4),
            "ai_dirty_score": round(after_obj.ai_dirty_score, 4),
            "sharpening_risk": round(after_obj.sharpening_risk, 4),
            "highlight_risk": round(after_obj.highlight_risk, 4),
            "color_pollution": round(after_obj.color_pollution, 4),
            "atmosphere_deficiency": round(after_obj.atmosphere_deficiency, 4),
            "commercial_grade": grade_label(after_obj.premium_score / 100),
        },
    }


def report_to_markdown(report: dict, title: str = "VisualMasterPro Quality Report") -> str:
    problems = report.get("problems_detected") or ["未发现明显问题"]
    actions = report.get("next_actions") or ["保持当前处理方向"]

    lines = [
        f"# {title}",
        "",
        "## Summary",
        "",
        f"- premium_score: {report['premium_score']}",
        f"- recommended_mode: {report['recommended_mode']}",
        f"- selected_mode: {report.get('selected_mode', '')}",
        f"- ai_noise_risk: {report['ai_noise_risk']}",
        f"- high_frequency_risk: {report['high_frequency_risk']}",
        f"- mid_frequency_score: {report['mid_frequency_score']}",
        f"- highlight_risk: {report['highlight_risk']}",
        f"- color_harmony_score: {report['color_harmony_score']}",
        f"- atmosphere_score: {report['atmosphere_score']}",
        "",
        "## Problems Detected",
        "",
    ]
    lines.extend(f"- {problem}" for problem in problems)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {action}" for action in actions)
    lines.extend(["", "## Diagnostics", ""])
    for key, value in report.get("diagnostics", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Strategy Used", ""])
    for key, value in report.get("strategy_used", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Rules Applied", ""])
    for source in report.get("rules_applied", []):
        lines.append(f"- {source}")
    lines.append("")
    return "\n".join(lines)


def write_quality_report_json(path: str | Path, report: dict) -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def write_quality_report_markdown(path: str | Path, report: dict, title: str = "VisualMasterPro Quality Report") -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_to_markdown(report, title), encoding="utf-8")
    return True


def write_quality_report(path: str | Path, report: dict) -> bool:
    return write_quality_report_json(path, report)

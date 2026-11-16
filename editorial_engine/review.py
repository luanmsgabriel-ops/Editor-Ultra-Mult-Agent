"""Render-bound review records with explicit coverage and bounded repair state."""

from __future__ import annotations

from .contracts import (EPSILON, SCHEMA_VERSION, clone, digest, index_by_id,
                        integer, interval, mapping, nonempty, number, provenance,
                        require, sequence, sha256, verify_file)
from .planner import assert_plan_digest

CHECKS = {"technical", "motion", "audio", "editorial"}


def _seal(state: dict) -> dict:
    state.pop("review_sha256", None)
    state["review_sha256"] = digest(state)
    return state


def _validate_state(state: dict) -> None:
    mapping(state, "review")
    unsigned = {key: value for key, value in state.items() if key != "review_sha256"}
    require(state.get("review_sha256") == digest(unsigned), "review_hash_mismatch", "Review state changed without validation")
    require(state.get("schema_version") == SCHEMA_VERSION, "schema_version", "Unsupported review version")
    integer(state.get("max_retries"), "review.max_retries")
    integer(state.get("retry_count"), "review.retry_count")
    require(state["retry_count"] <= state["max_retries"], "retry_limit", "Review repair budget exceeded")


def _render(plan: dict, artifact: dict) -> dict:
    assert_plan_digest(plan)
    require(plan.get("validation", {}).get("executable") is True, "plan_not_executable", "Review requires a file-verified executable plan")
    result = clone(mapping(artifact, "rendered_artifact"))
    require(result.get("plan_sha256") == plan["plan_sha256"], "render_plan_mismatch", "Render belongs to another plan revision")
    require(result.get("clock") == "output", "clock_mismatch", "Rendered review coverage must use the output clock")
    sha256(result.get("sha256"), "rendered_artifact.sha256")
    number(result.get("duration_s"), "rendered_artifact.duration_s", minimum=EPSILON)
    verify_file(result.get("path"), result["sha256"], "rendered_artifact.path")
    if "decision_ids" in result:
        decision_ids = sequence(result["decision_ids"], "rendered_artifact.decision_ids")
        known = {decision["id"] for decision in plan["decisions"]}
        require(bool(decision_ids) and all(isinstance(item, str) and item in known for item in decision_ids),
                "render_scope", "Render refers to an unknown or empty decision scope")
        require(len(decision_ids) == len(set(decision_ids)), "render_scope", "Render repeats a decision ID")
    return result


def new_review(plan: dict, rendered_artifact: dict, *, max_retries: int = 2) -> dict:
    artifact = _render(plan, rendered_artifact)
    integer(max_retries, "max_retries")
    used = sum(1 for entry in plan.get("history", []) if entry.get("render_sha256"))
    require(used <= max_retries, "retry_limit", "Plan has already consumed this repair budget")
    return _seal({
        "schema_version": SCHEMA_VERSION, "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"], "render_sha256": artifact["sha256"],
        "rendered_artifact": artifact, "max_retries": max_retries, "retry_count": used,
        "reports": [], "archived_reviews": [], "status": "unverified",
        "technical": "unverified", "perceptual": "unverified", "user_approval": "pending",
        "coverage": {check: {"status": "unverified", "covered_seconds": 0.0} for check in sorted(CHECKS)},
        "can_finalize": False, "can_accept_render": False,
        "scope_complete": "decision_ids" not in artifact or set(artifact["decision_ids"]) == {d["id"] for d in plan["decisions"]},
        "scope": "declared_render_decisions" if "decision_ids" in artifact else "entire_plan_render",
    })


def _covered(ranges: list[dict], duration_s: float) -> tuple[bool, float]:
    cursor, covered = 0.0, 0.0
    for item in sorted(ranges, key=lambda value: (value["start_s"], value["end_s"])):
        start, end = item["start_s"], item["end_s"]
        if end <= cursor:
            continue
        covered += end - max(start, cursor)
        cursor = end
    # Sum coverage cannot bridge gaps or silently turn samples into playback.
    return covered >= duration_s - EPSILON, round(covered, 8)


def _aggregate(state: dict) -> None:
    duration_s = state["rendered_artifact"]["duration_s"]
    coverage = {}
    for check_name in sorted(CHECKS):
        failed, accepted_ranges, partial_ranges = False, [], []
        for report in state["reports"]:
            check = report["checks"].get(check_name)
            if check is None:
                continue
            if check["status"] == "fail":
                failed = True
            if check["status"] != "pass":
                continue
            partial_ranges.extend(check["coverage"])
            continuous = check["mode"] == "continuous"
            if check_name == "technical":
                admissible = continuous or check["mode"] == "metadata"
            else:
                admissible = continuous and report["reviewer"]["kind"] in {"human", "model", "user"}
            if admissible:
                accepted_ranges.extend(check["coverage"])
        complete, seconds = _covered(accepted_ranges, duration_s)
        coverage[check_name] = {
            "status": "failed" if failed else ("passed" if complete else "unverified"),
            "covered_seconds": seconds,
            "claimed_pass_seconds": _covered(partial_ranges, duration_s)[1],
        }
    state["coverage"] = coverage
    state["technical"] = coverage["technical"]["status"]
    perceptual = [coverage[key]["status"] for key in ("motion", "audio", "editorial")]
    state["perceptual"] = "failed" if "failed" in perceptual else ("passed" if all(item == "passed" for item in perceptual) else "unverified")
    approvals = [report["approval"]["status"] for report in state["reports"] if report.get("approval")]
    state["user_approval"] = "rejected" if "rejected" in approvals else ("approved" if "approved" in approvals else "pending")
    failed = state["technical"] == "failed" or state["perceptual"] == "failed" or state["user_approval"] == "rejected"
    complete = state["technical"] == "passed" and state["perceptual"] == "passed"
    if failed:
        state["status"] = "exhausted" if state["retry_count"] >= state["max_retries"] else "needs_revision"
    elif complete:
        state["status"] = "user_approved" if state["user_approval"] == "approved" else "reviewed"
        if not state.get("scope_complete", False):
            state["status"] += "_partial"
    else:
        state["status"] = "unverified"
    state["can_accept_render"] = complete and not failed
    state["can_finalize"] = complete and not failed and state.get("scope_complete", False)


def invalidate_review(review: dict, new_plan_sha256: str, *, reason: str,
                      consume_retry: bool = False) -> dict:
    _validate_state(review)
    sha256(new_plan_sha256, "new_plan_sha256")
    nonempty(reason, "reason")
    result = clone(review)
    if consume_retry:
        require(result["retry_count"] < result["max_retries"], "retry_limit", "Review repair budget is exhausted")
        result["retry_count"] += 1
    result["archived_reviews"].append({
        "plan_sha256": result["plan_sha256"], "render_sha256": result.get("render_sha256"),
        "reports": result["reports"], "status": result["status"], "reason": reason,
    })
    result.update({"plan_sha256": new_plan_sha256, "render_sha256": None, "rendered_artifact": None,
                   "reports": [], "status": "stale", "technical": "unverified", "perceptual": "unverified",
                   "user_approval": "pending", "can_finalize": False, "can_accept_render": False,
                   "scope_complete": False, "invalidated_because": reason,
                   "coverage": {check: {"status": "unverified", "covered_seconds": 0.0} for check in sorted(CHECKS)}})
    return _seal(result)


def add_review(review: dict, plan: dict, rendered_artifact: dict, report: dict) -> dict:
    """Bind a report to current bytes; old plan/render reports never carry over.

    Samples can document useful findings. Even a report labeled ``pass`` remains
    perceptually unverified unless its continuous coverage spans this render.
    """
    _validate_state(review)
    artifact = _render(plan, rendered_artifact)
    result = clone(review)
    if result["plan_sha256"] != plan["plan_sha256"]:
        return invalidate_review(result, plan["plan_sha256"], reason="plan_changed_before_review")
    if result.get("render_sha256") not in {None, artifact["sha256"]}:
        result = invalidate_review(result, plan["plan_sha256"], reason="render_bytes_changed")
    elif result.get("rendered_artifact") is not None:
        prior = result["rendered_artifact"]
        if any(prior.get(key) != artifact.get(key) for key in ("duration_s", "clock", "decision_ids")):
            result = invalidate_review(result, plan["plan_sha256"], reason="render_scope_or_clock_changed")
    result["rendered_artifact"] = artifact
    result["render_sha256"] = artifact["sha256"]
    item = clone(mapping(report, "report"))
    nonempty(item.get("id"), "report.id")
    require(item["id"] not in {old["id"] for old in result["reports"]}, "duplicate_report", "Review report ID already exists")
    require(item.get("plan_sha256") == plan["plan_sha256"] and item.get("render_sha256") == artifact["sha256"],
            "stale_report", "Report refers to an older plan or render")
    require(item.get("clock", "output") == "output", "clock_mismatch", "Review report intervals must use the output clock")
    provenance(item.get("reviewer"), "report.reviewer", kinds={"tool", "model", "human", "user"})
    checks = mapping(item.get("checks"), "report.checks")
    require(set(checks) <= CHECKS, "review_check", "Unknown review dimension")
    require(bool(checks) or bool(item.get("approval")), "empty_review", "Report must contain checks or an explicit user response")
    for check_name, raw in checks.items():
        check = mapping(raw, "report.checks." + check_name)
        require(check.get("status") in ("pass", "fail", "unverified"), "review_status", "Unsupported check status")
        require(check.get("mode") in ("continuous", "sampled", "metadata", "unverified"), "review_mode", "Unsupported review mode")
        coverage = sequence(check.get("coverage"), "report.checks." + check_name + ".coverage")
        for time_range in coverage:
            interval(time_range, "report.checks." + check_name + ".coverage", duration_s=artifact["duration_s"])
        nonempty(check.get("notes"), "report.checks." + check_name + ".notes")
    if item.get("approval") is not None:
        approval = mapping(item["approval"], "report.approval")
        require(item["reviewer"]["kind"] == "user", "approval_provenance", "Only an explicit user response may record user approval")
        require(approval.get("status") in ("approved", "rejected"), "approval_status", "Unsupported user response")
        nonempty(approval.get("confirmation"), "report.approval.confirmation")
    result["reports"].append(item)
    result["scope"] = "declared_render_decisions" if "decision_ids" in artifact else "entire_plan_render"
    result["scope_complete"] = "decision_ids" not in artifact or set(artifact["decision_ids"]) == {d["id"] for d in plan["decisions"]}
    _aggregate(result)
    return _seal(result)

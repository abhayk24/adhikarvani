"""Deterministic eligibility engine (three-valued logic) and question planner.

Rules compiled from a document are evaluated in code, not by an LLM:
  * True / False / Unknown (None) logic means a missing fact never becomes a guess.
  * An unknown fact only matters if it can still change the verdict, so the
    planner asks for the fact that settles the most undecided rules first.
  * The same compiled rules can be evaluated for millions of citizens at zero
    AI cost, and every verdict is traceable to clause quotes.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Optional

from .models import PolicyCard, Rule, VariableDef
from .variables import ASK_PRIORITY, CANONICAL

OPS = {"==", "!=", ">", ">=", "<", "<=", "in", "not_in"}
Tri = Optional[bool]


class RuleError(ValueError):
    pass


# ------------------------------------------------------------ validation --
def validate_condition(cond: Any, var_defs: dict[str, VariableDef], path: str = "condition") -> list[str]:
    errs: list[str] = []
    if not isinstance(cond, dict) or not cond:
        return [f"{path}: must be an object"]
    if "all" in cond or "any" in cond:
        key = "all" if "all" in cond else "any"
        items = cond[key]
        if not isinstance(items, list) or not items:
            return [f"{path}.{key}: must be a non-empty list"]
        for k, sub in enumerate(items):
            errs += validate_condition(sub, var_defs, f"{path}.{key}[{k}]")
        return errs
    if "not" in cond:
        return validate_condition(cond["not"], var_defs, f"{path}.not")
    var, op = cond.get("var"), cond.get("op")
    if var not in var_defs:
        return [f"{path}: unknown variable '{var}' (define it in new_variables)"]
    if op not in OPS:
        return [f"{path}: unsupported op '{op}'"]
    v = var_defs[var]
    val = cond.get("value")
    if op in ("in", "not_in"):
        if not isinstance(val, list) or not val:
            return [f"{path}: '{op}' needs a non-empty list value"]
        vals = val
    else:
        vals = [val]
    for x in vals:
        if v.type == "number" and (isinstance(x, bool) or not isinstance(x, (int, float))):
            errs.append(f"{path}: '{var}' is a number, got {x!r}")
        elif v.type == "boolean" and not isinstance(x, bool):
            errs.append(f"{path}: '{var}' is yes/no, use true or false, got {x!r}")
        elif v.type == "enum" and str(x).lower() not in [o.lower() for o in (v.options or [])]:
            errs.append(f"{path}: '{x}' is not an option of '{var}'")
    if v.type in ("boolean", "enum", "text") and op in (">", ">=", "<", "<="):
        errs.append(f"{path}: '{op}' cannot be used with {v.type} variable '{var}'")
    return errs


def condition_vars(cond: Any) -> list[str]:
    out: list[str] = []
    if isinstance(cond, dict):
        for key in ("all", "any"):
            for sub in cond.get(key, []) or []:
                out += condition_vars(sub)
        if "not" in cond:
            out += condition_vars(cond["not"])
        if "var" in cond:
            out.append(cond["var"])
    return list(dict.fromkeys(out))


# ------------------------------------------------------------ evaluation --
def _cmp(x: Any, op: str, val: Any) -> bool:
    if op in ("in", "not_in"):
        pool = [str(v).lower() if not isinstance(v, (int, float)) or isinstance(v, bool) else v for v in val]
        xx = str(x).lower() if not isinstance(x, (int, float)) or isinstance(x, bool) else x
        hit = xx in pool
        return hit if op == "in" else not hit
    if isinstance(val, bool) or isinstance(x, bool):
        a, b = bool(x), bool(val)
    elif isinstance(val, (int, float)):
        a, b = float(x), float(val)
    else:
        a, b = str(x).strip().lower(), str(val).strip().lower()
    return {"==": a == b, "!=": a != b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]


def eval_condition(cond: dict, profile: dict[str, Any]) -> Tri:
    if "all" in cond:
        vals = [eval_condition(c, profile) for c in cond["all"]]
        if any(v is False for v in vals):
            return False
        return True if all(v is True for v in vals) else None
    if "any" in cond:
        vals = [eval_condition(c, profile) for c in cond["any"]]
        if any(v is True for v in vals):
            return True
        return False if all(v is False for v in vals) else None
    if "not" in cond:
        v = eval_condition(cond["not"], profile)
        return None if v is None else not v
    var = cond.get("var")
    if profile.get(var) is None:
        return None
    try:
        return _cmp(profile[var], cond["op"], cond.get("value"))
    except (TypeError, ValueError, KeyError):
        return None


def evaluate(policy: PolicyCard, profile: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for r in policy.rules:
        res = eval_condition(r.condition, profile)
        vars_ = condition_vars(r.condition)
        rows.append({
            "rule_id": r.id, "kind": r.kind, "description": r.description, "result": res,
            "vars": vars_, "missing": [v for v in vars_ if profile.get(v) is None],
            "claim_id": r.claim_id, "clause_id": r.clause_id, "quote": r.quote,
            # an exclusion that is True means the person is excluded
            "passes": None if res is None else (res if r.kind == "eligibility" else not res),
        })
    if not rows:
        status = "no_rules"
    elif any(x["passes"] is False for x in rows):
        status = "not_eligible"
    elif all(x["passes"] is True for x in rows):
        status = "eligible"
    else:
        status = "needs_info"
    missing = list(dict.fromkeys(v for x in rows if x["passes"] is None for v in x["missing"]))
    var_defs = {v.name: v for v in policy.variables} | CANONICAL
    blocking = [x for x in rows if x["passes"] is False]
    fixable = bool(blocking) and all(
        all(var_defs.get(v) is not None and var_defs[v].actionable for v in x["vars"]) for x in blocking)
    return {"policy_id": policy.id, "title": policy.title, "status": status, "rules": rows,
            "missing": missing, "blocking": [x["rule_id"] for x in blocking], "fixable": fixable}


def plan_next_question(evaluations: Iterable[dict], asked: dict[str, int],
                       var_defs: dict[str, VariableDef]) -> Optional[str]:
    """Pick the unknown fact that can settle the most undecided rules.

    Ties go to the most natural question first (state, age, work, income...)."""
    score: Counter = Counter()
    for ev in evaluations:
        if ev["status"] != "needs_info":
            continue
        for row in ev["rules"]:
            if row["passes"] is not None:
                continue
            missing = [v for v in row["missing"] if asked.get(v, 0) < 2 and v in var_defs]
            for v in missing:
                # who qualifies is asked before who is excluded (a more natural conversation)
                score[v] += 1.0 + (1.0 if len(missing) == 1 else 0.0) + (0.4 if row["kind"] == "eligibility" else 0.0)
    if not score:
        return None

    def prio(v: str) -> tuple:
        return (-score[v], asked.get(v, 0), ASK_PRIORITY.index(v) if v in ASK_PRIORITY else 99, v)

    return sorted(score, key=prio)[0]


def all_var_defs(policies: Iterable[PolicyCard]) -> dict[str, VariableDef]:
    defs = dict(CANONICAL)
    for p in policies:
        for v in p.variables:
            defs.setdefault(v.name, v)
    return defs


def rules_for(policy: PolicyCard) -> list[Rule]:
    return policy.rules

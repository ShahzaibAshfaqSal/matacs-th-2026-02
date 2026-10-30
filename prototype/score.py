"""Rule-based scoring and ranking. No AI in this file.

Reads the admin's criteria config and the extracted facts for each proposal,
then applies mandatory gates, flag rules and weighted scoring. The same inputs
always give the same output.

Usage:
    python score.py                                   # uses facts/expected_facts.json
    python score.py --facts out/extracted_facts.json  # uses facts produced by extract.py
    python score.py --write ../ranking.json           # also writes the ranking file
"""

import argparse
import copy
import json
from pathlib import Path

HERE = Path(__file__).parent
EVALUATION_YEAR = 2026


def value(facts, field):
    entry = facts.get(field) or {}
    if entry.get("status") != "stated":
        return None
    return entry.get("value")


def check_mandatory(cfg, facts):
    """Return (failures, unclear) as lists of human-readable strings."""
    failures, unclear = [], []
    project = cfg["project"]
    for rule in cfg["mandatory"]:
        answer = value(facts, rule["field"])
        if answer == "no":
            failures.append(f"{rule['label']} not held by the bidder")
        elif answer != "yes":
            unclear.append(f"{rule['label']} not clearly confirmed")
        if rule["rule"] == "yes_and_min_amount":
            amount = value(facts, rule["amount_field"])
            minimum = project[rule["min_amount_key"]]
            if amount is None:
                unclear.append(f"{rule['label']}: insurance amount not stated")
            elif amount < minimum:
                failures.append(f"{rule['label']}: insurance ${amount:,.0f} below ${minimum:,.0f}")
    return failures, unclear


def check_hard_limits(cfg, facts):
    """Weighted criteria can carry a hard project limit (budget, max weeks)."""
    failures, missing = [], []
    for crit in cfg["weighted"]:
        if "hard_max_key" not in crit:
            continue
        limit = cfg["project"][crit["hard_max_key"]]
        v = value(facts, crit["field"])
        if v is None:
            missing.append(f"{crit['label'].lower()} not stated, so the {crit['hard_max_text']} cannot be confirmed")
        elif v > limit:
            failures.append(f"{crit['label'].lower()} of {v:,} breaks the {crit['hard_max_text']}")
    return failures, missing


def missing_holds(cfg, facts):
    """Criteria the admin set to 'hold' when the proposal doesn't mention them."""
    holds = []
    for crit in cfg["weighted"]:
        if crit.get("if_missing") != "hold" or "hard_max_key" in crit:
            continue  # hard-limit criteria are already held by check_hard_limits
        fields = crit.get("fields") or [crit["field"]]
        if crit["method"] != "checklist" and all(value(facts, f) is None for f in fields):
            holds.append(f"{crit['label'].lower()} not mentioned")
    return holds


def doubted_answers(cfg, facts):
    """Answers the checks doubted ('unclear') on any scored field need a person."""
    scored = set()
    for crit in cfg["weighted"]:
        if "hard_max_key" in crit:
            continue  # a missing hard-limit value is already flagged by check_hard_limits
        scored.update(crit.get("fields") or [crit["field"]])
    return [f"{f} needs a human check" for f in sorted(scored)
            if (facts.get(f) or {}).get("status") == "unclear"]


def notes_for(cfg, facts):
    """Non-blocking warnings shown to the reviewer next to the score."""
    notes = []
    window = cfg["project"]["experience_window_years"]
    earliest = value(facts, "experience_earliest_year")
    if earliest is not None and earliest < EVALUATION_YEAR - window:
        notes.append(f"experience counted since {earliest} may include installs older than {window} years")
    notes.extend(facts.get("concerns", []))
    return notes


def best_values(cfg, pool):
    best = {}
    for crit in cfg["weighted"]:
        fields = crit.get("fields") or [crit["field"]]
        for f in fields:
            vals = [value(pool[p], f) for p in pool]
            vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if not vals:
                continue
            best[f] = min(vals) if crit["method"] == "lower_is_better" else max(vals)
    return best


def score_proposal(cfg, facts, best):
    """Return {criterion_id: points} for one proposal. Missing numbers score 0."""
    points = {}
    for crit in cfg["weighted"]:
        w = crit["weight"]
        method = crit["method"]
        if method == "higher_is_better":
            v = value(facts, crit["field"])
            points[crit["id"]] = w * v / best[crit["field"]] if v else 0.0
        elif method == "lower_is_better":
            v = value(facts, crit["field"])
            points[crit["id"]] = w * best[crit["field"]] / v if v else 0.0
        elif method == "average_of_higher_is_better":
            parts = [(value(facts, f) or 0) / best[f] for f in crit["fields"]]
            points[crit["id"]] = w * sum(parts) / len(parts)
        elif method == "checklist":
            hits = sum(1 for f in crit["fields"] if value(facts, f) is True)
            points[crit["id"]] = w * hits / len(crit["fields"])
        elif method == "level_scale":
            # For criteria that can't be a number: the AI picked a level from the admin's scale.
            level = value(facts, crit["field"]) or 0
            points[crit["id"]] = w * level / crit["max_level"]
        else:
            raise ValueError(f"unknown scoring method {method}")
    return points


def describe(crit_id, facts):
    if crit_id == "experience":
        return f"{value(facts, 'qualifying_installs')} qualifying installs"
    if crit_id == "price":
        return f"${value(facts, 'total_price_cad'):,.0f}"
    if crit_id == "timeline":
        return f"{value(facts, 'completion_weeks')} weeks"
    if crit_id == "warranty":
        return (f"{value(facts, 'panel_warranty_years')}-year panel, "
                f"{value(facts, 'workmanship_warranty_years')}-year workmanship")
    if crit_id == "team":
        fields = ["named_lead", "crew_stated", "safety_plan", "monitoring_plan"]
        return f"{sum(1 for f in fields if value(facts, f) is True)}/4 team items"
    return crit_id


def build_reason(cfg, facts, points):
    weights = {c["id"]: c["weight"] for c in cfg["weighted"]}
    labels = {c["id"]: c["label"].lower() for c in cfg["weighted"]}
    by_share = sorted(points, key=lambda c: points[c] / weights[c], reverse=True)
    strong = ", ".join(f"{labels[c]} ({describe(c, facts)})" for c in by_share[:2])
    weak = by_share[-1]
    return (f"Passed both mandatory checks; strongest on {strong}; "
            f"weakest on {labels[weak]} ({describe(weak, facts)}).")


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def what_if(cfg, all_facts, pid):
    """For a held proposal: where would it land once a person clears it?
    A missing hard-limit number (e.g. weeks) is tried at the limit and at the best value
    any other bid offers, because the answer can change the top of the ranking."""
    cleared = copy.deepcopy(all_facts)
    facts = cleared[pid]
    facts["injection"] = {"status": "false_alarm", "passages": []}
    facts["injection_attempts"] = []
    missing = [c for c in cfg["weighted"] if "hard_max_key" in c and value(facts, c["field"]) is None]

    def land(f):
        out, res = run(cfg, f, explain=False)
        entry = next(e for e in out if e["proposal"] == pid)
        return entry["rank"], res[pid]["total"]

    if not missing:
        rank, total = land(cleared)
        return f"If a person clears it, it would score {total} and rank {ordinal(rank)}." if rank else ""

    # Only bids that passed the must-have checks count as "the best other bid".
    _, base = run(cfg, all_facts, explain=False)
    eligible = [p for p in all_facts if p != pid and not base[p]["failures"]]
    unit = cfg["project"].get("units", {})
    parts = []
    for c in missing:
        limit = cfg["project"][c["hard_max_key"]]
        best = min(v for v in (value(all_facts[p], c["field"]) for p in eligible) if v is not None)
        label = unit.get(c["field"], "")
        for v, words in ((limit, f"at {limit:,} {label}"), (best, f"at {best:,} {label} or less")):
            trial = copy.deepcopy(cleared)
            trial[pid][c["field"]] = {"value": v, "status": "stated"}
            rank, total = land(trial)
            if rank:
                parts.append(f"{total} ({ordinal(rank)}) {words.strip()}")
    return f"If it gives one, it would score {parts[0]}, up to {parts[-1]}." if parts else ""


def run(cfg, all_facts, explain=True):
    weights_total = sum(c["weight"] for c in cfg["weighted"])
    if weights_total != 100:
        raise ValueError(f"weights add up to {weights_total}, not 100")

    results = {}
    for pid, facts in all_facts.items():
        failures, unclear = check_mandatory(cfg, facts)
        limit_failures, limit_missing = check_hard_limits(cfg, facts)
        flags = list(unclear) + limit_missing + missing_holds(cfg, facts) + doubted_answers(cfg, facts)
        notes = notes_for(cfg, facts)

        injection = facts.get("injection") or {"status": "none", "passages": []}
        where = (injection["passages"] or [{}])[0].get("location", "proposal text")
        if injection["status"] == "suspected" or (injection["status"] == "none" and facts.get("injection_attempts")):
            flags.insert(0, f"possible hidden instruction to automated reviewers ({where}), waiting for a reviewer")
        elif injection["status"] == "confirmed":
            if cfg.get("injection_policy") == "disqualify":
                failures.insert(0, f"confirmed instruction to automated reviewers ({where})")
            else:
                notes.insert(0, f"confirmed instruction to reviewers ({where}) was removed before reading")

        results[pid] = {
            "failures": failures + limit_failures,
            "flags": flags,
            "notes": notes,
        }

    # Relative scores compare against every proposal that passed the gates,
    # including flagged ones, so clearing a flag later does not move anyone else's score.
    pool = {p: all_facts[p] for p in results if not results[p]["failures"]}
    best = best_values(cfg, pool)
    for pid in pool:
        pts = score_proposal(cfg, all_facts[pid], best)
        results[pid]["points"] = pts
        results[pid]["total"] = round(sum(pts.values()), 1)

    ranked = [p for p in pool if not results[p]["flags"]]
    order = {c: i for i, c in enumerate(cfg["tie_break"])}

    def sort_key(p):
        pts = results[p]["points"]
        return (-results[p]["total"], *(-pts[c] for c in order), p)

    ranked.sort(key=sort_key)

    output = []
    for pid in sorted(all_facts):
        r = results[pid]
        if r["failures"]:
            entry = {"proposal": pid, "rank": None, "status": "ineligible", "score": None,
                     "reason": f"Fails mandatory check: {r['failures'][0]}; not scored."}
        elif r["flags"]:
            outlook = what_if(cfg, all_facts, pid) if explain else ""
            entry = {"proposal": pid, "rank": None, "status": "flagged", "score": None,
                     "reason": f"Held for a person to check: {'; '.join(r['flags'])}. {outlook}".strip()}
        else:
            entry = {"proposal": pid, "rank": ranked.index(pid) + 1, "status": "ranked",
                     "score": r["total"], "reason": build_reason(cfg, all_facts[pid], r["points"])}
        output.append(entry)

    status_order = {"ranked": 0, "flagged": 1, "ineligible": 2}
    output.sort(key=lambda e: (status_order[e["status"]], e["rank"] or 0, e["proposal"]))
    return output, results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--criteria", default=HERE / "criteria" / "commercial_solar_v1.json")
    parser.add_argument("--facts", default=HERE / "facts" / "expected_facts.json")
    parser.add_argument("--write", help="path to write ranking.json")
    args = parser.parse_args()

    cfg = json.loads(Path(args.criteria).read_text(encoding="utf-8"))
    all_facts = {k: v for k, v in json.loads(Path(args.facts).read_text(encoding="utf-8")).items()
                 if not k.startswith("_")}

    output, results = run(cfg, all_facts)

    print(f"Category: {cfg['category']} (criteria v{cfg['version']})\n")
    for pid in sorted(results):
        r = results[pid]
        print(f"Proposal {pid}")
        if "points" in r:
            for crit, pts in r["points"].items():
                print(f"  {crit:<11} {pts:6.2f}")
            print(f"  {'TOTAL':<11} {r['total']:6.1f}")
        for f in r["failures"]:
            print(f"  INELIGIBLE: {f}")
        for f in r["flags"]:
            print(f"  FLAG: {f}")
        for n in r["notes"]:
            print(f"  note: {n}")
        print()

    text = json.dumps(output, indent=2)
    print(text)
    if args.write:
        Path(args.write).write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.write}")


if __name__ == "__main__":
    main()

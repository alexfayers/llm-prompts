"""Gate a refine-plan scoring result. Requires evidence for scores >= 7."""

import json
import sys

QUALITY = ["elegance", "simplicity", "readability", "testability", "decoupling", "reusability", "focus"]
CONFIDENCE = ["feasibility", "scope_clarity"]
THRESHOLD = 9.0
EVIDENCE_THRESHOLD = 7


def validate(data: dict) -> dict:
    """Validate scores with evidence, compute averages, and gate."""
    scores = data.get("scores", {})
    evidence = data.get("evidence", {})
    skip_testability = data.get("testability_skipped", False)

    errors: list[str] = []
    categories = [c for c in QUALITY + CONFIDENCE if not (c == "testability" and skip_testability)]

    for cat in categories:
        if cat not in scores:
            errors.append(f"Missing: '{cat}'")
        elif not isinstance(scores[cat], (int, float)) or not 1 <= scores[cat] <= 10:
            errors.append(f"'{cat}' must be 1-10, got {scores[cat]}")
        elif scores[cat] >= EVIDENCE_THRESHOLD and not evidence.get(cat):
            errors.append(f"'{cat}' = {scores[cat]} needs evidence (cite file/pattern/finding)")

    if errors:
        return {"pass": False, "errors": errors}

    q_cats = [c for c in QUALITY if c in scores]
    c_cats = [c for c in CONFIDENCE if c in scores]
    q_avg = sum(scores[c] for c in q_cats) / len(q_cats)
    c_avg = sum(scores[c] for c in c_cats) / len(c_cats)

    below = [{"category": c, "score": scores[c]} for c in categories if scores[c] < THRESHOLD]
    passed = q_avg >= THRESHOLD and c_avg >= THRESHOLD

    return {
        "pass": passed,
        "quality_avg": round(q_avg, 2),
        "confidence_avg": round(c_avg, 2),
        "threshold": THRESHOLD,
        "below_threshold": below,
        "gate_message": (
            f"PASS: quality={q_avg:.1f}, confidence={c_avg:.1f}." if passed
            else f"BLOCKED: quality={q_avg:.1f}, confidence={c_avg:.1f} (need >= {THRESHOLD}). Fix: {', '.join(b['category'] for b in below)}"
        ),
    }


if __name__ == "__main__":
    try:
        data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
    except (json.JSONDecodeError, IndexError) as e:
        print(json.dumps({"pass": False, "errors": [str(e)]}))
        sys.exit(1)
    result = validate(data)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["pass"] else 1)

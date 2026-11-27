"""Backend-independent checks for dimension intent and measured drawing data.

The rule categories distinguish verified drawing metadata, job acceptance
criteria and layout heuristics. No material, tolerance or manufacturing data
are inferred from examples or from this module.
"""
import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

PAPER_MM = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}
# Project validation settings. These tolerances describe numerical comparisons.
MODEL_EPS_MM = .005
PAPER_EPS_MM = .1
DIMENSION_TEXT = re.compile(r"\(?[⌀ØΦR]?[+-]?(?:\d+(?:\.\d+)?)(?:°|[ ]?(?:[A-Za-z]{1,2}\d{1,2})(?:/[A-Za-z]{1,2}\d{1,2})?)?\)?")


def measured_number(value, *, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or abs(value) > 1e7 or (positive and value <= 0)):
        raise ValueError("Expected a finite engineering dimension")
    return float(value)


def dimension_text(text):
    if not isinstance(text, str):
        return False
    text = text.strip()
    return (len(text) <= 64 and bool(DIMENSION_TEXT.fullmatch(text))
            and text.startswith("(") == text.endswith(")"))


def dimension_chain(anchors, dimensions):
    """Check one datum system on one axis. Reference spans do not constrain it."""
    if not isinstance(anchors, dict) or not 2 <= len(anchors) <= 256:
        raise ValueError("A chain needs 2 to 256 identified geometric anchors")
    if not isinstance(dimensions, list) or len(dimensions) > 512:
        raise ValueError("A chain needs a bounded dimension list")
    coordinates = {name: measured_number(value) for name, value in anchors.items()}
    parents = dict(zip(anchors, anchors))
    issues = []
    seen = set()

    def root(anchor):
        while parents[anchor] != anchor:
            anchor = parents[anchor]
        return anchor

    for index, row in enumerate(dimensions):
        start, end = row["start"], row["end"]
        value = measured_number(row["mm"], positive=True)
        reference = row.get("reference", False)
        if type(reference) is not bool or start not in coordinates or end not in coordinates or start == end:
            raise ValueError("A dimension needs two distinct known anchors and a boolean reference flag")
        label = row.get("text")
        if label is not None and not dimension_text(label):
            issues.append({"code": "dimension_text", "row": index})
        delta = abs(coordinates[end] - coordinates[start])
        if abs(delta - value) > MODEL_EPS_MM:
            issues.append({"code": "dimension_value", "row": index, "expectedMm": delta, "actualMm": value})
        span = frozenset((start, end))
        if span in seen:
            issues.append({"code": "duplicate_span", "row": index})
        seen.add(span)
        if reference:
            continue
        a, b = root(start), root(end)
        if a == b:
            issues.append({"code": "closed_chain", "row": index})
        else:
            parents[b] = a
    groups = {}
    for key in anchors:
        groups.setdefault(root(key), []).append(key)
    if len(groups) > 1:
        issues.append({"code": "unlocated_anchors", "groups": list(groups.values())})
    return issues


def text_width_mm(text, height_mm):
    """Paper-space planning estimate. Fonts and visible geometry are checked separately."""
    height_mm = measured_number(height_mm, positive=True)
    if not isinstance(text, str) or len(text) > 120:
        raise ValueError("Expected short annotation text")
    width_units = sum(1 if unicodedata.east_asian_width(char) in "WF" else .62
                      for char in text if not unicodedata.combining(char))
    return width_units * height_mm


def dimension_lanes(spans, text_height_mm, gap_mm=2):
    """Fit short spans first, allowing space for text outside a narrow span."""
    gap_mm = measured_number(gap_mm, positive=True)
    entries = []
    for index, row in enumerate(spans):
        left, right = sorted(measured_number(value) for value in row["paperSpanMm"])
        if left == right:
            raise ValueError("A planned paper span must have a positive length")
        label = text_width_mm(row["text"], text_height_mm)
        right = max(right, left + label + 2 * gap_mm)
        entries.append((index, left, right))
    lanes = []
    result = [None] * len(entries)
    for index, left, right in sorted(entries, key=lambda item: (item[2] - item[1], item[1], item[0])):
        for level, occupied in enumerate(lanes):
            if all(right + gap_mm <= a or b + gap_mm <= left for a, b in occupied):
                occupied.append((left, right))
                break
        else:
            level = len(lanes)
            lanes.append([(left, right)])
        result[index] = level
    return result


def inspect_drawing(plan, drawing):
    """Audit SolidWorks readback, or any host adapter with the same measured fields."""
    size = PAPER_MM[plan["paper"]]
    if plan.get("portrait"):
        size = size[::-1]
    issues = []
    actual = drawing.get("sheetMm", [])
    if len(actual) != 2 or any(abs(a - b) > PAPER_EPS_MM for a, b in zip(actual, size)):
        issues.append({"code": "paper_size", "expectedMm": size, "actualMm": actual})
    if drawing.get("firstAngle") is not True or drawing.get("detailStandard") != 7:
        issues.append({"code": "native_gb_projection"})
    actual_scale = drawing.get("scale", 0)
    if abs(actual_scale - measured_number(plan["view_scale"], positive=True)) > 1e-6:
        issues.append({"code": "sheet_scale", "actual": actual_scale})
    margin = measured_number(plan.get("margin_mm", 5), positive=True)
    regions = []
    view_by_role = {}
    for view in drawing.get("views", []):
        role = view["role"]
        if role in view_by_role:
            issues.append({"code": "duplicate_view", "view": role})
        view_by_role[role] = view
        x1, y1, x2, y2 = view["boundsMm"]
        if not (margin <= x1 < x2 <= size[0] - margin and margin <= y1 < y2 <= size[1] - margin):
            issues.append({"code": "view_outside_sheet", "view": role})
        for key, a, b, c, d in regions:
            if min(x2, c) - max(x1, a) > PAPER_EPS_MM and min(y2, d) - max(y1, b) > PAPER_EPS_MM:
                issues.append({"code": "view_overlap", "views": [key, role]})
        regions.append((role, x1, y1, x2, y2))
    for role, targets in plan.get("views", {}).items():
        view = view_by_role.get(role)
        if view is None:
            issues.append({"code": "missing_view", "view": role})
            continue
        dimensions = view.get("dimensions", [])
        for target in targets:
            numeric = measured_number(target, positive=True)
            hits = sum(abs(row["valueMm"] - numeric) <= MODEL_EPS_MM for row in dimensions)
            if hits == 0:
                issues.append({"code": "missing_native_dimension", "view": role, "mm": numeric})
            if hits > 1 and plan.get("unique_expected_dimensions", False):
                issues.append({"code": "repeated_native_dimension", "view": role, "mm": numeric})
    if "bom" in plan:
        bom = drawing.get("bom", {})
        rows = bom.get("rows", [])
        actual_qty = Counter()
        for row in rows:
            actual_qty[row["part"]] += row["quantity"]
            if row["quantity"] != len(row["names"]):
                issues.append({"code": "bom_instance_quantity", "item": row["item"]})
        if actual_qty != Counter(plan["bom"]):
            issues.append({"code": "bom_quantity", "actual": dict(actual_qty)})
        balloons = Counter(row["item"] for row in bom.get("balloons", []) if row["leaders"] > 0)
        if balloons != Counter(row["item"] for row in rows):
            issues.append({"code": "bom_balloon_link"})
    return issues


def audit(contract, drawing=None):
    issues = []
    for key, chain in contract.get("chains", {}).items():
        issues.extend(dict(issue, chain=key) for issue in dimension_chain(chain["anchors"], chain["dimensions"]))
    if drawing is not None:
        issues.extend(inspect_drawing(contract, drawing))
    return {"passed": not issues, "issues": issues, "native_readback_used": drawing is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", nargs="?", type=Path)
    parser.add_argument("--standard", help="Query the checked national standards catalog")
    parser.add_argument("--native", type=Path)
    args = parser.parse_args()
    if args.standard is not None:
        if args.plan or args.native:
            parser.error("Use standard lookup separately from the drawing audit")
        path = Path(__file__).resolve().parents[1] / "resources" / "omni_gb_standards.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        result = [entry for entry in catalog["rows"] if args.standard.casefold() in entry["standard"].casefold()]
        print(json.dumps(result, ensure_ascii=True))
        return int(not result)
    if args.plan is None:
        parser.error("A drawing plan is required")
    for path in (args.plan, args.native):
        if path is not None and (not path.is_file() or path.stat().st_size > 4_000_000):
            parser.error("Expected a bounded JSON file")
    read = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    native = read(args.native) if args.native else None
    if native is not None:
        native = native.get("reopenedDrawing", native)
    result = audit(read(args.plan), native)
    print(json.dumps(result, ensure_ascii=True))
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())

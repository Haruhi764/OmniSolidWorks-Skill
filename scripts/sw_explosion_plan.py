"""Bounded planning with measured AABBs and explicit installation directions."""
from collections import Counter
from itertools import combinations, product
from math import cos, radians, sin

from sw_incremental_plan import make_plan
from sw_supervisor_state import atomic, read

EPS = .2


def moving(step):
    return step["components"] if "components" in step else [step["component"]]


def step_vector(step):
    direction = step.get("direction")
    if direction is None:
        witnessed = sorted(set(step.get("installation_directions", [])))
        if len(witnessed) != 1:
            raise ValueError("The installation direction must be confirmed")
        direction = witnessed[0]
    if direction not in ("+x", "-x", "+y", "-y", "+z", "-z"):
        raise ValueError("Expected a signed principal installation axis")
    distance = float(step["distance_mm"])
    if not 0 < distance <= 10000:
        raise ValueError("Unexpected explosion distance")
    axis = "xyz".index(direction[1])
    return tuple((distance if direction[0] == "+" else -distance) if i == axis else 0 for i in range(3))


def shifted(box, offset):
    return tuple(value + offset[i % 3] for i, value in enumerate(box))


def sweeps(a, b, relative, tolerance=EPS):
    start, end = 0.0, 1.0
    for axis, speed in enumerate(relative):
        lower = b[axis] - a[axis + 3] + tolerance
        upper = b[axis + 3] - a[axis] - tolerance
        if not speed:
            if not lower < 0 < upper:
                return None
            continue
        first, last = sorted((lower / speed, upper / speed))
        start, end = max(start, first), min(end, last)
        if start >= end:
            return None
    return start, end


def validate_removal_order(steps, precedences):
    """Check caller-confirmed component release order before evaluating paths."""
    start, end = {}, {}
    for index, step in enumerate(steps):
        for component in moving(step):
            start.setdefault(component, index)
            end[component] = index
    for released, dependent in precedences:
        if released not in end or dependent not in start or end[released] >= start[dependent]:
            raise ValueError(f"Release {released} completely before moving {dependent}")

def evaluate_path(boxes, steps, mates=(), *, precedences=()):
    validate_removal_order(steps, precedences)
    current = dict(boxes)
    intended = {frozenset(pair) for pair in mates}
    contacts = Counter()
    records = []
    for step in steps:
        selected = set(moving(step))
        if not selected or not selected <= current.keys():
            raise ValueError("An explosion group has missing components")
        delta = step_vector(step)
        per_step = Counter()
        for left in sorted(selected):
            for right in sorted(current.keys() - selected):
                a, b = current[left], current[right]
                interval = sweeps(a, b, delta)
                if interval is None:
                    continue
                if interval[0] > 1e-9:
                    label = "potential_new_overlap"
                elif frozenset((left, right)) in intended:
                    label = "initial_mate_envelope"
                else:
                    label = "initial_envelope"
                per_step[label] += 1
                contacts[label] += 1
                if len(records) < 50:
                    records.append({"step": step["id"], "pair": [left, right], "category": label,
                                    "fraction": [round(x, 5) for x in interval]})
        for key in selected:
            current[key] = shifted(current[key], delta)
        if per_step:
            records.append({"step": step["id"], "counts": dict(per_step)})
    final = sum(sweeps(a, b, (0, 0, 0)) is not None for a, b in combinations(current.values(), 2))
    return current, {"potential_counts": dict(contacts), "final_overlaps": final, "details": records,
                     "model": "continuous relative swept AABB, potential overlaps only"}


def matmul(left, right):
    return [sum(left[i * 3 + k] * right[k * 3 + j] for k in range(3))
            for i in range(3) for j in range(3)]


def camera_from(baseline, yaw, pitch):
    a, b = radians(yaw), radians(pitch)
    around_y = [cos(a), 0, -sin(a), 0, 1, 0, sin(a), 0, cos(a)]
    around_x = [1, 0, 0, 0, cos(b), sin(b), 0, -sin(b), cos(b)]
    return matmul(matmul(around_y, around_x), baseline[:9]) + baseline[9:]


def project(box, camera):
    corners = product(*[(box[axis], box[axis + 3]) for axis in range(3)])
    points = [tuple(sum(point[k] * camera[k * 3 + i] for k in range(3)) for i in range(3))
              for point in corners]
    return tuple([min(p[i] for p in points) for i in range(2)] +
                 [max(p[i] for p in points) for i in range(2)] +
                 [sum(p[2] for p in points) / 8])


def union_area(rectangles):
    if not rectangles:
        return 0
    xs = sorted({coordinate for rect in rectangles for coordinate in (rect[0], rect[2])})
    area = 0
    for begin, end in zip(xs, xs[1:]):
        covered = 0
        last = -float("inf")
        for low, high in sorted((x[1], x[3]) for x in rectangles if x[0] < end and x[2] > begin):
            covered += max(0, high - max(last, low))
            last = max(last, high)
        area += (end - begin) * covered
    return area


def visual_metrics(boxes, camera):
    rectangles = sorted((project(box, camera) for box in boxes.values()), key=lambda b: -b[4])
    visible = []
    for index, box in enumerate(rectangles):
        clip = [(max(box[0], ahead[0]), max(box[1], ahead[1]), min(box[2], ahead[2]), min(box[3], ahead[3]))
                for ahead in rectangles[:index] if ahead[4] > box[4] + EPS]
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area <= 0:
            raise ValueError("Invalid component projection")
        visible.append(max(0, 1 - union_area([r for r in clip if r[0] < r[2] and r[1] < r[3]]) / area))
    bounds = [max(r[axis + 2] for r in rectangles) - min(r[axis] for r in rectangles) for axis in (0, 1)]
    centers = [((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) for r in rectangles]
    crowded = sum((x - u) ** 2 + (y - v) ** 2 < 225 for (x, y), (u, v) in combinations(centers, 2))
    return {"mean_visible_proxy": sum(visible) / len(visible), "near_hidden": sum(x < .1 for x in visible),
            "spread_mm": bounds, "crowded_centers": crowded}


def select_candidate(boxes, steps, camera, mates):
    before_boxes, before_path = evaluate_path(boxes, steps, mates)
    baseline = visual_metrics(before_boxes, camera)
    baseline_risk = before_path["potential_counts"].get("potential_new_overlap", 0)
    choices = []
    for factor in (1, .95, 1.05, 1.10):
        trial = [{**row, "distance_mm": round(row["distance_mm"] * factor, 6)} for row in steps]
        placed, path = evaluate_path(boxes, trial, mates)
        if path["final_overlaps"] or path["potential_counts"].get("potential_new_overlap", 0) > baseline_risk:
            continue
        for yaw, pitch in product((-55, -38, -20, 0, 20, 38, 55), (-12, 0, 12)):
            view = camera_from(camera, yaw, pitch)
            metrics = visual_metrics(placed, view)
            maximum_extent = max(a / b for a, b in zip(metrics["spread_mm"], baseline["spread_mm"], strict=True))
            if maximum_extent > 1.20 or metrics["near_hidden"] > baseline["near_hidden"]:
                continue
            improvement = (metrics["mean_visible_proxy"] - baseline["mean_visible_proxy"])
            if improvement < .005 and metrics["near_hidden"] >= baseline["near_hidden"]:
                continue
            objective = (metrics["near_hidden"] * -.023 + metrics["mean_visible_proxy"]
                         - metrics["crowded_centers"] * .001 - .012 * maximum_extent - .02 * abs(factor - 1))
            choices.append((objective, factor, yaw, pitch, trial, path, view, metrics))
    if not choices:
        raise ValueError("No measured-envelope candidate improves baseline without added risk")
    _, factor, yaw, pitch, selected, after_path, view, metrics = max(
        choices, key=lambda row: (row[0], -abs(row[1] - 1), -abs(row[2]), -abs(row[3])))
    return selected, view, {
        "baseline": baseline, "candidate": metrics, "tested_candidate_limit": 84,
        "eligible_candidates": len(choices), "distance_factor": factor, "yaw_deg": yaw, "pitch_deg": pitch,
        "baseline_path": before_path, "candidate_path": after_path,
    }


def plan_explosion(run):
    from sw_reducer_incremental import baseline_inputs
    capture = read(run / "explode-capture" / "verified" / "native.json")
    job, inputs = baseline_inputs()
    prior = [row for row in job["features"] if row["operation"] == "explode"]
    mates = [row["components"] for row in job["features"] if row["operation"] == "mate"]
    selected, view, comparison = select_candidate(capture["componentBoxesMm"], prior,
                                                   capture["baselineCamera"], mates)
    job["features"] = [row for row in job["features"] if row["operation"] != "explode"] + selected
    job["incremental"] = {"prior_explosion": prior, "camera": view}
    if selected != prior:
        job["incremental"]["replace_steps"] = True
    comparison["steps_changed"] = selected != prior
    atomic(run / "EXPLOSION_COMPARISON.json", comparison)
    keep = [name for name in inputs if name.startswith("references/")]
    make_plan(run, "explode", job, inputs,
              ("ReducerAssembly.SLDASM", "BeforeExploded.bmp", "AfterExploded.bmp"),
              keep, checkpoint="v0.5/pinion-phase")


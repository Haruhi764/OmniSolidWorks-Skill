"""Independent two-station inspection fixture, dimensioned in mm.

The fixture is an engineering review specimen. Its nominal dimensions are
inputs, and its rectangular and cylindrical solids have closed-form volumes.
"""
from math import pi


def job(name, kind, features, validation, formats, dependencies=()):
    return {"schema_version": 2, "job_id": name, "document_type": kind, "units": "mm",
            "features": features, "parameters": {}, "dependencies": list(dependencies),
            "validation": validation, "outputs": {"name": name, "formats": formats}}


def circle(diameter, center=(0, 0)):
    return {"kind": "circle", "center": list(center), "diameter": diameter}


def part(name, size, depth, holes=()):
    if isinstance(size, tuple):
        x, y = (value / 2 for value in size)
        area = size[0] * size[1]
        profile = {"kind": "rectangle", "lower": [-x, -y], "upper": [x, y]}
    else:
        x = y = size / 2
        area = pi * x * y
        profile = circle(size)
    cuts = [{"id": f"Bore{n}", "operation": "through_cut", "plane": "Stock",
             "profile": circle(diameter, center)} for n, (diameter, center) in enumerate(holes, 1)]
    ids = list(holes) or ([] if isinstance(size, tuple) else [(size, (0, 0))])
    section = area - sum(pi * diameter ** 2 / 4 for diameter, _ in holes)

    def geometry(thickness):
        return {"bounds_mm": [[-x, -y, 0], [x, y, thickness]],
                "volume_mm3": section * thickness,
                "cylinders": [{"diameter": d, "center": list(center), "z": [0, thickness]}
                              for d, center in ids]}

    validation = geometry(depth)
    validation["edit"] = {"feature_id": "Stock", "depth_mm": depth + 1,
                          "geometry": geometry(depth + 1)}
    result = job(name, "part", [{"id": "Stock", "operation": "boss_extrude", "plane": "base",
                                 "profile": profile, "depth": {"parameter": "stock_thickness"}}, *cuts],
                 validation, ["sldprt", "step"])
    result["parameters"] = {"stock_thickness": depth}
    return result


def parts():
    holes = [(12, (x, y)) for x in (-55, 55) for y in (-29, 29)]
    return [
        part("FixtureBase", (170, 115), 10, holes),
        part("GuideRail", (30, 92), 12, [(12, (0, -29)), (12, (0, 29))]),
        part("LocatingPin", 12, 32),
        part("RetainingCollar", 20, 5, [(12, (0, 0))]),
        part("SupportPad", (27, 18), 7),
        part("SideStop", (10, 15), 18),
        part("EndLocator", (22, 9), 20),
        part("RearFence", (60, 9), 25),
    ]


def assembly(dependencies):
    components = []
    mates = []
    steps = []

    def add(key, dependency, x, y, z, fixed=True):
        components.append({"id": key, "operation": "component", "dependency": dependency,
                           "location": [x, y, z], "fixed": fixed})

    def release(name, group, distance, direction="+z"):
        steps.append({"id": name, "operation": "explode", "components": group,
                      "axis_component": "Base", "direction": direction, "distance_mm": distance})

    add("Base", "FixtureBase", 0, 0, 0)
    for side, x in (("Left", -55), ("Right", 55)):
        add(side + "Rail", "GuideRail", x, 0, 10)
        collars, pins = [], []
        for end, y in (("Front", 29), ("Rear", -29)):
            pin, collar = side + end + "Pin", side + end + "Collar"
            add(pin, "LocatingPin", x, y, 0)
            add(collar, "RetainingCollar", x, y, 22, fixed=False)
            pins.append(pin)
            collars.append(collar)
            mates.extend([
                {"id": collar + "Seat", "operation": "mate", "kind": "distance",
                 "components": [pin, collar], "distance_mm": 22},
                {"id": collar + "Axis", "operation": "mate", "kind": "concentric",
                 "components": [pin, collar], "diameters": [12, 12]},
            ])
        release("Remove" + side + "Collars", collars, 83)
        release("Withdraw" + side + "Pins", pins, 57)
    release("LiftLeftRail", ["LeftRail"], 25)
    release("LiftRightRail", ["RightRail"], 25)

    for side, x in (("Left", -1), ("Right", 1)):
        add(side + "Pad", "SupportPad", 18 * x, 0, 10)
        add(side + "Stop", "SideStop", 32 * x, 20, 10)
        add(side + "Locator", "EndLocator", 18 * x, 34, 10)
    add("Fence", "RearFence", 0, -43, 10)
    release("LiftSideStops", ["LeftStop", "RightStop"], 22)
    release("LiftEndLocators", ["LeftLocator", "RightLocator"], 32)
    release("LiftRearFence", ["Fence"], 27)
    release("LiftWorkSupports", ["LeftPad", "RightPad"], 16)

    spec = job("GuideFixture", "assembly", components + mates + steps,
               {"mate_count": len(mates), "relative_positions": {c["id"]: c["location"] for c in components},
                "clearance_check": True}, ["sldasm"], dependencies)
    spec["limits"] = {"part_files": 8, "components": 18, "explode_steps": 10}
    return spec


def disassembly_precedence():
    for side in ("Left", "Right"):
        for end in ("Front", "Rear"):
            stem = side + end
            yield stem + "Collar", stem + "Pin"
            yield stem + "Pin", side + "Rail"

def drawing(dependencies):
    spec = job("GuideFixtureDrawing", "drawing",
               [{"id": "Sheet1", "operation": "drawing_sheet", "paper": "a3", "exploded": True,
                 "bom": True, "title": "Two-station guide fixture", "drawing_number": "GF-00",
                 "witness_dimensions": [{"view": "Front", "part": "FixtureBase", "model_axis": axis, "mm": mm}
                                        for axis, mm in ((0, 170), (1, 115))]}],
               {"component_count": 18, "dimensions_mm": [170, 115]},
               ["slddrw", "pdf", "dwg", "dxf"], dependencies)
    spec["limits"] = {"part_files": 8, "components": 18, "explode_steps": 10}
    return spec

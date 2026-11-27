"""Set up the V0.8 A1 comparison without touching the source assembly."""
from sw_incremental_plan import input_row, make_plan
from sw_reducer_incremental import SOURCE
from sw_supervisor_state import read


def plan_drawing(run, phase="drawing"):
    source = run / "explode" / "verified"
    step_source = "incremental/explode"
    if not source.is_dir():
        source, step_source = SOURCE, "v0.5/pinion-phase"
    native = read(source / "native.json")
    assy = source / "ReducerAssembly.SLDASM"
    if not native["reopenedExplosion"]["verified"] or native["solidInterferences"] != []:
        raise ValueError("A persisted and statically validated assembly is required")
    inputs = {"references/ReducerAssembly.SLDASM": input_row(assy)}
    names = {row["path"].split("\\")[-1] for row in native["reopenedAssembly"]["components"]}
    parts = sorted((source / "references").glob("*.SLDPRT"))
    if names != {part.name for part in parts}:
        raise ValueError("Native reference graph does not match the staged files")
    deps = [{"id": "ReducerAssembly", "path": assy.name, "sha256": inputs["references/ReducerAssembly.SLDASM"]["sha256"]}]
    for part in parts:
        bind = input_row(part)
        inputs["references/references/" + part.name] = bind
        deps.append({"id": part.stem, "path": part.name, "sha256": bind["sha256"]})
    prior = read(SOURCE.parent / "drawing-final" / "native.json")
    long, high = prior["reopenedDrawing"]["dimensionsMm"]
    data = read(run / "explode-capture" / "verified" / "native.json")
    lower = data["componentBoxesMm"]["Sump"]
    thick = lower[5] - lower[2]
    drawing = {
        "incremental_drawing": {"witnesses": [
            {"parts": ["LowerHousing", "UpperHousing"], "view": "Front", "model_axis": 0, "mm": long, "required": True},
            {"parts": ["LowerHousing", "UpperHousing"], "view": "Front", "model_axis": 1, "mm": high, "required": True},
            {"part": "LowerHousing", "view": "Left", "model_axis": 2, "mm": thick},
        ]},
        "schema_version": 2, "limits": {}, "document_type": "drawing", "outputs": {"name": "ReducerDrawing"},
        "features": [{"id": "MainSheet", "operation": "drawing_sheet", "paper": "a1",
                      "title": "二级斜齿轮减速器装配", "drawing_number": "RG-2018-A01",
                      "bom": True, "exploded": True, "detail": False, "section": False, "center_marks": False}],
        "dependencies": deps, "validation": {"component_count": len(native["reopenedAssembly"]["components"]),
                                             "dimensions_mm": [long, high]},
    }
    if native.get("serviceViewPersisted"):
        drawing["incremental_drawing"]["model_view"] = "Service Exploded"
    make_plan(run, phase, drawing, inputs, [f"ReducerDrawing.{ext}" for ext in ("SLDDRW", "PDF", "DWG", "DXF")],
              inputs.keys(), checkpoint=step_source)


"""Create drawing jobs from the accepted native case artifacts, without remodeling them."""

import argparse
import json
from pathlib import Path

from create_v03_assembly_fixtures import dependency


def fixture(name, files, dimensions, *, component_count=None, **options):
    validation = {"dimensions_mm": dimensions}
    if component_count is not None:
        validation["component_count"] = component_count
    return {"schema_version": 1, "job_id": name + "Final", "document_type": "drawing", "units": "mm",
            "features": [{"id": "Sheet1", "operation": "drawing_sheet", "paper": "auto", **options}],
            "parameters": {}, "dependencies": [dependency(path.stem, path) for path in files],
            "outputs": {"name": name, "formats": ["slddrw", "dwg", "dxf", "pdf"]}, "validation": validation}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("part", type=Path)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(exist_ok=True)
    part = [args.part]
    assembly = [args.assembly, *sorted((args.assembly.parent / "references").glob("*.SLDPRT"))]
    fixtures = {
        "H1-PartDrawing": fixture("BearingBlockDrawing", part, [8, 20, 30, 50, 80], title="轴承座"),
        "H2-AssemblyDrawing": fixture("ExplodedAssemblyDrawing", assembly, [], component_count=4, exploded=True, bom=True, title="轴与法兰装配"),
        "H3-DetailDrawing": fixture("BearingBlockDetail", part, [8, 20, 30, 50, 80], section=True, detail=True, center_marks=True, title="轴承座"),
    }
    for filename, data in fixtures.items():
        with (args.destination / f"{filename}.json").open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

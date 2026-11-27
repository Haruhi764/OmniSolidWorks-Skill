"""Materialize fixture dependencies from the fresh A and B regression artifacts."""
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "outputs" / "v0.3"


def dependency(name, source):
    source = source.resolve(strict=True)
    with source.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"id": name, "path": source.relative_to(ROOT).as_posix(), "sha256": sha}


def component(name, dependency_id, z=0):
    return {"id": name, "operation": "component", "dependency": dependency_id, "location": [0, 0, z]}


def mate(name, kind, refs, **dimensions):
    return {"id": name, "operation": "mate", "kind": kind, "components": refs, **dimensions}


def assembly(name, components, mates, dependencies, offsets):
    return {"schema_version": 1, "job_id": name, "document_type": "assembly", "units": "mm",
            "features": [*components, *mates], "parameters": {}, "dependencies": dependencies,
            "outputs": {"name": name, "formats": ["sldasm"]},
            "validation": {"relative_positions": {key: [0, 0, offset] for key, offset in offsets.items()},
                           "mate_count": len(mates)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("shaft", type=Path)
    parser.add_argument("flange", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(exist_ok=True)
    dependencies = [dependency("Shaft", args.shaft), dependency("Flange", args.flange)]
    components = [component("Base", "Flange"), component("Shaft", "Shaft")]
    mates = [mate("ShaftAxis", "concentric", ["Base", "Shaft"], diameters=[30, 20]),
             mate("ShaftSeat", "coincident", ["Base", "Shaft"])]
    test_e = assembly("TwoPartAssembly", components, mates, dependencies, {"Base": 0, "Shaft": 0})
    test_f = assembly("FourPartAssembly", [*components, component("GuideFront", "Flange", 50), component("GuideRear", "Flange", 90)],
                      [*mates, mate("FrontAxis", "concentric", ["Base", "GuideFront"], diameters=[30, 30]),
                       mate("FrontOffset", "distance", ["Base", "GuideFront"], distance_mm=50),
                       mate("RearAxis", "concentric", ["Base", "GuideRear"], diameters=[30, 30]),
                       mate("RearOffset", "distance", ["Base", "GuideRear"], distance_mm=90)], dependencies,
                      {"Base": 0, "Shaft": 0, "GuideFront": 50, "GuideRear": 90})
    for letter, data in (("E", test_e), ("F", test_f)):
        with (args.destination / f"{letter}-Assembly.json").open("x", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)


if __name__ == "__main__":
    main()

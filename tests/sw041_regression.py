"""Synthetic scale cases for the unchanged SolidWorks 2014 COM architecture."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from v03_jobs import run_tool, sha
from v03_schema import normalize

OUT = ROOT/"outputs/v0.4.1"
BASE = ROOT/"outputs/v0.4"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def dep(path):
    return {"id":path.stem,"path":path.relative_to(OUT).as_posix(),"sha256":sha(path)}


def stage():
    fixtures = OUT/"fixtures"
    fixtures.mkdir(parents=True,exist_ok=True)
    batch = read(BASE/"native-batch.json")
    art = batch["cases"]["B"]["assembly"]["artifacts"]
    for name in ("Housing","Shaft","Fastener"):
        entry = next(row for row in art if Path(row["path"]).name.casefold()==(name+".SLDPRT").casefold())
        source = BASE/entry["path"]
        if sha(source)!=entry["sha256"]:
            raise ValueError("V0.4 source hash differs")
        targets = [fixtures/(name+".SLDPRT")]
        if name=="Fastener":
            targets += [fixtures/f"Sample{i:02}.SLDPRT" for i in range(1,29)]
        for target in targets:
            if not target.exists():
                shutil.copyfile(source,target)
            if sha(target)!=entry["sha256"]:
                raise ValueError("Synthetic fixture hash differs")
    return fixtures


def job(name, kind, features, dependencies, formats, validation):
    return dict(schema_version=2,job_id=name,document_type=kind,units="mm",limits={},
                features=features,parameters={},dependencies=dependencies,
                outputs=dict(name=name,formats=formats),validation=validation)


def component(key, part, point, fixed=False):
    return dict(id=key,operation="component",dependency=part,location=point,fixed=fixed)


def assembly(total, distinct, fixtures):
    name = f"Scale{total}"
    parts = [component("Base","Housing",[0,0,0]),component("Drive","Shaft",[0,0,0])]
    for index in range(total-2):
        part = f"Sample{index%(distinct-2)+1:02}"
        point = [130+(index//5)*28, 35+(index%5)*28, 0]
        parts.append(component(f"Instance{index+1:02}",part,point,True))
    features = parts + [
        dict(id="AxisMate",operation="mate",kind="concentric",components=["Base","Drive"],diameters=[30,20]),
        dict(id="SeatMate",operation="mate",kind="coincident",components=["Base","Drive"]),
        dict(id="AxialExtraction",operation="explode",components=["Drive"],axis_component="Base",
             axis_diameter=30,distance_mm=150,direction="-z"),
    ]
    for index in range(0,total-2,2):
        keys = [row["id"] for row in parts[index+2:index+4]]
        features.append(dict(id=f"Group{index//2+1:02}",operation="explode",components=keys,axis_component="Base",
                             distance_mm=100,direction="+x"))
    refs = [dep(fixtures/(name+".SLDPRT")) for name in dict.fromkeys(row["dependency"] for row in parts)]
    expected = {p["id"]:p["location"] for p in parts}
    return job(name,"assembly",features,refs,["sldasm"],dict(mate_count=2,relative_positions=expected,clearance_check=True))


def drawing(total, geometry):
    source = [geometry,*sorted((geometry.parent/"references").glob("*.SLDPRT"))]
    return job(f"Scale{total}Drawing","drawing",[dict(id="Sheet1",operation="drawing_sheet",paper="auto",
                exploded=True,bom=True,title=f"Assembly scale {total}",drawing_number=f"SCALE-{total}")],
               [dep(path) for path in source],["slddrw","pdf","dwg","dxf"],
               dict(component_count=total,dimensions_mm=[]))


def proof(spec, existing):
    if not existing or existing.get("status")!="PASS":
        return None
    native = OUT/existing["evidence"]
    try:
        if (sha(native)==existing["native_sha256"] and
            read(native.parent/"normalized.json")==normalize(spec,OUT) and
            all(sha(OUT/row["path"])==row["sha256"] for row in existing["artifacts"])):
            return existing
    except OSError:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--through",type=int,choices=(10,22,30),default=30)
    args = parser.parse_args()
    fixtures = stage()
    cases = [(10,5),(22,12),(30,30)]
    for count,kinds in cases+[(50,30)]:
        spec = assembly(count,kinds,fixtures)
        assert len(normalize(spec,OUT)["validation"]["relative_positions"])==count
    too_many = assembly(51,30,fixtures)
    try:
        normalize(too_many,OUT)
    except ValueError:
        pass
    else:
        raise AssertionError("The 50-instance guard did not reject 51")
    print("Offline preflight accepted 10, 22, 30, 50 and rejected 51.",flush=True)
    if args.offline:
        return 0
    path = OUT/"scale-batch.json"
    ledger = read(path) if path.exists() else {}
    for total,kinds in cases:
        if total>args.through:
            break
        row = ledger.setdefault(str(total),{})
        spec = assembly(total,kinds,fixtures)
        a = proof(spec,row.get("assembly")) or run_tool(spec)
        row["assembly"] = a
        write(path,ledger)
        print(total,"assembly",a["status"],a.get("error",""),flush=True)
        if a["status"]!="PASS":
            return 1
        parent = (OUT/a["evidence"]).parent
        spec = drawing(total,parent/(spec["outputs"]["name"]+".SLDASM"))
        d = proof(spec,row.get("drawing")) or run_tool(spec)
        row["drawing"] = d
        write(path,ledger)
        print(total,"drawing",d["status"],d.get("error",""),flush=True)
        if d["status"]!="PASS":
            return 1
        native = read(OUT/d["evidence"])
        bom = native["reopenedDrawing"]["bom"]
        assert len(bom["rows"])==kinds and sum(r["quantity"] for r in bom["rows"])==total
        assert len(bom["balloons"])==kinds and set(b["item"] for b in bom["balloons"])==set(r["item"] for r in bom["rows"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())

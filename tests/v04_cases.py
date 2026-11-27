
"""Run synthetic A/B jobs through the same SolidWorks CLI and emit regression evidence."""
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from v03_jobs import run_tool, sha
from v03_schema import normalize

OUT = ROOT/"outputs"/"v0.4"
FIXTURES = OUT/"fixtures"


def job(name, kind, features, validation, dependencies, formats):
    return dict(schema_version=2, job_id=name,document_type=kind,units="mm",
                features=features, parameters={},dependencies=dependencies,
                outputs=dict(name=name,formats=formats),validation=validation)


def circle(diameter,center=None):
    return dict(kind="circle",center=center or [0,0],diameter=diameter)


def boss(name, shape, length, plane="base"):
    return dict(id=name,operation="boss_extrude",plane=plane,profile=shape,depth=length)


def cut(name, diameter, plane, center=None):
    return dict(id=name,operation="through_cut",plane=plane,profile=circle(diameter,center))


def cylinder(diameter, z, center=None):
    return dict(diameter=diameter,z=z,center=center or [0,0])


def ring(name, diameter, hole, depth):
    r = diameter/2
    validate = dict(volume_mm3=math.pi/4*(diameter**2-hole**2)*depth,
                    bounds_mm=[[-r,-r,0],[r,r,depth]], cylinders=[cylinder(hole,[0,depth])])
    return job(name,"part",[boss("Blank",circle(diameter),depth),cut("Bore",hole,"Blank")],validate,[],["sldprt","step"])


def fastener():
    validate = dict(volume_mm3=math.pi*(4**2*12+7**2*4),bounds_mm=[[-7,-7,0],[7,7,16]],
                    cylinders=[cylinder(8,[0,12]),cylinder(14,[12,16])])
    return job("Fastener","part",[boss("Shank",circle(8),12),boss("Head",circle(14),4,"Shank")],
               validate,[],["sldprt","step"])


def housing():
    shape = dict(kind="rectangle",lower=[-70,-55],upper=[70,55])
    holes = [(30,[0,0]),(10,[40,0]),(10,[-40,0]),(10,[0,40]),(10,[0,-40])]
    features = [boss("Blank",shape,20)]+[cut(f"Hole{i+1}",diam,"Blank",xy) for i,(diam,xy) in enumerate(holes)]
    validate = dict(volume_mm3=(140*110-math.pi/4*sum(diam**2 for diam,_ in holes))*20,
                    bounds_mm=[[-70,-55,0],[70,55,20]],
                    cylinders=[cylinder(diam,[0,20],xy) for diam,xy in holes])
    return job("Housing","part",features,validate,[],["sldprt","step"])


def dependency(name,path):
    return dict(id=name,path=path.relative_to(OUT).as_posix(),sha256=sha(path))


def component(key,part,z,x=0,y=0,fixed=False):
    return dict(id=key,operation="component",dependency=part,location=[x,y,z],fixed=fixed)


def position(key,base,diam,z):
    constraints = [dict(id=key+"Axis",operation="mate",kind="concentric",components=[base,key],diameters=diam)]
    seat = dict(id=key+"Seat",operation="mate",kind="distance" if z else "coincident",components=[base,key])
    if z:
        seat["distance_mm"]=z
    return constraints+[seat]


def explode(name, keys, anchor, distance, direction, diameter=None):
    op = dict(id=name,operation="explode",components=keys,axis_component=anchor,distance_mm=distance,direction=direction)
    if diameter:
        op["axis_diameter"]=diameter
    return op


def specs(parts):
    a = [component("Carrier","Carrier",0),component("Shaft","Shaft",0),
         component("Bearing","Bearing",30),component("Sleeve","Sleeve",50),
         component("Bolt","Fastener",0,x=40,fixed=True)]
    b = [component("Housing","Housing",0),component("Cap","EndCap",20),component("Shaft","Shaft",0),
         component("BoltL","Fastener",20,x=-40,fixed=True),component("BoltR","Fastener",20,x=40,fixed=True)]
    plans = [
        ("A",a,position("Shaft","Carrier",[30,20],0)+position("Bearing","Carrier",[30,30],30)+position("Sleeve","Carrier",[30,30],50),
         [explode("ReleaseBolt",["Bolt"],"Carrier",64,"+z",30),
          explode("ExtractShaft",["Shaft"],"Carrier",148,"-z",30),
          explode("MoveSleeve",["Sleeve"],"Carrier",75,"+z",30),
          explode("MoveBearing",["Bearing"],"Carrier",40,"+z",30)]),
        ("B",b,position("Cap","Housing",[30,30],20)+position("Shaft","Housing",[30,20],0),
         [explode("ReleaseBolts",["BoltL","BoltR"],"Housing",110,"+z",30),
          explode("ExtractShaft",["Shaft"],"Housing",152,"-z",30),
          explode("LiftCap",["Cap"],"Housing",25,"+z",30),
          explode("SlideCap",["Cap"],"Housing",120,"+x")]),
    ]
    for key,rows,mates,steps in plans:
        validation = dict(mate_count=len(mates),relative_positions={c["id"]:c["location"] for c in rows},
                          clearance_check=True)
        yield key,job(f"V04-{key}-Core","assembly",rows+mates+steps,validation,
                      [dependency(c,parts[c]) for c in dict.fromkeys(row["dependency"] for row in rows)],["sldasm"])


def record(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def accept(spec,result):
    if result["status"]!="PASS":
        raise ValueError(f"{spec['job_id']}: {result.get('error')} ({result['evidence']})")
    return (OUT/result["evidence"]).parent


def drawing(key, assembly):
    outline = {"A":"轴承与套筒装配", "B":"壳体与端盖装配"}[key]
    part_refs = sorted((assembly.parent/"references").glob("*.SLDPRT"))
    return job(f"V04-{key}-Drawing","drawing",
               [dict(id="Sheet1",operation="drawing_sheet",paper="a3",exploded=True,bom=True,title=outline,
                     drawing_number=f"SW04-{key}")],
               dict(component_count=5,dimensions_mm=[]),
               [dependency(p.stem,p) for p in [assembly,*part_refs]],["slddrw","pdf","dwg","dxf"])


def saved_checkpoint(evidence_path, assembly):
    source = evidence_path.resolve(strict=True)
    if not source.is_relative_to(OUT):
        raise ValueError("Checkpoint evidence must be under the V0.4 output directory.")
    parent = source.parent
    native = json.loads(source.read_text(encoding="utf-8-sig"))
    prior_job = json.loads((parent/"normalized.json").read_text(encoding="utf-8-sig"))
    if not native["assembly"]["verified"] or not native["preExplodeSave"]["ok"]:
        raise ValueError("The checkpoint lacks verified baseline assembly evidence.")
    if prior_job["features"] != assembly["features"] or prior_job["dependencies"] != assembly["dependencies"]:
        raise ValueError("The checkpoint and requested assembly contract differ.")
    model = Path(native["preExplodeSave"]["path"]).resolve(strict=True)
    if model.parent != parent or not model.name.endswith("_base.SLDASM"):
        raise ValueError("Unexpected checkpoint assembly path.")
    for row in assembly["dependencies"]:
        if sha(parent/"references"/(row["id"]+".SLDPRT")) != row["sha256"]:
            raise ValueError("A checkpoint dependency does not match its source.")
    return {"path": model.relative_to(OUT).as_posix(), "sha256":sha(model), "evidenceSha256":sha(source)}


def reusable(result, spec):
    if not result or result["status"]!="PASS":
        return False
    evidence = OUT/result["evidence"]
    try:
        return (sha(evidence)==result["native_sha256"] and
                json.loads((evidence.parent/"normalized.json").read_text(encoding="utf-8"))==normalize(spec,OUT) and
                all(sha(OUT/item["path"])==item["sha256"] for item in result["artifacts"]))
    except (OSError, ValueError):
        return False


def main():
    FIXTURES.mkdir(parents=True,exist_ok=True)
    ledger = OUT/"native-batch.json"
    catalog = json.loads((ROOT/"outputs/v0.3/fixtures/G-Explode.json").read_text(encoding="utf-8"))["dependencies"]
    sources = {}
    for row in catalog:
        src = ROOT/"outputs/v0.3"/row["path"]
        target = FIXTURES/(row["id"]+".SLDPRT")
        if sha(src)!=row["sha256"]:
            raise ValueError("The V0.3 baseline artifact differs from its accepted hash.")
        if not target.exists():
            with target.open("xb") as output, src.open("rb") as inp:
                shutil.copyfileobj(inp,output)
        if sha(target)!=row["sha256"]:
            raise ValueError("Staged baseline hash mismatch.")
        sources[row["id"]]=target
    sources["Carrier"]=sources["EndCap"]=sources["Flange"]
    prior = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else dict(parts={},cases={})
    report = dict(parts=dict(prior["parts"]),cases=dict(prior["cases"]))
    for part in [ring("Bearing",52,30,12),ring("Sleeve",44,30,20),fastener(),housing()]:
        name = part["outputs"]["name"]
        record(FIXTURES/(name+".json"),part)
        result = prior["parts"].get(name)
        if not result or result["status"]!="PASS" or not all(
                sha(OUT/item["path"])==item["sha256"] for item in result["artifacts"]):
            result = run_tool(part)
        report["parts"][name]=result
        record(ledger,report)
        sources[name]=accept(part,result)/(name+".SLDPRT")
    from argparse import ArgumentParser
    parser=ArgumentParser()
    parser.add_argument("--models-only",action="store_true")
    parser.add_argument("--redraw",action="store_true",help="Rebuild only drawing jobs from verified assemblies")
    parser.add_argument("--resume-a",type=Path)
    parser.add_argument("--case",choices=("A","B"))
    args=parser.parse_args()
    for key,assembly in specs(sources):
        if args.case and key!=args.case:
            continue
        row=report["cases"].setdefault(key,{})
        record(FIXTURES/(assembly["job_id"]+".json"),assembly)
        result = row.get("assembly")
        if not reusable(result,assembly):
            if args.redraw:
                raise ValueError(f"{key} lacks a matching verified assembly for a drawing-only run.")
            checkpoint = saved_checkpoint(args.resume_a,assembly) if key=="A" and args.resume_a else None
            result = run_tool(assembly,checkpoint=checkpoint)
            row.pop("drawing",None)
        row["assembly"]=result
        record(ledger,report)
        if result["status"]!="PASS" or args.models_only:
            continue
        asm = accept(assembly,result)/(assembly["outputs"]["name"]+".SLDASM")
        spec = drawing(key,asm)
        record(FIXTURES/(spec["job_id"]+".json"),spec)
        if args.redraw or not reusable(row.get("drawing"),spec):
            row["drawing"] = run_tool(spec,force=args.redraw)
        record(ledger,report)
    print(json.dumps({k:{n:v["status"] for n,v in row.items()} for k,row in report["cases"].items()}))
    return int(any(result["status"]!="PASS" for row in report["cases"].values() for result in row.values()))


if __name__=="__main__":
    raise SystemExit(main())

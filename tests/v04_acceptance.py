
"""Hard-gate and package verified SolidWorks 2014 V0.4 regression artifacts."""
import argparse
import json
from collections import Counter
from pathlib import Path
import shutil
import sys
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from v03_jobs import sha

OUT = ROOT/"outputs"/"v0.4"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def native(result):
    source = OUT / result["evidence"]
    require(result["status"]=="PASS" and sha(source)==result["native_sha256"],"Unverified native report")
    for artifact in result["artifacts"]:
        require(sha(OUT/artifact["path"])==artifact["sha256"],"Changed artifact: "+artifact["path"])
    report = read(source)
    require(report["documentCountBefore"]==report["documentCountAfter"]==0 and report["preferencesRestored"],
            "SolidWorks session was not restored")
    require(report["revision"]=="22.0.0" and report["nativeOpen"]["ok"],"SolidWorks 2014 reopen absent")
    return report,source.parent


def evaluate(key, row, visual):
    a,assembly = native(row["assembly"])
    d,drawing = native(row["drawing"])
    require(a.get("assembledBaselinePreserved"),"Collapsed baseline transforms differ after save/reopen")
    for field in ("assembly","reopenedAssembly"):
        require(a[field]["verified"] and len(a[field]["components"])==5 and
                len(a[field]["mates"])==({"A":6,"B":4}[key]),"Component or mate readback mismatch")
    for field in ("explosion","reopenedExplosion"):
        explosion = a[field]
        require(explosion["verified"] and explosion["expandedChecked"] and explosion["collapsedChecked"]
                and explosion["restoredTransforms"] and len(explosion["steps"])==4,"Missing native explode state")
        require(explosion["clearance"]["pairs"]==10 and not explosion["clearance"]["potentialOverlap"],
                "Potential final exploded overlap")
    if key=="B":
        exploded = a["reopenedExplosion"]
        require(any(len(s["components"])==2 for s in exploded["steps"]) and
                {s["direction"][-1] for s in exploded["steps"]}=={"x","z"},"Grouped multi-axis explosion is absent")
    for stage in ("drawing","reopenedDrawing"):
        view = d[stage]
        require(view["firstAngle"] and len(view["views"])==4 and sum(v["exploded"] for v in view["views"])==1,
                "Native drawing layout or explode state mismatch")
        bom = view["bom"]
        totals = sorted(t["quantity"] for t in bom["rows"])
        require(bom["componentCount"]==5 and totals==({"A":[1]*5,"B":[1,1,1,2]}[key]),"BOM totals mismatch")
        require({x["item"] for x in bom["rows"]}=={x["item"].strip() for x in bom["balloons"]} and
                all(x["leaders"]>0 for x in bom["balloons"]),"BOM balloon numbers do not reconcile")
    pdf = next(drawing.glob("*.PDF"))
    png = OUT/"review"/f"{key}.png"
    require(visual["reviewed"] and visual["pdfSha256"]==sha(pdf) and visual["pngSha256"]==sha(png),
            "Actual visual evidence is missing or stale")
    return assembly,drawing,png,dict(status="PASS",revision=a["revision"],components=5,
                           mates=len(a["reopenedAssembly"]["mates"]),nativeSteps=4,
                           groups=[s["components"] for s in a["reopenedExplosion"]["steps"]],
                           displacementMm=a["reopenedExplosion"]["deltaMm"],
                           bom=d["reopenedDrawing"]["bom"], geometryGates="PASS", visual=visual,
                           nativeSeconds={"assembly":a["nativeSeconds"],"drawing":d["nativeSeconds"]},
                           trackedComCalls={"assembly":a["trackedComInvocations"],"drawing":d["trackedComInvocations"]},
                           computerUse=0)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("visual",type=Path)
    parser.add_argument("--zip",type=Path)
    args=parser.parse_args()
    batch=read(OUT/"native-batch.json")
    visual=read(args.visual)
    delivery = OUT/"delivery"
    delivery.mkdir(exist_ok=True)
    reports={}
    for key in ("A","B"):
        assembly,drawing,png,reports[key]=evaluate(key,batch["cases"][key],visual[key])
        target=delivery/key
        for label,source in (("assembly",assembly),("drawing",drawing)):
            for path in sorted(source.rglob("*")):
                if not path.is_file() or path.name == "checkpoint.SLDASM" or path.name.endswith(("_base.SLDASM", "_layout.SLDDRW")):
                    continue
                if path.suffix.lower() not in {".sldasm",".sldprt",".slddrw",".pdf",".dwg",".dxf"}:
                    continue
                new=target/label/path.relative_to(source)
                new.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,new)
            evidence=target/"evidence"
            evidence.mkdir(exist_ok=True)
            report=read(source/"native.json")
            report=json.loads(json.dumps(report).replace(str(ROOT).replace("\\","\\\\")+"\\\\",""))
            (evidence/f"{label}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            shutil.copyfile(source/"normalized.json", evidence/f"{label}-input.json")
            if (source/"checkpoint.json").is_file():
                shutil.copyfile(source/"checkpoint.json",evidence/"assembly-checkpoint.json")
        shutil.copyfile(png,target/"preview.png")
        (target/"BOM.json").write_text(json.dumps(reports[key]["bom"],ensure_ascii=False,indent=2),encoding="utf-8")
    parts = delivery/"verified-parts"
    parts.mkdir(exist_ok=True)
    for name,result in batch["parts"].items():
        for artifact in result["artifacts"]:
            path = OUT/artifact["path"]
            require(sha(path)==artifact["sha256"],"Part artifact hash mismatch")
            shutil.copyfile(path,parts/path.name)
    (delivery/"acceptance.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:{m:v[m] for m in ("status","nativeSteps","nativeSeconds")} for k,v in reports.items()}))
    if not args.zip:
        return
    if args.zip.exists():
        raise FileExistsError(args.zip)
    sources = [ROOT/name for name in ("SKILL.md","README.md","CHANGELOG.md","GITHUB_RESEARCH.md","AGENTS.md")]
    sources += [path for name in ("scripts","schemas","tests","examples","docs")
                for path in (ROOT/name).rglob("*") if path.is_file() and path.suffix in {".md",".json",".py",".ps1",".cs"}]
    staged=args.zip.with_name(args.zip.name+"."+uuid4().hex+".tmp")
    manifest={}
    with ZipFile(staged,"x",ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sources + sorted(p for p in delivery.rglob("*") if p.is_file()):
            name = path.relative_to(ROOT).as_posix()
            archive.write(path,name)
            manifest[name]=sha(path)
        archive.writestr("MANIFEST_SHA256.json",json.dumps(manifest,indent=2,ensure_ascii=False))
    with ZipFile(staged) as archive:
        require(archive.testzip() is None,"ZIP data check failed")
    staged.rename(args.zip)
    print(args.zip,sha(args.zip))


if __name__=="__main__":
    main()

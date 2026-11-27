"""Bounded SolidWorks 2014 native involute gear job. Dimensions in mm."""
import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from uuid import uuid4

from v03_jobs import ROOT, configuration, create_json, environment, get_template, host_command, run_host, sha


def gear(name, teeth, module, pressure, helix, width, bore, key=0, phase=0, seed_only=False, key_depth=0):
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}",name) is None:
        raise ValueError("Invalid gear name")
    if type(teeth) is not int or not 18 <= teeth <= 60 or not all(map(math.isfinite,(module,pressure,helix,width,bore,key,phase,key_depth))):
        raise ValueError("Expected 18–60 teeth and finite metric inputs")
    if not 1.5 <= module <= 5 or not 17.5 <= pressure <= 25 or not -25 <= helix <= 25 or not 4 <= width <= 35:
        raise ValueError("Gear dimensions outside the bounded candidate domain")
    beta=math.radians(helix)
    pitch=module/math.cos(beta)*teeth/2
    alpha=math.atan(math.tan(math.radians(pressure))/math.cos(beta))
    root=pitch-1.25*module
    tip=pitch+module
    base=pitch*math.cos(alpha)
    if bore <= 0 or key < 0 or bore/2+max(module,key*0.35) >= root or (key and key>bore/2):
        raise ValueError("Bore or keyway leaves insufficient root material")
    if abs(width*math.tan(beta)) > 16*module:
        raise ValueError("Tooth twist is outside the bounded candidate domain")
    depth=key_depth or key*.22
    if depth<0 or (not key and depth) or bore/2+depth+0.5>=root:
        raise ValueError("Invalid keyway radial depth")
    offset=module*0.20
    involute=lambda a: math.tan(a)-a
    def phi(r):
        a=math.acos(min(1,base/r))
        return math.pi/(2*teeth)-0.064*module/pitch+involute(alpha)-involute(a)
    start=max(base,root+module*.12)
    anchor=root-offset
    radii=[anchor]+[start+(tip-start)*i/8 for i in range(9)]
    widths=[phi(start)]+[phi(r) for r in radii[1:]]
    if min(widths)<=0 or 2*max(widths)>=math.tau/teeth:
        raise ValueError("Non-positive tooth tip or adjacent tooth overlap")
    tooth=list(zip(radii,(-v for v in widths)))+list(reversed(list(zip(radii,widths))))
    twist=width*math.tan(beta)/pitch
    sections=[]
    for z in (0,width/2,width):
        a=phase+twist*z/width
        points=[[r*math.cos(a+p),r*math.sin(a+p)] for r,p in tooth]
        if min(math.dist(p,q) for p,q in zip(points,points[1:]+points[:1]))<.04:
            raise ValueError("Degenerate sketch segment")
        sections.append(dict(z=z,points=points))
    return dict(document_type="gear",name=name,teeth=teeth,normal_module_mm=module,pressure_deg=pressure,
                helix_deg=helix,width=width,bore=bore,key=key,phase=phase,root=root,tip=tip,
                transverse_pressure_deg=math.degrees(alpha),pitch=pitch,twist=twist,key_depth=depth,
                tip_half_angle=widths[-1],sections=sections,seed_only=seed_only)


def run(spec):
    revision,install,templates=configuration()
    host=environment()
    if host.get("status")!="PASS" or host.get("documents")!=0:
        raise RuntimeError(f"Expected a ready empty SolidWorks process: {host}")
    base=ROOT/"outputs"/"v0.5"/"gear"
    for p in (base,*base.parents):
        if p.is_symlink() or p.is_junction():
            raise ValueError("Redirected output path")
        if p==ROOT:
            break
    folder=base/f"run-{uuid4().hex[:12]}"
    folder.mkdir(parents=True,exist_ok=False)
    create_json(folder/"job.json",spec)
    command=host_command("Invoke-V05Gear.ps1",revision,install,get_template("part",templates),folder,host["pid"])
    tick=time.perf_counter()
    try:
        proc=run_host(command,timeout=180)
        if proc.stderr:
            (folder/"stderr.txt").write_bytes(proc.stderr)
    except TimeoutError as exc:
        create_json(folder/"timeout.json",{"status":"BLOCKED","error":str(exc),"pid":host["pid"]})
        print(folder)
        return 1
    evidence=folder/"native.json"
    if not evidence.is_file():
        raise RuntimeError(f"No native report: {folder}")
    record=json.loads(evidence.read_text(encoding="utf-8-sig"))
    part=folder/(spec["name"]+".SLDPRT")
    print(json.dumps(dict(path=str(folder),status=record["status"],stage=record["stage"],error=record.get("error"),
        elapsed_s=round(time.perf_counter()-tick,3),sha256=sha(part) if part.is_file() else None),ensure_ascii=True))
    return 0 if proc.returncode==0 and record["status"]=="PASS" else 1


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("teeth",type=int)
    parser.add_argument("helix",type=float)
    parser.add_argument("bore",type=float)
    parser.add_argument("--module",type=float,default=2.5)
    parser.add_argument("--pressure",type=float,default=20)
    parser.add_argument("--width",type=float,default=20)
    parser.add_argument("--key",type=float,default=0)
    parser.add_argument("--key-depth",type=float,default=0)
    parser.add_argument("--phase",type=float,default=0)
    parser.add_argument("--seed-only",action="store_true")
    args=parser.parse_args()
    return run(gear(**vars(args)))


if __name__=="__main__":
    sys.exit(main())


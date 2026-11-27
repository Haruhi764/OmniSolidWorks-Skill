from itertools import accumulate
from math import cos, pi, sin
import argparse
import sys

from sw_blind_gripper import init_run
from sw_blind_gripper_delivery import publish
from sw_incremental_plan import input_row
from sw_release_case import execute
from v09_guide_fixture import job, part
from sw_supervisor_state import ROOT, atomic, read, require_workspace, sha
from v03_schema import normalize

sys.path.insert(0, str(ROOT / "tests"))
import v04_cases


def bench(run):
    dimensions = read(ROOT / "examples" / "benchmarks.json")
    rows = dimensions["shaft"]["segments"]
    extents = list(accumulate((row["length"] for row in rows), initial=0))
    diameter = max(row["diameter"] for row in rows)
    cuts, cylinders = [], []
    for n, row in enumerate(rows):
        cuts.append(v04_cases.boss("Step" + str(n + 1), v04_cases.circle(row["diameter"]), row["length"],
                                  "base" if n == 0 else "Step" + str(n)))
        cylinders.append(v04_cases.cylinder(row["diameter"], extents[n:n + 2]))
    volume = sum(pi * row["diameter"]**2 / 4 * row["length"] for row in rows)
    shaft = job("Shaft", "part", cuts, {"volume_mm3":volume, "cylinders":cylinders,
                "bounds_mm":[[-diameter/2,-diameter/2,0],[diameter/2,diameter/2,extents[-1]]]}, ["sldprt","step"])
    flange = dimensions["flange"]
    radius = flange["pitch_circle_diameter"] / 2
    holes = [(flange["bore_diameter"],(0,0))]
    for n in range(flange["bolt_count"]):
        theta = 2*pi*n/flange["bolt_count"]
        holes.append((flange["bolt_diameter"],(round(radius*cos(theta),10),round(radius*sin(theta),10))))
    return {"Shaft": execute(run,"shaft",shaft), "Flange": execute(run,"flange",
            part("Flange",flange["outer_diameter"],flange["thickness"],holes))}


def historical_ab():
    run=init_run("run-regression-ab")
    paths=bench(run)
    for part_job in (v04_cases.ring("Bearing",52,30,12),v04_cases.ring("Sleeve",44,30,20),
                     v04_cases.fastener(),v04_cases.housing()):
        name=part_job["job_id"]
        paths[name]=execute(run,name.lower(),part_job)
    paths["Carrier"]=paths["EndCap"]=paths["Flange"]
    v04_cases.OUT=ROOT/"outputs"
    for label, request in v04_cases.specs(paths):
        assembly=execute(run, label.lower()+"-core-r1", request, options={"review_assembly":True})
        execute(run,label.lower()+"-drawing",v04_cases.drawing(label,assembly))


def reducer():
    from sw_reducer_incremental import baseline_inputs
    run=init_run("run-regression-reducer")
    request, inputs=baseline_inputs()
    request["review_assembly"]=True
    request["incremental"]={"capture_only":True}
    assets={name: ROOT/row["path"] for name,row in inputs.items()}
    output=publish(run,"explode-capture",request,assets,())
    native=read(output/"native.json")
    atomic(run/"REDUCER_REOPEN.json",{"status":"PASS","scope":"historical native reducer, fresh reopen and native step/transform readback",
        "components":len(native["capturedAssembly"]["components"]),"steps":len(native["baselineExplosion"]["steps"])})


def wrong_initial():
    run=init_run("run-regression-blind-negative")
    request=part("FaultGuidePin",8,25)
    request["validation"]["volume_mm3"]+=1
    from sw_incremental_plan import make_plan
    from sw_supervisor import supervise
    plan=make_plan(run,"wrong-original-volume",normalize(request,ROOT/"outputs"),{},["FaultGuidePin.SLDPRT","FaultGuidePin.STEP"])
    state=supervise(run,"wrong-original-volume",plan)
    native=read(run/state["partial"]/"native.json") if state.get("partial") else {}
    if state["status"]!="failed" or "solid volume" not in native.get("error","") or native.get("documentCountAfter")!=0:
        raise ValueError("Initial volume negative did not reject for the original volume")
    atomic(run/"WRONG_INITIAL_GEOMETRY.json",{"status":"PASS","reason":native["error"]})


if __name__=="__main__":
    require_workspace(allow_installed=True)
    parser=argparse.ArgumentParser()
    parser.add_argument("case",choices=("ab","reducer","geometry-negative"))
    call={"ab":historical_ab,"reducer":reducer,"geometry-negative":wrong_initial}
    call[parser.parse_args().case]()

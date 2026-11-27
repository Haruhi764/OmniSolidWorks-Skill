"""Deterministic validation for the documented job-schema subset."""
import hashlib
import re
from pathlib import Path, PureWindowsPath
from stat import FILE_ATTRIBUTE_REPARSE_POINT


IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
FORMATS = {"part": {"sldprt", "step"}, "assembly": {"sldasm"}, "drawing": {"slddrw", "pdf", "dwg", "dxf"}}


def object_fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError(f"Expected fields {', '.join(required)} with optional {', '.join(optional)}")
    return value


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or PureWindowsPath(value).is_reserved():
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def number(value, parameters=None, *, positive=False, limit=100_000):
    if isinstance(value, dict) and parameters is not None:
        name = identifier(object_fields(value, ("parameter",))["parameter"])
        if name not in parameters:
            raise ValueError(f"Missing engineering parameter: {name}")
        value = parameters[name]
    if type(value) not in (int, float) or not -limit <= value <= limit or positive and value <= 0:
        raise ValueError(f"Invalid numeric input: {value!r}")
    return value


def vector(value, size, parameters=None):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"Expected a vector with {size} coordinates")
    return [number(coordinate, parameters) for coordinate in value]


def bounds(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Expected two opposing bounds corners")
    lower, upper = (vector(row, 3) for row in value)
    if any(start >= end for start, end in zip(lower, upper, strict=True)):
        raise ValueError("Solid bounds must be ordered with positive spans")
    return [lower, upper]


def validation_geometry(value):
    data = object_fields(value, ("volume_mm3", "bounds_mm", "cylinders"), ("edit", "centroid_mm"))
    if not isinstance(data["cylinders"], list) or len(data["cylinders"]) > 128:
        raise ValueError("Expected an array of cylindrical geometry checks")
    cylinders = []
    for row in data["cylinders"]:
        object_fields(row, ("center", "diameter", "z"))
        z = vector(row["z"], 2)
        if z[0] >= z[1]:
            raise ValueError("Cylinder axial interval must increase")
        cylinders.append({"center": vector(row["center"], 2), "diameter": number(row["diameter"], positive=True), "z": z})
    geometry = {"volume_mm3": number(data["volume_mm3"], positive=True, limit=10**15),
                "bounds_mm": bounds(data["bounds_mm"]), "cylinders": cylinders}
    if "centroid_mm" in data:
        point = vector(data["centroid_mm"], 3)
        lower, upper = geometry["bounds_mm"]
        if not all(a <= x <= b for a, x, b in zip(lower, point, upper, strict=True)):
            raise ValueError("Centroid is outside the confirmed solid envelope")
        geometry["centroid_mm"] = point
    return geometry


def profile(value, parameters):
    if not isinstance(value, dict):
        raise ValueError("A feature needs a profile")
    kind = value.get("kind")
    if kind == "circle":
        object_fields(value, ("kind", "center", "diameter"))
        return {"kind": kind, "center": vector(value["center"], 2, parameters),
                "diameter": number(value["diameter"], parameters, positive=True)}
    if kind == "rectangle":
        object_fields(value, ("kind", "lower", "upper"))
        lower, upper = (vector(value[key], 2, parameters) for key in ("lower", "upper"))
        if any(start >= end for start, end in zip(lower, upper, strict=True)):
            raise ValueError("Rectangle corners must have a positive span")
        return {"kind": kind, "lower": lower, "upper": upper}
    if kind == "polygon":
        object_fields(value, ("kind", "points"))
        if not isinstance(value["points"], list) or not 3 <= len(value["points"]) <= 32:
            raise ValueError("A polygon requires three to 32 points")
        points = [vector(point, 2, parameters) for point in value["points"]]
        if len({tuple(point) for point in points}) != len(points):
            raise ValueError("Polygon points must be distinct")
        return {"kind": kind, "points": points}
    raise ValueError(f"Unsupported profile: {kind!r}")


def part_plan(job, parameters):
    if job["dependencies"] != []:
        raise ValueError("Standalone part jobs take no file dependencies")
    features = job["features"]
    if not isinstance(features, list) or not 1 <= len(features) <= 32:
        raise ValueError("A part requires one to 32 features")
    normalized = []
    prior = {}
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("Expected a feature object")
        name = identifier(feature.get("id"))
        op = feature.get("operation")
        if name in prior or op not in ("boss_extrude", "through_cut", "boss_revolve"):
            raise ValueError(f"Duplicate feature or unsupported operation: {name}, {op}")
        object_fields(feature, ("id", "operation", "plane", "profile"), ("depth", "axis"))
        plane = feature["plane"]
        if plane != "base" and (not isinstance(plane, str) or prior.get(plane) != "boss_extrude"):
            raise ValueError(f"Plane does not refer to a preceding extrusion: {plane!r}")
        row = {"id": name, "operation": op, "plane": plane, "profile": profile(feature["profile"], parameters)}
        if not normalized and (op == "through_cut" or plane != "base"):
            raise ValueError("A part must first create a solid on the base plane")
        if op == "boss_extrude":
            row["depth"] = number(feature.get("depth"), parameters, positive=True)
        elif op == "boss_revolve":
            if plane != "base" or row["profile"]["kind"] != "polygon" or feature.get("axis") != "x":
                raise ValueError("The revolution operation accepts a polygon on the base plane and the x axis")
        if any(key in feature and key not in row and not (key == "axis" and op == "boss_revolve") for key in ("axis", "depth")):
            raise ValueError(f"Unexpected operation field on {name}")
        prior[name] = op
        normalized.append(row)
    validation = validation_geometry(job["validation"])
    if edit := job["validation"].get("edit"):
        object_fields(edit, ("feature_id", "depth_mm", "geometry"))
        target = identifier(edit["feature_id"])
        if prior.get(target) != "boss_extrude":
            raise ValueError("The edit must target an existing boss extrusion")
        validation["edit"] = {"feature_id": target, "depth_mm": number(edit["depth_mm"], positive=True),
                              "geometry": validation_geometry(edit["geometry"])}
    return normalized, [], validation


def dependencies_for(job, root, count, extensions):
    rows = job["dependencies"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= count:
        raise ValueError("Unexpected number of document dependencies")
    dependencies = {}
    for row in rows:
        object_fields(row, ("id", "path", "sha256"))
        key = identifier(row["id"])
        path = output_path(root, row["path"])
        if key in dependencies or path.suffix.lower() not in extensions or not isinstance(row["sha256"], str):
            raise ValueError("Duplicate dependency ID or incompatible source artifact")
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != row["sha256"]:
            raise ValueError(f"Dependency hash changed: {key}")
        dependencies[key] = dict(row, path=path.relative_to(root).as_posix())
    return dependencies


def scale_limits(job):
    defaults = {"part_files": 5, "components": 5, "explode_steps": 12}
    if job["schema_version"] == 1 or "limits" not in job:
        return defaults
    config = object_fields(job["limits"], (), defaults)
    limits = dict(defaults, **{"part_files": 30, "components": 50, "explode_steps": 50})
    limits.update(config)
    for field, maximum in {"part_files": 30, "components": 50, "explode_steps": 50}.items():
        minimum = 2 if field == "components" else 1
        if type(limits[field]) is not int or not minimum <= limits[field] <= maximum:
            raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    return limits


def assembly_plan(job, root):
    extended = job["schema_version"] == 2
    limits = scale_limits(job)
    dependencies = dependencies_for(job, root, limits["part_files"], {".sldprt"})
    operation_cap = 24 if "limits" not in job else 7 * limits["components"] + limits["explode_steps"]
    if not isinstance(job["features"], list) or not 3 <= len(job["features"]) <= operation_cap:
        raise ValueError("Expected a bounded list of components and mates")
    features = []
    seen = set()
    components = {}
    mates = 0
    steps = 0
    for feature in job["features"]:
        if not isinstance(feature, dict):
            raise ValueError("Expected an assembly feature object")
        op = feature.get("operation")
        name = identifier(feature.get("id"))
        if name in seen:
            raise ValueError("Duplicate assembly ID")
        seen.add(name)
        if op == "component":
            object_fields(feature, ("id", "operation", "dependency", "location"), ("fixed",) if extended else ())
            if "fixed" in feature and type(feature["fixed"]) is not bool:
                raise ValueError("fixed must be boolean")
            dependency = identifier(feature["dependency"])
            if dependency not in dependencies or mates or steps:
                raise ValueError("Declare valid components before all mates")
            components[name] = dependency
            features.append(dict(feature, location=vector(feature["location"], 3)))
        elif op == "mate":
            if steps:
                raise ValueError("Mate definitions must precede explosion steps")
            object_fields(feature, ("id", "operation", "kind", "components"), ("diameters", "distance_mm"))
            refs = feature["components"]
            if not isinstance(refs, list) or len(refs) != 2 or any(identifier(item) not in components for item in refs) or refs[0] == refs[1]:
                raise ValueError("Mate components must refer to two distinct, preceding components")
            kind = feature["kind"]
            if kind == "concentric":
                values = vector(feature.get("diameters"), 2)
                if any(value <= 0 for value in values):
                    raise ValueError("Concentric mate needs two positive cylinder diameters")
                features.append(dict(feature, diameters=values))
            elif kind == "distance":
                features.append(dict(feature, distance_mm=number(feature.get("distance_mm"), positive=True)))
            elif kind == "coincident":
                features.append(dict(feature))
            else:
                raise ValueError("Unsupported mate type")
            mates += 1
        elif op == "explode":
            if extended:
                feature = explode_step(feature, components)
                if not mates or steps >= limits["explode_steps"]:
                    raise ValueError("Explosion requires real mates and must fit the configured step limit")
                features.append(feature)
                steps += 1
                continue
            object_fields(feature, ("id", "operation", "component", "axis_component", "axis_diameter", "distance_mm", "direction"))
            target, axis = (identifier(feature[key]) for key in ("component", "axis_component"))
            if mates == 0 or steps >= limits["explode_steps"] or target not in components or axis not in components or target == axis:
                raise ValueError("An explode step requires a mated assembly and two distinct component references")
            if feature["direction"] not in ("+z", "-z"):
                raise ValueError("The 2014 explode workflow accepts only signed axial movement")
            features.append(dict(feature, axis_diameter=number(feature["axis_diameter"], positive=True),
                                 distance_mm=number(feature["distance_mm"], positive=True)))
            steps += 1
        else:
            raise ValueError("Unsupported assembly operation")
    if not 2 <= len(components) <= limits["components"] or mates == 0 or set(components.values()) != dependencies.keys():
        raise ValueError("Assembly requires at least two components within the configured limit, all dependencies used, and real mates")
    validation = object_fields(job["validation"], ("relative_positions", "mate_count"),
                               ("clearance_check",) if extended else ())
    if type(validation.get("clearance_check", False)) is not bool:
        raise ValueError("clearance_check must be boolean")
    if extended:
        connected = {key for row in features if row["operation"] == "mate" for key in row["components"]}
        for row in [item for item in features if item["operation"] == "component"][1:]:
            if row["id"] not in connected and not row.get("fixed"):
                raise ValueError("Every floating component requires a declared mate")
    positions = validation["relative_positions"]
    if not isinstance(positions, dict) or positions.keys() != components.keys() or type(validation["mate_count"]) is not int or validation["mate_count"] != mates:
        raise ValueError("Assembly validation must specify all relative positions and the exact mate count")
    validation = dict(validation, relative_positions={key: vector(value, 3) for key, value in positions.items()})
    return features, list(dependencies.values()), validation


def explode_step(row, components):
    object_fields(row, ("id", "operation", "components", "axis_component", "distance_mm", "direction"),
                  ("axis_diameter",))
    keys, axis = row["components"], identifier(row["axis_component"])
    if (not isinstance(keys, list) or not keys or len(set(map(identifier, keys))) != len(keys)
            or any(k not in components or k == axis for k in keys) or axis not in components):
        raise ValueError("Invalid or duplicate moving component in explosion step")
    direction = row["direction"]
    if direction not in ("+x", "-x", "+y", "-y", "+z", "-z"):
        raise ValueError("Use an explicit signed principal direction")
    if direction[1] != "z" and "axis_diameter" in row:
        raise ValueError("The axial cylinder reference is only supported for Z")
    normalized = dict(row, distance_mm=number(row["distance_mm"], positive=True, limit=10000))
    if "axis_diameter" in row:
        normalized["axis_diameter"] = number(row["axis_diameter"], positive=True)
    return normalized


def drawing_plan(job, root):
    limits = scale_limits(job)
    dependencies = list(dependencies_for(job, root, limits["part_files"] + 1, {".sldprt", ".sldasm"}).values())
    if not isinstance(job["features"], list) or len(job["features"]) != 1:
        raise ValueError("A drawing job requires one sheet plan")
    sheet = object_fields(job["features"][0], ("id", "operation", "paper"),
                          ("exploded", "bom", "section", "detail", "center_marks", "title", "drawing_number", "witness_dimensions"))
    identifier(sheet["id"])
    if sheet["operation"] != "drawing_sheet" or sheet["paper"] not in (("auto", "a4", "a3", "a2", "a1", "a0") if job["schema_version"] == 2 else ("auto", "a4", "a3")):
        raise ValueError("Expected a supported drawing sheet size")
    for field in ("title", "drawing_number"):
        if field in sheet and (not isinstance(sheet[field], str) or not sheet[field].strip() or len(sheet[field]) > 48 or
                               any(char in sheet[field] for char in "\r\n\t$<>")):
            raise ValueError(f"Invalid confirmed drawing {field}")
    flags = {}
    for name in ("exploded", "bom", "section", "detail", "center_marks"):
        flags[name] = sheet.get(name, False)
        if type(flags[name]) is not bool:
            raise ValueError(f"{name} must be true or false")
    primary = Path(dependencies[0]["path"])
    is_assembly = primary.suffix.lower() == ".sldasm"
    if is_assembly:
        ref_dir = primary.parent / "references"
        if len(dependencies) < 2 or any(Path(row["path"]).parent != ref_dir or
            Path(row["path"]).suffix.lower() != ".sldprt" or Path(row["path"]).stem != row["id"] for row in dependencies[1:]):
            raise ValueError("Supply the checked assembly followed by its original staged component references")
        if any(flags[name] for name in ("section", "detail", "center_marks")):
            raise ValueError("Section, detail and center-mark plans are currently scoped to parts")
    elif len(dependencies) != 1 or flags["exploded"] or flags["bom"]:
        raise ValueError("A part drawing takes one model. Exploded views and BOM require an assembly")
    validation = object_fields(job["validation"], ("dimensions_mm",), ("component_count",))
    expected = validation["dimensions_mm"]
    if not isinstance(expected, list) or len(expected) > 24 or (not is_assembly and not expected):
        raise ValueError("A part drawing requires confirmed key dimension values")
    validation = dict(validation, dimensions_mm=[number(x, positive=True) for x in expected])
    if is_assembly:
        count = validation.get("component_count")
        if type(count) is not int or not 2 <= count <= limits["components"]:
            raise ValueError("An assembly drawing requires the confirmed total component count")
    elif "component_count" in validation:
        raise ValueError("component_count is only used for assemblies")
    witnesses = sheet.get("witness_dimensions", [])
    if "witness_dimensions" in sheet:
        if job["schema_version"] != 2 or not isinstance(witnesses, list) or not 1 <= len(witnesses) <= 12:
            raise ValueError("Witness dimensions require a schema 2 drawing and 1 to 12 entries")
        part_ids = {item["id"] for item in (dependencies[1:] if is_assembly else dependencies)}
        values = []
        for entry in witnesses:
            row = object_fields(entry, ("view", "part", "model_axis", "mm"))
            if (row["view"] not in ("Front", "Top", "Left") or identifier(row["part"]) not in part_ids
                    or type(row["model_axis"]) is not int or row["model_axis"] not in (0, 1, 2)):
                raise ValueError("Witness dimensions require a declared part, an orthographic view and model axis 0, 1 or 2")
            mm = number(row["mm"], positive=True)
            if mm not in validation["dimensions_mm"]:
                raise ValueError("Every witness dimension must also be a confirmed validation dimension")
            values.append(dict(row, mm=mm, required=True))
        if len({(r["view"], r["part"], r["model_axis"], r["mm"]) for r in values}) != len(values):
            raise ValueError("Duplicate witness dimension")
        flags["witness_dimensions"] = values
    return [dict(sheet, **flags)], dependencies, validation


def normalize(job, output_root):
    object_fields(job, ("schema_version", "job_id", "document_type", "units", "features", "parameters", "dependencies", "outputs", "validation"), ("limits",))
    if type(job["schema_version"]) is not int or job["schema_version"] not in (1, 2) or job["units"] != "mm":
        raise ValueError("Expected schema version 1 or 2 and dimensions in mm")
    kind = job["document_type"]
    if kind not in FORMATS:
        raise ValueError(f"Document type not available: {kind!r}")
    if not isinstance(job["parameters"], dict) or len(job["parameters"]) > 64:
        raise ValueError("Expected a bounded numeric parameter object")
    parameters = {identifier(key): number(val) for key, val in job["parameters"].items()}
    output = object_fields(job["outputs"], ("name", "formats"))
    formats = output["formats"]
    if not isinstance(formats, list) or any(type(item) is not str for item in formats) or set(formats) != FORMATS[kind] or len(formats) != len(set(formats)):
        raise ValueError(f"Expected formats: {sorted(FORMATS[kind])}")
    if kind == "part":
        features, dependencies, validation = part_plan(job, parameters)
    elif kind == "assembly":
        if parameters:
            raise ValueError("Use the assembly feature fields for positioning and mating dimensions")
        features, dependencies, validation = assembly_plan(job, output_root)
    else:
        if parameters:
            raise ValueError("Drawing dimensions are read from the referenced model")
        features, dependencies, validation = drawing_plan(job, output_root)
    if "limits" in job and (job["schema_version"] != 2 or kind == "part"):
        raise ValueError("Scale limits apply to schema 2 assembly and drawing jobs")
    result = {"schema_version": job["schema_version"], "job_id": identifier(job["job_id"]), "document_type": kind, "units": "mm",
            "features": features, "parameters": parameters, "dependencies": dependencies,
            "outputs": {"name": identifier(output["name"]), "formats": sorted(formats)}, "validation": validation}
    if "limits" in job:
        result["limits"] = scale_limits(job)
    return result


def output_path(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Expected a project-relative artifact path")
    candidate = PureWindowsPath(relative)
    if candidate.anchor or any(part == ".." or ":" in part or part.endswith((".", " "))
                               or PureWindowsPath(part).is_reserved() for part in candidate.parts):
        raise ValueError("Artifact paths must stay inside the V0.3 output directory")
    path = root
    for part in candidate.parts:
        path /= part
        if getattr(path.lstat(), "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Artifact path contains a reparse point")
    path = path.resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Artifact path escapes the V0.3 output directory or is not a file")
    return path

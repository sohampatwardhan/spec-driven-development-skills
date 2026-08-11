#!/usr/bin/env python3
"""Validate spec navigation, file links, traceability, and execution readiness."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fnmatch
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit


NAV_MODULE_PATH = Path(__file__).with_name("spec-nav.py")
NAV_MODULE_SPEC = importlib.util.spec_from_file_location("spec_nav", NAV_MODULE_PATH)
if NAV_MODULE_SPEC is None or NAV_MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load navigation helper: {NAV_MODULE_PATH}")
NAV_MODULE = importlib.util.module_from_spec(NAV_MODULE_SPEC)
NAV_MODULE_SPEC.loader.exec_module(NAV_MODULE)
navigation_errors = NAV_MODULE.navigation_errors

# `build_tasks_sidecar` resolves each task's capability tier/model in-process (never shelling out
# per task) by reusing the same deterministic router `spec-execute` invokes at delegation time.
MODEL_ROUTER_PATH = Path(__file__).with_name("model-router.py")
MODEL_ROUTER_SPEC = importlib.util.spec_from_file_location("model_router", MODEL_ROUTER_PATH)
if MODEL_ROUTER_SPEC is None or MODEL_ROUTER_SPEC.loader is None:
    raise RuntimeError(f"cannot load model-router helper: {MODEL_ROUTER_PATH}")
MODEL_ROUTER = importlib.util.module_from_spec(MODEL_ROUTER_SPEC)
MODEL_ROUTER_SPEC.loader.exec_module(MODEL_ROUTER)


TASK_HEADER = re.compile(
    r"(?m)^(?P<indent>[ \t]*)-\s+\[(?P<status>[ xX])\](?P<optional>\*)?\s+"
    r"(?P<id>\d+(?:\.\d+)*)\b(?P<title>[^\n]*)$"
)
DEPENDS_FIELD = re.compile(r"(?mi)^\s*-\s+\*\*Depends on:\*\*\s*(.*?)\s*$")
STAGE_FIELD = re.compile(r"(?mi)^\s*-\s+\*\*Stage:\*\*\s*(.*?)\s*$")
FILES_FIELD = re.compile(r"(?mi)^\s*-\s+\*\*Files:\*\*\s*(.*?)\s*$")
DELEGATION_FIELD = re.compile(r"(?mi)^\s*-\s+\*\*Delegation:\*\*\s*(.*?)\s*$")
TASK_CATEGORY_FIELD = re.compile(r"(?mi)^\s*-\s+\*\*Task category:\*\*\s*(.*?)\s*$")
EFFORT_FIELD = re.compile(r"(?mi)^\s*-\s+\*\*Estimated effort:\*\*\s*(.*?)\s*$")
# Prose-capable fields (unlike Files/Depends on/Stage/.../Estimated effort, which are always one
# short structured value by convention) commonly soft-wrap across physical lines when the value
# is long — exactly like an EARS criterion does. Extracted separately via _field_values, which
# extends to the next metadata bullet/_Requirements:_ line/blank line rather than end-of-line.
PROSE_FIELD_BOUNDARY = re.compile(r"\n\s*-\s+(?:\*\*\w|_Requirements:)|\n[ \t]*\n")


def _field_values(label: str, body: str) -> list[str]:
    """Extract a metadata field's value, tolerating a soft-wrapped continuation line."""
    marker = re.compile(r"(?mi)^\s*-\s+\*\*" + re.escape(label) + r":\*\*\s*")
    values: list[str] = []
    for match in marker.finditer(body):
        boundary = PROSE_FIELD_BOUNDARY.search(body, match.end())
        end = boundary.start() if boundary else len(body)
        values.append(re.sub(r"\s+", " ", body[match.end():end]).strip())
    return values
REQUIREMENTS_FIELD = re.compile(r"(?mi)^\s*-\s+_Requirements:\s*([^_]+)_\s*$")
DEPENDENCY_RESOLUTION_FIELD = re.compile(
    r"(?mi)^\s*-\s+\*\*Dependency resolution:\*\*\s*(.*?)\s*$"
)
DEPENDENCY_DELIVERY_FIELD = re.compile(
    r"(?mi)^\s*-\s+\*\*Dependency delivery:\*\*\s*(.*?)\s*$"
)
DELEGATION_VALUES = {"controller", "sequential subagent", "parallel-safe"}
DEPENDENCY_RESOLUTION_VALUES = {"none", "change"}
DEPENDENCY_DELIVERY_VALUES = {"none", "main", "release"}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)")
INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
FENCED_CODE = re.compile(r"(?ms)^(```|~~~).*?^\1[ \t]*$")
PATH_EXEMPT_MARKERS = ("*", "?", "[", "]", "{", "}", "<", ">", "$", "|")
DEPENDENCY_SECURITY_HEADING = re.compile(
    r"(?mi)^##\s+Dependency Security Evidence\b"
)
CURRENT_TECHNOLOGY_HEADING = re.compile(
    r"(?mi)^##\s+Current Technology Evidence\b"
)
RESOLUTION_FILENAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
    "bun.lock", "bun.lockb", "pyproject.toml", "poetry.lock", "pdm.lock", "uv.lock",
    "pipfile", "pipfile.lock",
    "requirements.txt", "requirements.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
    "composer.json", "composer.lock", "gemfile", "gemfile.lock", "pom.xml",
    "build.gradle", "build.gradle.kts", "gradle.lockfile",
}
DEPENDENCY_CHANGE_NARRATIVE = re.compile(
    r"(?is)(?:\b(?:upgrade|bump|pin)\w*\b.{0,60}"
    r"\b(?:dependenc\w*|package|library|version|manifest|lockfile|lock file)\b|"
    r"\b(?:add|remove|replace|change|update|edit|regenerate)\b.{0,50}"
    r"\b(?:manifest|lockfile|lock file|resolved\s+dependency\s+snapshot|"
    r"dependency\s+version|dependenc(?:y|ies)(?!\s+security\s+evidence))\b|"
    r"\b(?:manifest|lockfile|lock file)\b.{0,60}"
    r"\b(?:update|edit|regenerate|write|modify)\w*\b)"
)
NEGATED_STEP = re.compile(
    r"(?i)\b(?:no|not|never|missing|stale|outdated|without|do\s+not|don't)\b"
)
LOCAL_ACTION_GOVERNOR = re.compile(
    r"(?i)(?:\b(?:not|never|without)\b(?:\s+\w+){0,1}|"
    r"\bno\b(?:\s+\w+){0,1}|\bdo\s+not|"
    r"\b(?:decline|declined|refuse|refused|fail|failed)\b"
    r"(?:\s+(?!(?:and|or|but|then)\b)[\w-]+)*\s+to|"
    r"\b(?:(?:am|is|are|was|were|be|been|being)\s+)?unable\b"
    r"(?:\s+(?!(?:and|or|but|then)\b)[\w-]+)*\s+to|"
    r"\b(?:attempt|attempted|try|tried)\b"
    r"(?:\s+(?!to\b)[\w-]+)*\s+to|"
    r"\bunsuccessfully\b(?:\s+(?!to\b)[\w-]+)*\s+(?:to\s+)?|"
    r"\bunsuccessful\b(?:\s+(?!to\b)[\w-]+)*\s+attempt\b"
    r"(?:\s+(?!to\b)[\w-]+)*\s+to|"
    r"\b(?:avoid|avoided|omit|omitted|skip|skipped)\b(?:\s+to)?)\s*$"
)


def cited(text: str, marker: str) -> set[str]:
    found: set[str] = set()
    for match in re.finditer(marker, text, flags=re.IGNORECASE):
        found.update(re.findall(r"\b(\d+\.\d+)\b", match.group(1)))
    return found


def requirements_contract_errors(text: str) -> list[str]:
    """Validate canonical criterion IDs and the five EARS sentence forms.

    A criterion's EARS sentence commonly soft-wraps across several physical Markdown lines —
    exactly like the `**User Story:**` sentence spec-requirements.md's own JSON-extraction
    pseudocode already has to account for. The body is the paragraph following `**R<n>.<m>**`,
    up to the next criterion marker, a blank line, or a heading — not just the same physical
    line — so a naturally-wrapped criterion isn't misreported as invalid EARS.
    """

    visible = FENCED_CODE.sub("", text)
    criterion_header = re.compile(r"(?m)^\s*(?:\d+\.\s+)?\*\*R(?P<id>\d+\.\d+)\*\*\s*")
    ears_pattern = re.compile(
        r"(?:"
        r"THE\s+.+?\s+SHALL\s+.+|"
        r"WHEN\s+.+?,\s+THE\s+.+?\s+SHALL\s+.+|"
        r"WHILE\s+.+?,\s+(?:WHEN\s+.+?,\s+)?THE\s+.+?\s+SHALL\s+.+|"
        r"IF\s+.+?,\s+THEN\s+THE\s+.+?\s+SHALL\s+.+|"
        r"WHERE\s+.+?,\s+THE\s+.+?\s+SHALL\s+.+"
        r")\.?"
    )
    errors: list[str] = []
    matches = list(criterion_header.finditer(visible))
    if not matches:
        return ["no canonical EARS criteria found; use **R1.1** followed by an EARS sentence"]
    seen: set[str] = set()
    expected_by_requirement: dict[str, int] = {}
    for index, match in enumerate(matches):
        criterion_id = match.group("id")
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(visible)
        raw_body = visible[match.end():body_end]
        boundary = re.search(r"\n[ \t]*\n|\n[ \t]*#{1,6}\s", raw_body)
        if boundary:
            raw_body = raw_body[: boundary.start()]
        body = re.sub(r"\s+", " ", raw_body).strip()
        requirement, item = criterion_id.split(".", 1)
        if criterion_id in seen:
            errors.append(f"duplicate requirement criterion R{criterion_id}")
        seen.add(criterion_id)
        expected = expected_by_requirement.get(requirement, 1)
        if int(item) != expected:
            errors.append(
                f"requirement {requirement} criteria must be contiguous; expected R{requirement}.{expected}"
            )
        expected_by_requirement[requirement] = int(item) + 1
        if not body or ears_pattern.fullmatch(body) is None:
            errors.append(f"R{criterion_id} is not valid EARS")
    return errors


def project_root_for(spec_dir: Path) -> Path:
    """Resolve the project root for `.specs/<feature-slug>/`."""
    if spec_dir.parent.name == ".specs":
        return spec_dir.parent.parent
    return spec_dir.parent


def local_link_target(artifact: Path, raw_target: str) -> Path | None:
    """Resolve a local Markdown target, excluding URLs and document anchors."""
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    split = urlsplit(target)
    if split.scheme or split.netloc or not split.path:
        return None
    return (artifact.parent / unquote(split.path)).resolve()


def existing_reference(candidate: str, artifact: Path, project_root: Path) -> Path | None:
    """Resolve an inline-code value when it is an existing project path."""
    value = candidate.strip()
    if (
        not value
        or any(character.isspace() for character in value)
        or any(marker in value for marker in PATH_EXEMPT_MARKERS)
        or "://" in value
        or value.startswith(("-", "#"))
    ):
        return None
    value = re.sub(r":\d+(?:-\d+)?$", "", value)
    raw = Path(value)
    candidates = [raw.resolve()] if raw.is_absolute() else [
        (artifact.parent / raw).resolve(),
        (project_root / raw).resolve(),
    ]
    project = project_root.resolve()
    for resolved in candidates:
        try:
            resolved.relative_to(project)
        except ValueError:
            continue
        if resolved.exists():
            return resolved
    return None


def artifact_link_errors(spec_dir: Path) -> list[str]:
    """Report broken local links and unlinked references to existing project paths."""
    root = spec_dir.resolve()
    project_root = project_root_for(root)
    errors: list[str] = []
    for artifact in sorted(root.glob("0[0-5]_*.md")):
        text = artifact.read_text(encoding="utf-8")
        visible_text = FENCED_CODE.sub("", text)
        for match in MARKDOWN_LINK.finditer(visible_text):
            target = local_link_target(artifact, match.group(1))
            if target is not None and not target.exists():
                errors.append(f"{artifact.name} contains a broken local link: {match.group(1)}")
        for match in INLINE_CODE.finditer(visible_text):
            if (
                match.start() > 0
                and visible_text[match.start() - 1] == "["
                and match.end() < len(visible_text)
                and visible_text[match.end()] == "]"
            ):
                continue
            resolved = existing_reference(match.group(1), artifact, project_root)
            if resolved is None:
                continue
            label = resolved.relative_to(project_root.resolve()).as_posix()
            errors.append(
                f"{artifact.name} references existing project path `{label}` without a Markdown link"
            )
    return errors


def parse_dependencies(value: str, task_id: str, errors: list[str]) -> list[str]:
    if value.strip().lower() == "none":
        return []
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not re.fullmatch(r"\d+(?:\.\d+)+", part) for part in parts):
        errors.append(
            f"task {task_id} has invalid Depends on value; use 'none' or comma-separated task IDs"
        )
        return []
    if len(parts) != len(set(parts)):
        errors.append(f"task {task_id} lists a dependency more than once")
    return list(dict.fromkeys(parts))


def parse_owned_files(value: str) -> list[str]:
    """Normalize inline-code and linked task ownership paths to their visible labels."""
    files: list[str] = []
    for item in value.split(","):
        candidate = item.strip()
        linked = re.fullmatch(r"\[(`?)([^\]`]+)\1\]\([^)]+\)", candidate)
        if linked:
            candidate = linked.group(2).strip()
        else:
            candidate = candidate.strip("`")
        if candidate:
            files.append(candidate)
    return files


def owned_paths_overlap(first: str, second: str) -> bool:
    left = first.strip().removeprefix("./").rstrip("/")
    right = second.strip().removeprefix("./").rstrip("/")
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def task_dependency_graph(text: str) -> tuple[list[dict[str, object]], list[str]]:
    """Parse the task DAG and canonical dependency-security scheduling metadata.

    Every executable leaf declares both fields so dependency-free work is represented explicitly
    and remains schedulable in the earliest stage. Migration diagnostics are ordinary errors and
    therefore cannot produce a ready execution result.
    """
    errors: list[str] = []
    headers = list(TASK_HEADER.finditer(text))
    tasks: list[dict[str, object]] = []
    seen: set[str] = set()

    for index, header in enumerate(headers):
        task_id = header.group("id")
        if "." not in task_id:
            continue
        if task_id in seen:
            errors.append(f"duplicate task ID {task_id}")
            continue
        seen.add(task_id)
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = text[header.end() : end]
        depends_matches = DEPENDS_FIELD.findall(body)
        stage_matches = STAGE_FIELD.findall(body)
        files_matches = FILES_FIELD.findall(body)
        delegation_matches = DELEGATION_FIELD.findall(body)
        documentation_matches = _field_values("Documentation", body)
        verification_matches = _field_values("Verification", body)
        risk_matches = _field_values("Risk", body)
        task_category_matches = TASK_CATEGORY_FIELD.findall(body)
        interfaces_matches = _field_values("Interfaces", body)
        effort_matches = EFFORT_FIELD.findall(body)
        requirements_matches = REQUIREMENTS_FIELD.findall(body)
        resolution_matches = DEPENDENCY_RESOLUTION_FIELD.findall(body)
        delivery_matches = DEPENDENCY_DELIVERY_FIELD.findall(body)
        stage: int | None = None
        if len(stage_matches) != 1:
            errors.append(f"task {task_id} must declare exactly one Stage field")
        elif not re.fullmatch(r"[1-9]\d*", stage_matches[0].strip()):
            errors.append(f"task {task_id} Stage must be a positive integer")
        else:
            stage = int(stage_matches[0].strip())
        if not depends_matches:
            dependencies: list[str] = []
            if stage != 1:
                errors.append(
                    f"task {task_id} may omit Depends on only when it declares Stage 1"
                )
        elif len(depends_matches) > 1:
            errors.append(f"task {task_id} must not declare more than one Depends on field")
            dependencies = []
        else:
            dependencies = parse_dependencies(depends_matches[0], task_id, errors)
        files: list[str] = []
        if len(files_matches) != 1:
            errors.append(f"task {task_id} must declare exactly one Files field")
        else:
            files = parse_owned_files(files_matches[0])
            if not files:
                errors.append(f"task {task_id} Files must name at least one path")
        delegation: str | None = None
        if len(delegation_matches) != 1:
            errors.append(f"task {task_id} must declare exactly one Delegation field")
        else:
            delegation = delegation_matches[0].strip().lower()
            if delegation not in DELEGATION_VALUES:
                errors.append(
                    f"task {task_id} Delegation must be controller, sequential subagent, "
                    "or parallel-safe"
                )
        # Task category is parsed here but validated only where it is consumed
        # (`build_tasks_sidecar`, and in turn `--emit-json`/`--ready`'s freshness gate): a task
        # list from before this field existed still parses as a valid graph, but cannot emit a
        # fresh `04_tasks.json` sidecar until every leaf declares a recognized category.
        task_category: str | None = None
        if len(task_category_matches) > 1:
            errors.append(f"task {task_id} must not declare more than one Task category field")
        elif len(task_category_matches) == 1:
            task_category = (
                task_category_matches[0].strip().casefold().replace(" ", "_").replace("-", "_")
            )
        contract_fields: dict[str, str | None] = {}
        for label, matches in (
            ("Documentation", documentation_matches),
            ("Verification", verification_matches),
            ("Risk", risk_matches),
        ):
            if len(matches) != 1:
                errors.append(f"task {task_id} must declare exactly one {label} field")
                contract_fields[label.casefold()] = None
            elif not matches[0].strip() or matches[0].strip().casefold() in {"tbd", "todo", "n/a"}:
                errors.append(f"task {task_id} {label} must contain an executable contract")
                contract_fields[label.casefold()] = None
            else:
                contract_fields[label.casefold()] = matches[0].strip()
        interfaces: str | None = None
        if len(interfaces_matches) != 1:
            errors.append(f"task {task_id} must declare exactly one Interfaces field")
        else:
            interfaces = interfaces_matches[0].strip()
            interface_contract = re.fullmatch(
                r"(?is)Consumes:\s*(?!tbd\b|todo\b|n/a\b)\S.+?;\s*"
                r"Produces:\s*(?!tbd\b|todo\b|n/a\b)\S.+",
                interfaces,
            )
            if interface_contract is None:
                errors.append(
                    f"task {task_id} Interfaces must declare non-placeholder Consumes and Produces clauses"
                )
        effort: str | None = None
        if len(effort_matches) != 1:
            errors.append(f"task {task_id} must declare exactly one Estimated effort field")
        else:
            effort = effort_matches[0].strip()
            if re.fullmatch(
                r"(?i)\s*\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*"
                r"(?:seconds?|minutes?|hours?|days?)\s*",
                effort,
            ) is None:
                errors.append(
                    f"task {task_id} Estimated effort must contain a bounded duration or range"
                )
        requirements: list[str] = []
        if len(requirements_matches) != 1:
            errors.append(f"task {task_id} must declare exactly one Requirements field")
        else:
            requirements = re.findall(r"\b(\d+\.\d+)\b", requirements_matches[0])
            if not requirements:
                errors.append(f"task {task_id} Requirements must cite at least one criterion ID")
        dependency_resolution: str | None = None
        if len(resolution_matches) == 1:
            dependency_resolution = resolution_matches[0].strip().casefold()
            if dependency_resolution not in DEPENDENCY_RESOLUTION_VALUES:
                errors.append(
                    f"task {task_id} Dependency resolution must be none or change"
                )
        else:
            errors.append(
                f"task {task_id} must declare exactly one Dependency resolution field"
            )

        dependency_delivery: str | None = None
        if len(delivery_matches) == 1:
            dependency_delivery = delivery_matches[0].strip().casefold()
            if dependency_delivery not in DEPENDENCY_DELIVERY_VALUES:
                errors.append(
                    f"task {task_id} Dependency delivery must be none, main, or release"
                )
        else:
            errors.append(
                f"task {task_id} must declare exactly one Dependency delivery field"
            )
        tasks.append(
            {
                "id": task_id,
                "title": header.group("title").strip().lstrip(". "),
                "depends_on": dependencies,
                "stage": stage,
                "files": files,
                "delegation": delegation,
                "dependency_resolution": dependency_resolution,
                "dependency_delivery": dependency_delivery,
                "documentation": contract_fields["documentation"],
                "verification": contract_fields["verification"],
                "risk": contract_fields["risk"],
                "task_category": task_category,
                "interfaces": interfaces,
                "estimated_effort": effort,
                "requirements": requirements,
                "checked": header.group("status").lower() == "x",
                "optional": bool(header.group("optional")),
                "position": len(tasks) + 1,
            }
        )

    if not tasks:
        errors.append("no leaf tasks found; use dotted IDs such as 1.1")
        return tasks, errors

    by_id = {str(task["id"]): task for task in tasks}
    positions = {str(task["id"]): int(task["position"]) for task in tasks}
    for task in tasks:
        task_id = str(task["id"])
        for dependency in task["depends_on"]:
            if dependency == task_id:
                errors.append(f"task {task_id} cannot depend on itself")
            elif dependency not in by_id:
                errors.append(f"task {task_id} depends on unknown task {dependency}")
            elif not task["optional"] and by_id[dependency]["optional"]:
                errors.append(
                    f"required task {task_id} cannot depend on optional task {dependency}"
                )
            elif positions[dependency] >= positions[task_id]:
                errors.append(f"task {task_id} depends on later task {dependency}")

    visiting: set[str] = set()
    computed: dict[str, int] = {}
    reported_cycles: set[tuple[str, ...]] = set()

    def compute_stage(task_id: str, trail: tuple[str, ...] = ()) -> int | None:
        if task_id in computed:
            return computed[task_id]
        if task_id in visiting:
            cycle_start = trail.index(task_id) if task_id in trail else 0
            cycle = trail[cycle_start:] + (task_id,)
            cycle_nodes = cycle[:-1]
            canonical = min(
                cycle_nodes[offset:] + cycle_nodes[:offset]
                for offset in range(len(cycle_nodes))
            )
            if canonical not in reported_cycles:
                errors.append(f"task dependency cycle: {' -> '.join(cycle)}")
                reported_cycles.add(canonical)
            return None
        visiting.add(task_id)
        task = by_id[task_id]
        dependency_stages: list[int] = []
        for dependency in task["depends_on"]:
            if dependency not in by_id or dependency == task_id:
                continue
            dependency_stage = compute_stage(dependency, trail + (task_id,))
            if dependency_stage is not None:
                dependency_stages.append(dependency_stage)
        visiting.remove(task_id)
        if len(dependency_stages) != len(task["depends_on"]):
            return None
        result = 1 if not dependency_stages else max(dependency_stages) + 1
        computed[task_id] = result
        return result

    previous_stage = 0
    for task in tasks:
        task_id = str(task["id"])
        expected = compute_stage(task_id)
        declared = task["stage"]
        task["computed_stage"] = expected
        if declared is not None and expected is not None and declared != expected:
            errors.append(
                f"task {task_id} declares stage {declared}; dependency graph requires {expected}"
            )
        if declared is not None:
            if declared < previous_stage:
                errors.append(
                    f"task {task_id} stage {declared} appears after stage {previous_stage}"
                )
            previous_stage = max(previous_stage, declared)

    parallel_by_stage: dict[int, list[dict[str, object]]] = {}
    for task in tasks:
        if task["delegation"] == "parallel-safe" and task["stage"] is not None:
            parallel_by_stage.setdefault(int(task["stage"]), []).append(task)
            for owned_path in task["files"]:
                if any(marker in owned_path for marker in ("*", "?", "[")):
                    errors.append(
                        f"parallel-safe task {task['id']} Files must use exact paths, not globs"
                    )
    for stage, candidates in parallel_by_stage.items():
        for index, first in enumerate(candidates):
            for second in candidates[index + 1 :]:
                overlaps = [
                    (left, right)
                    for left in first["files"]
                    for right in second["files"]
                    if owned_paths_overlap(left, right)
                ]
                if overlaps:
                    pairs = ", ".join(f"{left} ↔ {right}" for left, right in overlaps)
                    errors.append(
                        f"parallel-safe tasks {first['id']} and {second['id']} overlap in stage "
                        f"{stage}: {pairs}"
                    )

    return tasks, errors


def task_structure_errors(text: str) -> list[str]:
    """Validate parent roll-up and canonical checkpoint declarations."""

    errors: list[str] = []
    headers = list(TASK_HEADER.finditer(FENCED_CODE.sub("", text)))
    parents = [header for header in headers if "." not in header.group("id")]
    for parent in parents:
        parent_id = parent.group("id")
        required_children = [
            child
            for child in headers
            if child.group("id").startswith(f"{parent_id}.") and not child.group("optional")
        ]
        if not required_children:
            continue
        parent_checked = parent.group("status").casefold() == "x"
        all_children_checked = all(
            child.group("status").casefold() == "x" for child in required_children
        )
        if parent_checked and not all_children_checked:
            errors.append(f"parent task {parent_id} is checked while a required child is open")
        elif not parent_checked and all_children_checked:
            errors.append(f"parent task {parent_id} is open although all required children are checked")

    for line in FENCED_CODE.sub("", text).splitlines():
        if not re.match(r"^\s*(?:#{2,6}\s+|-\s+\[[ xX]\]\s+).*[Cc]heckpoint\b", line):
            continue
        heading = re.fullmatch(
            r"\s*##\s+\d+(?:\.\d+)*\.\s+\S.*\bCheckpoint\s*", line
        )
        checkbox = re.fullmatch(
            r"\s*-\s+\[[ xX]\]\s+\d+(?:\.\d+)*\.\s+Checkpoint\s+[—-]\s+\S.*",
            line,
        )
        if heading is None and checkbox is None:
            errors.append(f"malformed checkpoint declaration: {line.strip()}")
    return errors


def _table_rows(text: str, heading: str, header: list[str]) -> tuple[list[list[str]], str | None]:
    match = re.search(rf"(?m)^###\s+{re.escape(heading)}\s*$", text)
    if match is None:
        return [], f"05_execution.md must contain ### {heading}"
    end_match = re.search(r"(?m)^###\s+", text[match.end():])
    end = match.end() + end_match.start() if end_match else len(text)
    lines = [line.strip() for line in text[match.end():end].splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return [], f"### {heading} must contain its canonical Markdown table"
    parsed = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    if parsed[0] != header:
        return [], f"### {heading} has a non-canonical header"
    return parsed[2:], None


def execution_timing_errors(text: str, *, require_timing: bool) -> list[str]:
    """Validate durable run/task timing records and their derived Mermaid Gantt."""

    if not require_timing:
        return []
    errors: list[str] = []
    run_rows, run_error = _table_rows(
        text,
        "Run Intervals",
        ["Run ID", "Started UTC", "Stopped UTC", "Elapsed Seconds", "Outcome"],
    )
    attempt_rows, attempt_error = _table_rows(
        text,
        "Task Attempt Intervals",
        [
            "Run ID", "Stage/Wave", "Task", "Attempt", "Started UTC",
            "Stopped UTC", "Elapsed Seconds", "Outcome",
        ],
    )
    errors.extend(error for error in (run_error, attempt_error) if error)
    if run_error or attempt_error:
        return errors
    if not run_rows:
        errors.append("Run Intervals must contain an active or closed run")

    closed = False
    for kind, rows, expected_cells in (("run", run_rows, 5), ("task attempt", attempt_rows, 8)):
        for row in rows:
            if len(row) != expected_cells:
                errors.append(f"{kind} timing row has {len(row)} cells; expected {expected_cells}")
                continue
            run_id = row[0]
            start_value = row[1] if kind == "run" else row[4]
            stop_value = row[2] if kind == "run" else row[5]
            elapsed_value = row[3] if kind == "run" else row[6]
            outcome = row[4] if kind == "run" else row[7]
            if re.fullmatch(r"run-\d{8}T\d{6}Z(?:-\d{2})?", run_id) is None:
                errors.append(f"invalid execution run ID: {run_id}")
            start = _timezone_timestamp(start_value)
            if start is None or not start_value.endswith("Z"):
                errors.append(f"{kind} {run_id} has invalid Started UTC")
                continue
            if outcome == "active":
                if stop_value != "pending" or elapsed_value != "pending":
                    errors.append(f"active {kind} {run_id} must have pending stop and elapsed values")
                continue
            if outcome == "interrupted" and stop_value == "unknown" and elapsed_value == "unknown":
                continue
            stop = _timezone_timestamp(stop_value)
            if stop is None or not stop_value.endswith("Z") or not elapsed_value.isdigit():
                errors.append(f"closed {kind} {run_id} must have UTC stop and whole-second elapsed values")
                continue
            elapsed = int((stop - start).total_seconds())
            if elapsed < 0 or int(elapsed_value) != elapsed:
                errors.append(f"{kind} {run_id} elapsed seconds do not match its timestamps")
            closed = True

    if closed:
        gantt = re.search(
            r"(?ms)^###\s+Execution Gantt\s*$.*?```mermaid\s*\n\s*gantt\b.*?"
            r"\n\s*dateFormat\s+YYYY-MM-DDTHH:mm:ss\b.*?```",
            text,
        )
        if gantt is None:
            errors.append("closed timing rows require a canonical ### Execution Gantt Mermaid block")
    return errors


def _section_content(text: str, heading: re.Match[str] | None) -> str:
    """Return visible content under a second-level heading."""

    if heading is None:
        return ""
    start = text.find("\n", heading.end())
    start = len(text) if start < 0 else start + 1
    following = re.search(r"(?mi)^##\s+", text[start:])
    end = start + following.start() if following else len(text)
    return text[start:end].strip()


def _reasoned_na(content: str) -> bool:
    """Recognize a concise explanation that no material evidence applies.

    Split on sentence punctuation or a blank line (paragraph break) only — a single soft-wrap
    newline inside one authored sentence is not a clause boundary, and each clause's internal
    whitespace (including any such soft wrap) is collapsed before pattern-matching so a `.{0,N}`
    gap can span what was originally a line break.
    """

    clauses = re.split(r"(?:[.;](?=\s)|\n[ \t]*\n)", content)
    return any(
        re.search(
            r"(?is)\bno\b.{0,40}\b(?:dependenc\w*|librar\w*|"
            r"evolving\s+technology\s+behavior)\b.{0,60}"
            r"\b(?:appl|select|use|require|rely)\w*\b",
            re.sub(r"\s+", " ", clause),
        )
        or re.search(r"(?is)\bnot applicable\b.{3,}\b(?:because|since)\b", re.sub(r"\s+", " ", clause))
        for clause in clauses
    )


def _meaningful_evidence(content: str) -> bool:
    """Reject empty, placeholder-only, and unexplained N/A evidence sections."""

    plain = re.sub(r"[\s|`*_<>.-]+", " ", content).strip()
    if not plain or plain.casefold() in {"none", "n/a", "na", "not applicable", "tbd"}:
        return False
    return _reasoned_na(content) or len(plain.split()) >= 4


def _markdown_report_links(text: str, filename: str) -> list[re.Match[str]]:
    """Find actual Markdown links whose path ends with the named report."""

    found: list[re.Match[str]] = []
    for match in MARKDOWN_LINK.finditer(text):
        path = urlsplit(match.group(1).strip("<>")).path.casefold()
        if path == filename or path.endswith(f"/{filename}"):
            found.append(match)
    return found


def _material_security_evidence_missing(content: str) -> list[str]:
    """Return missing human-review fields for material dependency evidence."""

    missing: list[str] = []
    version = _affirmative_prefix_search(
        r"(?:@|resolved(?:\s+version)?\s*[:=]?\s*`?)v?\d+(?:[._+-][0-9A-Za-z]+)+",
        content,
    )
    if version is None:
        missing.append("exact resolved version")
    if _affirmative_prefix_search(r"\b(?:change|main|release)\b", content) is None:
        missing.append("audit mode")
    for filename in ("latest.json", "latest.md"):
        if not _markdown_report_links(content, filename):
            missing.append(f"Markdown-linked {filename}")
    if _affirmative_prefix_search(r"\b(?:pass|warnings|blocked|unavailable|invalid)\b", content) is None:
        missing.append("effective status")
    if _affirmative_search(r"\bdecision\b", content) is None:
        missing.append("decision")
    if re.search(r"(?i)\bwarnings\b", content):
        warning_reviews = list(re.finditer(
            r"(?is)\bexplicitly\s+reviewed\s+warnings\b", content
        ))
        if not any(not _negated_before_match(content, match) for match in warning_reviews):
            missing.append("explicitly reviewed warnings")
        if not re.search(r"(?is)\bwarnings\b.{0,30}\b(?:not|never)\s+clean\b", content):
            missing.append("warnings not clean")
    if re.search(r"(?i)\b(?:blocked|unavailable|invalid)\b", content) and not re.search(
        r"(?is)\b(?:blocked|unavailable|invalid)\b.{0,100}\b(?:cannot|must not|do not)\b"
        r".{0,40}\b(?:ship|satisf\w*|proceed)\b",
        content,
    ):
        missing.append("blocked/unavailable/invalid cannot ship")
    return missing


def _material_technology_evidence_missing(content: str) -> list[str]:
    """Return missing provenance and decision fields for current-technology evidence."""

    missing: list[str] = []
    consulted = _affirmative_evidence_search(
        r"(?:\b(?:consulted|checked|queried|reviewed|used)\b.{0,60}\bcontext7\b|"
        r"\bcontext7\b.{0,60}\b(?:consulted|checked|queried|reviewed|used)\b)",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source = re.search(r"(?i)/[a-z0-9_.-]+/[a-z0-9_.-]+", content)
    if consulted is None or source is None:
        missing.append("Context7 identity/source")
    if _affirmative_prefix_search(r"\bv?\d+(?:[._+-][0-9A-Za-z]+)+\b", content) is None:
        missing.append("exact selected version")
    if _affirmative_search(r"\bdecision\b", content) is None:
        missing.append("decision")
    return missing


EXCLUDED_RESOLUTION_SEGMENTS = {"doc", "docs", "example", "examples", "fixture", "fixtures"}
RESOLUTION_GROUPS = (
    {
        "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
        "bun.lock", "bun.lockb",
    },
    {"pyproject.toml", "poetry.lock", "pdm.lock", "uv.lock"},
    {"pipfile", "pipfile.lock"},
    {"requirements.txt", "requirements.lock"},
    {"cargo.toml", "cargo.lock"},
    {"go.mod", "go.sum"},
    {"composer.json", "composer.lock"},
    {"gemfile", "gemfile.lock"},
    {"pom.xml"},
    {"build.gradle", "build.gradle.kts", "gradle.lockfile"},
)
WORKSPACE_LOCK_REGISTRY = {
    "package.json": {
        "locks": {
            "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
            "bun.lock", "bun.lockb",
        },
    },
    "cargo.toml": {"locks": {"Cargo.lock"}},
}


def _is_resolution_path(path: str) -> bool:
    """Recognize a project resolution path while excluding documentary/sample artifacts."""

    lowered = tuple(part.casefold() for part in Path(path.replace("\\", "/").strip()).parts)
    if not lowered or any(part in EXCLUDED_RESOLUTION_SEGMENTS for part in lowered[:-1]):
        return False
    name = lowered[-1]
    return name in RESOLUTION_FILENAMES or (
        name.startswith("requirements") and name.endswith((".txt", ".in", ".lock"))
    )


def _owned_resolution_paths(files: list[str], project_root: Path) -> set[Path]:
    """Resolve declared resolution ownership to exact project-root-relative paths."""

    root = project_root.resolve()
    owned: set[Path] = set()
    for value in files:
        raw = Path(value)
        resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        if _is_resolution_path(relative.as_posix()):
            owned.add(relative)
    return owned


def _valid_workspace_pattern(value: str) -> tuple[bool, str] | None:
    """Parse a safe relative workspace glob and its optional exclusion marker."""

    candidate = value.strip()
    excluded = candidate.startswith("!")
    pattern = candidate[1:] if excluded else candidate
    path = Path(pattern)
    if not pattern or path.is_absolute() or ".." in path.parts:
        return None
    return excluded, pattern.rstrip("/")


def _ordered_workspace_match(member: str, patterns: list[str]) -> bool:
    """Apply ordered positive and negative workspace globs to one member path."""

    included = False
    for value in patterns:
        parsed = _valid_workspace_pattern(value)
        if parsed is None:
            continue
        excluded, pattern = parsed
        if fnmatch.fnmatchcase(member, pattern):
            included = not excluded
    return included


def _workspace_membership(manifest: Path, member: str) -> bool:
    """Return whether a supported ancestor manifest declares this workspace member."""

    if manifest.name.casefold() == "package.json":
        try:
            workspaces = json.loads(manifest.read_text(encoding="utf-8")).get("workspaces", [])
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            return False
        if isinstance(workspaces, dict):
            workspaces = workspaces.get("packages", [])
        patterns = (
            [value for value in workspaces if isinstance(value, str)]
            if isinstance(workspaces, list) else []
        )
        return _ordered_workspace_match(member, patterns)
    if manifest.name.casefold() == "cargo.toml":
        try:
            workspace = tomllib.loads(manifest.read_text(encoding="utf-8")).get("workspace", {})
        except (OSError, UnicodeError, tomllib.TOMLDecodeError, AttributeError):
            return False
        members = workspace.get("members", []) if isinstance(workspace, dict) else []
        excludes = workspace.get("exclude", []) if isinstance(workspace, dict) else []
        member_patterns = [value for value in members if isinstance(value, str)] if isinstance(members, list) else []
        exclude_patterns = [value for value in excludes if isinstance(value, str)] if isinstance(excludes, list) else []
        return (
            _ordered_workspace_match(member, member_patterns)
            and not any(
                fnmatch.fnmatchcase(member, parsed[1])
                for value in exclude_patterns
                if (parsed := _valid_workspace_pattern(value)) is not None
            )
        )
    return False


def _pnpm_workspace_patterns(directory: Path) -> list[str] | None:
    """Read the documented package-list subset from pnpm-workspace.yaml without a YAML runtime."""

    workspace = directory / "pnpm-workspace.yaml"
    if not workspace.is_file():
        return None
    try:
        text = workspace.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if not re.search(r"(?m)^\s*packages\s*:", text):
        return None
    return [
        match.group(1).strip().strip("'\"")
        for match in re.finditer(r"(?m)^\s*-\s*([^#\n]+?)\s*$", text)
    ]


def _workspace_ancestor_locks(relative: Path, project_root: Path) -> set[Path]:
    """Find nearest declared workspace ancestor locks for a nested owned manifest."""

    name = relative.name.casefold()
    registry = WORKSPACE_LOCK_REGISTRY.get(name)
    if registry is None or relative.parent == Path("."):
        return set()
    root = project_root.resolve()
    for ancestor in relative.parent.parents:
        ancestor_directory = root / ancestor
        member = relative.parent.relative_to(ancestor).as_posix()
        manifest = ancestor_directory / relative.name
        declared = _workspace_membership(manifest, member) if manifest.is_file() else False
        if name == "package.json":
            pnpm_patterns = _pnpm_workspace_patterns(ancestor_directory)
            if pnpm_patterns is not None:
                declared = _ordered_workspace_match(member, pnpm_patterns)
        if not declared:
            continue
        locks = {
            ancestor / lock_name
            for lock_name in registry["locks"]
            if (ancestor_directory / lock_name).is_file()
        }
        if locks:
            return locks
    return set()


def _resolution_ownership_errors(
    task_id: str, files: list[str], project_root: Path | None
) -> list[str]:
    """Require exact ownership of every applicable manifest/resolution artifact."""

    if project_root is None:
        return [] if any(_is_resolution_path(path) for path in files) else [
            f"dependency-changing task {task_id} must own an exact project manifest/lock path"
        ]
    owned = _owned_resolution_paths(files, project_root)
    if not owned:
        return [f"dependency-changing task {task_id} must own an exact project manifest/lock path"]
    missing: set[Path] = set()
    root = project_root.resolve()
    workspace_locks = set().union(*(
        _workspace_ancestor_locks(relative, root) for relative in owned
    )) if owned else set()
    missing.update(workspace_locks - owned)
    owned_identities = {path.as_posix().casefold() for path in owned}
    for relative in owned:
        if relative in workspace_locks and relative.name.casefold() != "package.json":
            continue
        name = relative.name.casefold()
        group = next((items for items in RESOLUTION_GROUPS if name in items), {name})
        for sibling_name in group:
            directory = root / relative.parent
            try:
                match = next(
                    child for child in directory.iterdir()
                    if child.is_file() and child.name.casefold() == sibling_name.casefold()
                )
            except (OSError, StopIteration):
                continue
            sibling = relative.parent / match.name
            if sibling.as_posix().casefold() not in owned_identities:
                missing.add(sibling)
        if name.startswith("requirements") and name.endswith((".txt", ".in", ".lock")):
            shared_stem = name.rsplit(".", 1)[0]
            for extension in ("txt", "in", "lock"):
                sibling = relative.parent / f"{shared_stem}.{extension}"
                if (root / sibling).is_file() and sibling not in owned:
                    missing.add(sibling)
    if not missing:
        return []
    joined = ", ".join(sorted(path.as_posix() for path in missing))
    return [f"dependency-changing task {task_id} must also own applicable resolution files: {joined}"]


def _step_is_negated(text: str, match: re.Match[str]) -> bool:
    """Return whether a required step is negated or described as missing/stale in its clause."""

    clause_start, clause_end = _clause_bounds(text, match.start(), match.end())
    return NEGATED_STEP.search(text[clause_start:clause_end]) is not None


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Return sentence/clause bounds without treating dots inside report links as punctuation.

    A blank line (paragraph break) is a boundary; a single soft-wrap newline inside one authored
    sentence is not — otherwise a sentence that wraps across physical Markdown lines gets cut in
    half, hiding a negation/qualifier that appears earlier in the same logical sentence.
    """

    boundaries = list(re.finditer(r"(?:[.;](?=\s)|\n[ \t]*\n)", text))
    clause_start = max(
        (boundary.end() for boundary in boundaries if boundary.end() <= start),
        default=0,
    )
    clause_end = min(
        (boundary.start() for boundary in boundaries if boundary.start() >= end),
        default=len(text),
    )
    return clause_start, clause_end


def _negated_before_match(text: str, match: re.Match[str]) -> bool:
    """Check the evidence prefix so required safety suffixes such as 'not clean' remain valid."""

    clause_start, _ = _clause_bounds(text, match.start(), match.end())
    return NEGATED_STEP.search(text[clause_start:match.start()]) is not None


def _affirmative_search(pattern: str, text: str, *, flags: int = re.IGNORECASE) -> re.Match[str] | None:
    """Find the first required clause that is present and not negated."""

    for match in re.finditer(pattern, text, flags=flags):
        if not _step_is_negated(text, match):
            return match
    return None


def _affirmative_prefix_search(
    pattern: str, text: str, *, flags: int = re.IGNORECASE
) -> re.Match[str] | None:
    """Find a required value not negated before the value within its clause."""

    for match in re.finditer(pattern, text, flags=flags):
        if not _negated_before_match(text, match):
            return match
    return None


def _affirmative_evidence_search(
    pattern: str, text: str, *, flags: int = re.IGNORECASE
) -> re.Match[str] | None:
    """Find affirmative design evidence without applying executable-contract grammar."""

    for match in re.finditer(pattern, text, flags=flags):
        clause_start, _ = _clause_bounds(text, match.start(), match.end())
        prefix = text[clause_start:match.start()]
        if LOCAL_ACTION_GOVERNOR.search(prefix) is None and not NEGATED_STEP.search(match.group(0)):
            return match
    return None


STRUCTURED_EVIDENCE = re.compile(
    r"(?mi)^\s*-\s+\*\*(?P<label>[^*]+):\*\*\s*(?P<value>[^\n]+)\s*$"
)
EVIDENCE_LINK = re.compile(r"^\[[^\]\n]+\]\(([^)\n]+)\)$")
DELIVERY_FRESHNESS_HOURS = 24
CHANGE_MAX_SEQUENCE_DAYS = 7
AUDIT_RESULT_REQUIRED = {
    "schema_version", "mode", "timestamp", "project_revision", "inventory", "sources",
    "findings", "decisions", "gate_status", "exit_code",
}
INVENTORY_REQUIRED = {
    "packages", "dependencies", "fingerprint", "complete", "statuses", "incomplete_reasons",
}


def _expected_path(
    value: str, *, project_root: Path | None = None, suffix: str | None = None
) -> Path | None:
    """Validate a plain project-relative path used only as a pending expectation."""

    path = Path(value.strip())
    if not value.strip() or path.is_absolute() or ".." in path.parts:
        return None
    if suffix is not None and path.suffix.casefold() != suffix:
        return None
    if project_root is not None:
        root = project_root.resolve()
        resolved = (root / path).resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            return None
    return path


def _expected_report_pair(
    record: dict[str, str], project_root: Path | None = None
) -> tuple[Path, Path] | None:
    json_path = _expected_path(
        record.get("expected_json", ""), project_root=project_root, suffix=".json"
    )
    markdown_path = _expected_path(
        record.get("expected_markdown", ""), project_root=project_root, suffix=".md"
    )
    expected = Path(".security/dependency-audit")
    if (
        json_path is None or markdown_path is None or json_path.parent != expected
        or markdown_path.parent != expected or json_path.stem != markdown_path.stem
    ):
        return None
    return json_path, markdown_path


def _timezone_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _package_v1(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {"ecosystem", "name", "version", "purl", "direct", "scope", "bom_ref"}
    return (
        required.issubset(value)
        and all(isinstance(value[key], str) for key in ("ecosystem", "name", "version", "purl"))
        and isinstance(value["direct"], bool)
        and value["scope"] in {"runtime", "development", "unknown"}
        and (value["bom_ref"] is None or isinstance(value["bom_ref"], str))
    )


def _source_status_v1(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {"source", "state", "attempted_at", "provenance", "diagnostic"}
    return (
        required.issubset(value)
        and all(isinstance(value[key], str) for key in required)
        and value["state"] in {"ok", "partial", "unavailable", "not_applicable"}
        and _timezone_timestamp(value["attempted_at"]) is not None
    )


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _affected_event_v1(value: object) -> bool:
    return (
        isinstance(value, dict)
        and {"kind", "value"}.issubset(value)
        and value["kind"] in {"introduced", "fixed", "last_affected", "limit"}
        and isinstance(value["value"], str)
    )


def _affected_range_v1(value: object) -> bool:
    return (
        isinstance(value, dict)
        and {"type", "events", "repo"}.issubset(value)
        and isinstance(value["type"], str)
        and isinstance(value["events"], list)
        and all(_affected_event_v1(event) for event in value["events"])
        and (value["repo"] is None or isinstance(value["repo"], str))
    )


def _affected_package_v1(value: object) -> bool:
    return (
        isinstance(value, dict)
        and {"ecosystem", "name", "purl", "versions", "ranges", "fixed_versions"}.issubset(value)
        and isinstance(value["ecosystem"], str)
        and isinstance(value["name"], str)
        and (value["purl"] is None or isinstance(value["purl"], str))
        and _string_list(value["versions"])
        and isinstance(value["ranges"], list)
        and all(_affected_range_v1(item) for item in value["ranges"])
        and _string_list(value["fixed_versions"])
    )


def _number_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    )


def _advisory_enrichment_v1(value: object) -> bool:
    required = {
        "source", "severity", "cvss_scores", "cvss_vectors", "epss_scores",
        "vulnerable_functions", "details",
    }
    return (
        isinstance(value, dict)
        and required.issubset(value)
        and isinstance(value["source"], str)
        and isinstance(value["severity"], str)
        and _number_list(value["cvss_scores"])
        and _string_list(value["cvss_vectors"])
        and _number_list(value["epss_scores"])
        and _string_list(value["vulnerable_functions"])
        and isinstance(value["details"], str)
    )


def _advisory_v1(value: object) -> bool:
    required = {
        "id", "aliases", "severity", "withdrawn", "fixed_versions", "references",
        "affected_ranges", "modified", "details", "source", "affected_packages", "enrichments",
    }
    return (
        isinstance(value, dict)
        and required.issubset(value)
        and isinstance(value["id"], str)
        and _string_list(value["aliases"])
        and isinstance(value["severity"], str)
        and isinstance(value["withdrawn"], bool)
        and _string_list(value["fixed_versions"])
        and _string_list(value["references"])
        and _string_list(value["affected_ranges"])
        and (value["modified"] is None or isinstance(value["modified"], str))
        and isinstance(value["details"], str)
        and isinstance(value["source"], str)
        and isinstance(value["affected_packages"], list)
        and all(_affected_package_v1(item) for item in value["affected_packages"])
        and isinstance(value["enrichments"], list)
        and all(_advisory_enrichment_v1(item) for item in value["enrichments"])
    )


def _audit_result_v1(value: object) -> str | None:
    """Validate required AuditResult 1.0 structure while tolerating unknown extension fields."""

    if not isinstance(value, dict) or not AUDIT_RESULT_REQUIRED.issubset(value):
        return "missing required AuditResult fields"
    if value["schema_version"] != "1.0":
        return "unsupported schema_version"
    if (
        value["mode"] not in {"change", "main", "release"}
        or _timezone_timestamp(value["timestamp"]) is None
        or not isinstance(value["project_revision"], str)
        or value["gate_status"] not in {"pass", "warnings", "blocked", "unavailable", "invalid"}
        or not isinstance(value["exit_code"], int) or isinstance(value["exit_code"], bool)
    ):
        return "invalid AuditResult scalar field types"
    inventory = value["inventory"]
    if not isinstance(inventory, dict) or not INVENTORY_REQUIRED.issubset(inventory):
        return "missing required InventoryResult fields"
    if (
        not isinstance(inventory["packages"], list)
        or not all(_package_v1(item) for item in inventory["packages"])
        or not isinstance(inventory["dependencies"], list)
        or not all(
            isinstance(edge, list) and len(edge) == 2
            and all(isinstance(item, str) for item in edge)
            for edge in inventory["dependencies"]
        )
        or not isinstance(inventory["fingerprint"], str)
        or re.fullmatch(r"[0-9a-f]{64}", inventory["fingerprint"]) is None
        or not isinstance(inventory["complete"], bool)
        or not isinstance(inventory["statuses"], list)
        or not all(_source_status_v1(item) for item in inventory["statuses"])
        or not isinstance(inventory["incomplete_reasons"], list)
        or not all(isinstance(item, str) for item in inventory["incomplete_reasons"])
    ):
        return "invalid InventoryResult field types"
    if not isinstance(value["sources"], list) or not all(
        _source_status_v1(item) for item in value["sources"]
    ):
        return "invalid SourceStatus collection"
    if not isinstance(value["findings"], list) or not all(
        isinstance(item, dict)
        and {"package", "advisory", "kev", "reachability", "reachability_evidence"}.issubset(item)
        and _package_v1(item["package"])
        and _advisory_v1(item["advisory"])
        and isinstance(item["kev"], bool)
        and item["reachability"] in {"reachable", "unreachable", "unknown", "not_assessed"}
        and isinstance(item["reachability_evidence"], list)
        and all(isinstance(evidence, str) for evidence in item["reachability_evidence"])
        for item in value["findings"]
    ):
        return "invalid Finding collection"
    if not isinstance(value["decisions"], list) or not all(
        isinstance(item, dict)
        and {"decision", "reason_codes", "mitigation", "risk_acceptance"}.issubset(item)
        and item["decision"] in {"excluded", "warn", "block"}
        and isinstance(item["reason_codes"], list)
        and all(isinstance(reason, str) for reason in item["reason_codes"])
        and isinstance(item["mitigation"], str)
        and isinstance(item["risk_acceptance"], str)
        for item in value["decisions"]
    ):
        return "invalid DecisionRecord collection"
    return None


def _git_revision(project_root: Path) -> str | None:
    """Read the canonical current revision through Git, including worktrees and packed refs."""

    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip().casefold()
    return revision if re.fullmatch(r"[0-9a-f]{40,64}", revision) else None


def _evidence_record(body: str, label: str) -> tuple[dict[str, str], int] | None:
    """Parse one canonical pipe-delimited human-readable evidence record."""

    matches = [
        match for match in STRUCTURED_EVIDENCE.finditer(body)
        if match.group("label").strip().casefold() == label.casefold()
    ]
    if len(matches) != 1:
        return None
    fields: dict[str, str] = {}
    for item in matches[0].group("value").split("|"):
        key, separator, value = item.strip().partition("=")
        if not separator or not key.strip() or key.strip().casefold() in fields:
            return None
        fields[key.strip().casefold()] = value.strip().strip("`")
    return fields, matches[0].start()


def _safe_link(value: str, project_root: Path | None) -> tuple[str, Path | None] | None:
    """Parse one local Markdown link and resolve its project-contained target when possible."""

    match = re.fullmatch(r"\[([^\]\n]+)\]\(([^)\n]+)\)", value.strip())
    if match is None:
        return None
    label, raw_target = match.group(1).strip("` "), match.group(2).strip()
    split = urlsplit(raw_target)
    if split.scheme or split.netloc or split.query or not split.path:
        return None
    parts = list(Path(unquote(split.path)).parts)
    leading = 0
    while parts and parts[0] == "..":
        leading += 1
        parts.pop(0)
    if leading not in {0, 2} or not parts:
        return None
    relative = Path(*parts)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    if project_root is None:
        return label, relative
    root = project_root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return label, resolved


def _report_pair(
    record: dict[str, str], project_root: Path | None, *, completed: bool
) -> tuple[Path | None, Path | None] | None:
    json_link = _safe_link(record.get("json", ""), project_root)
    markdown_link = _safe_link(record.get("markdown", ""), project_root)
    if json_link is None or markdown_link is None:
        return None
    json_path, markdown_path = json_link[1], markdown_link[1]
    assert json_path is not None and markdown_path is not None
    json_relative = json_path if project_root is None else json_path.relative_to(project_root.resolve())
    markdown_relative = markdown_path if project_root is None else markdown_path.relative_to(project_root.resolve())
    expected = Path(".security/dependency-audit")
    if (
        json_relative.parent != expected or markdown_relative.parent != expected
        or json_path.suffix.casefold() != ".json" or markdown_path.suffix.casefold() != ".md"
        or json_path.stem != markdown_path.stem
        or completed and project_root is not None and (
            not json_path.is_file() or not markdown_path.is_file()
        )
    ):
        return None
    return json_path, markdown_path


def _linked_paths(value: str, project_root: Path | None, *, completed: bool) -> list[tuple[str, Path | None]] | None:
    links = list(re.finditer(r"\[[^\]\n]+\]\([^)\n]+\)", value))
    if not links or re.sub(r"\[[^\]\n]+\]\([^)\n]+\)|[\s,]+", "", value):
        return None
    parsed = [_safe_link(match.group(0), project_root) for match in links]
    if any(item is None for item in parsed):
        return None
    result = [item for item in parsed if item is not None]
    if completed and project_root is not None and any(
        path is None or not path.is_file() for _, path in result
    ):
        return None
    return result


def _change_sequence_error(
    body: str, owned_files: list[str], *, checked: bool, project_root: Path | None
) -> str | None:
    """Validate canonical structured dependency-change evidence; prose never substitutes."""

    labels = (
        "Context7 evidence", "Pre-change dependency audit", "Resolution edit",
        "Project tests", "Post-change dependency audit",
    )
    records = {label: _evidence_record(body, label) for label in labels}
    missing = [label for label, record in records.items() if record is None]
    if missing:
        return "requires canonical structured evidence records: " + ", ".join(missing)
    if [records[label][1] for label in labels if records[label] is not None] != sorted(
        records[label][1] for label in labels if records[label] is not None
    ):
        return "must order structured records Context7, pre-change, edit, tests, post-change"
    phase = "completed" if checked else "pending"
    context = (records["Context7 evidence"] or ({}, 0))[0]
    context_keys = {"state", "identity", "version", "decision"}
    if (
        set(context) != context_keys or context.get("state") != phase
        or not re.fullmatch(r"/[\w.-]+/[\w.-]+", context.get("identity", ""))
        or not re.fullmatch(r"v?\d+(?:\.\d+)+(?:[-+][\w.-]+)?", context.get("version", ""))
        or not context.get("decision")
    ):
        return f"has invalid {phase} Context7 evidence"

    audit_targets: list[tuple[str, str]] = []
    audit_metadata: list[tuple[datetime, str, str]] = []
    for label in ("Pre-change dependency audit", "Post-change dependency audit"):
        audit = (records[label] or ({}, 0))[0]
        pending_keys = {"state", "command", "expected_json", "expected_markdown", "review"}
        completed_keys = {
            "state", "command", "mode", "timestamp", "project_revision",
            "inventory_fingerprint", "json", "markdown", "review", "result", "exit",
            "decision", "warnings_reviewed", "clean",
        }
        report_pair = _report_pair(audit, project_root, completed=True) if checked else None
        if (
            set(audit) != (completed_keys if checked else pending_keys)
            or audit.get("state") != phase
            or audit.get("command") != "dependency-security-audit change"
            or audit.get("review") != phase
            or checked and report_pair is None
            or not checked and _expected_report_pair(audit, project_root) is None
        ):
            return f"has invalid {phase} {label} record"
        if checked:
            try:
                audit_timestamp = datetime.fromisoformat(
                    audit["timestamp"].replace("Z", "+00:00")
                )
            except ValueError:
                return f"has invalid {label} timestamp"
            exits = {"pass": "0", "warnings": "0", "blocked": "1", "unavailable": "2", "invalid": "3"}
            result = audit.get("result", "")
            if (
                audit.get("mode") != "change" or audit_timestamp.tzinfo is None
                or not re.fullmatch(r"[0-9a-f]{40,64}", audit.get("project_revision", ""))
                or not re.fullmatch(r"[0-9a-f]{64}", audit.get("inventory_fingerprint", ""))
                or result not in exits or audit.get("exit") != exits[result] or not audit.get("decision")
                or result in {"blocked", "unavailable", "invalid"}
                or result == "warnings" and not (
                    audit.get("warnings_reviewed") == "true" and audit.get("clean") == "false"
                )
                or result == "pass" and audit.get("clean") != "true"
            ):
                return f"cannot complete {label} with its result/exit/decision semantics"
            if project_root is not None:
                assert report_pair[0] is not None
                try:
                    evidence = json.loads(report_pair[0].read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    return f"cannot parse {label} JSON evidence"
                schema_error = _audit_result_v1(evidence)
                inventory = evidence.get("inventory") if isinstance(evidence, dict) else None
                if (
                    schema_error is not None
                    or evidence.get("mode") != "change"
                    or evidence.get("timestamp") != audit["timestamp"]
                    or evidence.get("project_revision") != audit["project_revision"]
                    or not isinstance(inventory, dict)
                    or inventory.get("fingerprint") != audit["inventory_fingerprint"]
                    or evidence.get("gate_status") != result
                    or evidence.get("exit_code") != int(audit["exit"])
                ):
                    return f"{label} JSON schema/value correlation failed"
            audit_metadata.append((audit_timestamp, audit["project_revision"], audit["inventory_fingerprint"]))
        pair_for_identity = report_pair if checked else _expected_report_pair(audit, project_root)
        assert pair_for_identity is not None
        audit_targets.append(tuple(str(path) for path in pair_for_identity))
    if audit_targets[0][0] == audit_targets[1][0] or audit_targets[0][1] == audit_targets[1][1]:
        return "must use distinct pre-change and post-change JSON/Markdown reports"
    now = datetime.now(timezone.utc)
    if checked and not (
        audit_metadata[0][0] < audit_metadata[1][0]
        and audit_metadata[0][0].astimezone(timezone.utc) <= now
        and audit_metadata[1][0].astimezone(timezone.utc) <= now
        and now - audit_metadata[1][0].astimezone(timezone.utc) <= timedelta(hours=DELIVERY_FRESHNESS_HOURS)
        and audit_metadata[1][0] - audit_metadata[0][0] <= timedelta(days=CHANGE_MAX_SEQUENCE_DAYS)
        and audit_metadata[0][1] == audit_metadata[1][1]
        and audit_metadata[0][2] != audit_metadata[1][2]
    ):
        return (
            "pre/post audits require nonfuture ordered timestamps within 7 days, a post audit "
            "no older than 24 hours, one project revision, and changed inventory fingerprints"
        )

    edit = (records["Resolution edit"] or ({}, 0))[0]
    expected_edit_keys = {"state", "files"} if checked else {"state", "expected_files"}
    if set(edit) != expected_edit_keys or edit.get("state") != phase:
        return f"has invalid {phase} resolution edit record"
    if checked:
        linked = _linked_paths(edit.get("files", ""), project_root, completed=True)
        if linked is None:
            return "completed resolution edit files must be safe local Markdown links"
        linked_files = {label for label, _ in linked}
    else:
        expected_files = [item.strip() for item in edit.get("expected_files", "").split(",")]
        if set(edit) != {"state", "expected_files"} or any(
            _expected_path(item, project_root=project_root) is None for item in expected_files
        ):
            return "pending resolution edit requires safe project-relative expected_files"
        linked_files = set(expected_files)
    required_files = {path for path in owned_files if _is_resolution_path(path)}
    if not required_files or not required_files.issubset(linked_files):
        return "resolution edit must link every owned manifest/lock with a matching label"
    if checked and project_root is not None:
        root = project_root.resolve()
        for label, path in linked:
            assert path is not None
            expected = Path(label)
            if expected.is_absolute():
                if path != expected.resolve():
                    return "resolution edit link label and target disagree"
            elif path.relative_to(root).as_posix() != expected.as_posix():
                return "resolution edit link label and target disagree"
    tests = (records["Project tests"] or ({}, 0))[0]
    test_keys = {"state", "evidence"} if checked else {"state", "expected_evidence"}
    if set(tests) != test_keys or tests.get("state") != phase:
        return f"has invalid {phase} project tests record"
    if checked:
        if _linked_paths(tests.get("evidence", ""), project_root, completed=True) is None:
            return "completed project test evidence must be safe existing local Markdown links"
    elif any(
        _expected_path(item.strip(), project_root=project_root) is None
        for item in tests["expected_evidence"].split(",")
    ):
        return "pending project tests require safe project-relative expected_evidence"
    return None


def _delivery_gate_error(
    body: str, mode: str, *, checked: bool, project_root: Path | None
) -> str | None:
    """Validate one canonical structured, fresh, fail-closed delivery evidence record."""

    parsed = _evidence_record(body, "Dependency delivery evidence")
    if parsed is None:
        return "requires one canonical Dependency delivery evidence record"
    record = parsed[0]
    if not checked:
        if (
            set(record) != {"state", "mode", "expected_json", "expected_markdown"}
            or record.get("state") != "pending" or record.get("mode") != mode
        ):
            return "requires exact pending delivery plan fields"
        if _expected_report_pair(record, project_root) is None:
            return "pending delivery reports must be safe project-relative expected paths"
        return None
    required = {"state", "mode", "timestamp", "revision", "json", "markdown", "review", "result", "exit", "decision", "warnings_reviewed", "clean"}
    if set(record) != required:
        return "requires exact completed delivery evidence fields"
    try:
        timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        return "has invalid timezone-aware ISO timestamp"
    if (
        record["state"] != "completed" or record["mode"] != mode or timestamp.tzinfo is None
        or not re.fullmatch(r"[0-9a-f]{40,64}", record["revision"])
        or _report_pair(record, project_root, completed=True) is None
        or record["review"] != "completed" or not record["decision"]
    ):
        return "has invalid completed mode/revision/timestamp/report/review/decision evidence"
    exits = {"pass": "0", "warnings": "0", "blocked": "1", "unavailable": "2", "invalid": "3"}
    status = record["result"]
    if status not in exits or record["exit"] != exits[status]:
        return "has invalid status-to-exit mapping"
    if status in {"blocked", "unavailable", "invalid"}:
        return f"cannot ship structured delivery status {status}"
    if status == "warnings" and not (
        record.get("warnings_reviewed") == "true" and record.get("clean") == "false"
    ):
        return "warnings require warnings_reviewed=true and clean=false"
    if status == "pass" and record.get("clean") != "true":
        return "pass requires clean=true"
    if project_root is not None:
        pair = _report_pair(record, project_root, completed=True)
        assert pair is not None and pair[0] is not None
        try:
            evidence = json.loads(pair[0].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return "cannot parse delivery JSON evidence"
        schema_error = _audit_result_v1(evidence)
        if schema_error is not None:
            return f"delivery JSON schema is invalid: {schema_error}"
        for key, expected in (
            ("mode", mode), ("timestamp", record["timestamp"]),
            ("project_revision", record["revision"]), ("gate_status", status),
        ):
            if str(evidence.get(key, "")) != expected:
                return f"delivery JSON {key} does not match the record"
        if str(evidence.get("exit_code", "")) != record["exit"]:
            return "delivery JSON exit does not match the record"
        now = datetime.now(timezone.utc)
        age_hours = (now - timestamp.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours < 0 or age_hours > DELIVERY_FRESHNESS_HOURS:
            return f"delivery evidence is outside the {DELIVERY_FRESHNESS_HOURS}-hour freshness window"
        revision = _git_revision(project_root)
        if revision is None or revision != record["revision"].casefold():
            return "delivery revision cannot correlate to the current git target"
    return None


def _affirmative_dependency_change_claim(text: str) -> bool:
    """Recognize only present/future implementation claims that change dependency resolution."""

    subclauses = re.split(r"(?:[.;](?=\s)|\n+|,?\s+\b(?:and|but|then)\b\s+)", text)
    historical_subject = re.compile(
        r"(?i)\b(?:previously|historically|formerly|already|had|was|were|"
        r"prior\s+release|last\s+release|previous\s+release|"
        r"(?:one|two|three|four|several|many|\d+)\s+releases?\s+ago)\b"
    )
    documentation_governor = re.compile(
        r"(?i)\b(?:document|describe|explain|show\s+an?\s+example\s+of)\w*\b.{0,30}"
    )
    interface_governor = re.compile(
        r"(?i)\b(?:render|display|show|label)\w*\b.{0,30}"
    )
    interface_object = re.compile(r"(?i)\b(?:ui|label|copy|text|button|heading|message)\b")
    documentation_object = re.compile(r"(?i)^\s*(?:documentation|docs?)\b")
    past_action = re.compile(r"(?i)^\s*(?:upgraded|bumped|pinned|updated|changed|replaced)\b")
    release_time = re.compile(r"(?i)\b(?:prior|last|previous)\s+release\b")
    for subclause in subclauses:
        for match in DEPENDENCY_CHANGE_NARRATIVE.finditer(subclause):
            prefix = subclause[:match.start()]
            suffix = subclause[match.end():match.end() + 30]
            local = subclause[max(0, match.start() - 50):match.end() + 50]
            if NEGATED_STEP.search(prefix) or NEGATED_STEP.search(match.group(0)):
                continue
            if historical_subject.search(prefix):
                continue
            if past_action.search(match.group(0)) and release_time.search(subclause):
                continue
            if documentation_governor.search(prefix):
                continue
            if interface_governor.search(prefix) and interface_object.search(local):
                continue
            if interface_object.search(suffix):
                continue
            if documentation_object.search(suffix):
                continue
            if re.search(
                r"(?i)\b(?:library|package)\s+(?:documentation|docs?)\b",
                match.group(0),
            ):
                continue
            if re.search(
                r"(?i)\b(?:documentation|docs?)\s+for\s+(?:the\s+)?"
                r"(?:dependenc\w*|library|package)(?:\s+version)?\b",
                match.group(0),
            ):
                continue
            return True
    return False


def dependency_security_errors(
    design: str,
    tasks_text: str,
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Validate design evidence and executable dependency change/delivery task contracts."""

    errors: list[str] = []
    visible_design = FENCED_CODE.sub("", design)
    technology = CURRENT_TECHNOLOGY_HEADING.search(visible_design)
    security = DEPENDENCY_SECURITY_HEADING.search(visible_design)
    if technology is None:
        errors.append("03_design.md must contain Current Technology Evidence")
    if security is None:
        errors.append("03_design.md must contain Dependency Security Evidence")
    elif technology is not None and security.start() < technology.start():
        errors.append("Dependency Security Evidence must follow Current Technology Evidence")
    elif technology is not None and re.search(
        r"(?mi)^##\s+", visible_design[technology.end():security.start()]
    ):
        errors.append("Dependency Security Evidence must be adjacent to Current Technology Evidence")

    technology_content = _section_content(visible_design, technology)
    security_content = _section_content(visible_design, security)
    if technology is not None and not _meaningful_evidence(technology_content):
        errors.append("Current Technology Evidence must contain material evidence or a reasoned N/A")
    elif technology is not None and not _reasoned_na(technology_content):
        missing = _material_technology_evidence_missing(technology_content)
        if missing:
            errors.append("Current Technology Evidence lacks material fields: " + ", ".join(missing))
    if security is not None:
        if not _meaningful_evidence(security_content):
            errors.append("Dependency Security Evidence must contain material evidence or a reasoned N/A")
        elif not _reasoned_na(security_content):
            missing = _material_security_evidence_missing(security_content)
            if missing:
                errors.append("Dependency Security Evidence lacks material fields: " + ", ".join(missing))

    headers = list(TASK_HEADER.finditer(tasks_text))
    for index, header in enumerate(headers):
        task_id = header.group("id")
        if "." not in task_id:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(tasks_text)
        body = tasks_text[header.end():end]
        files = [path for value in FILES_FIELD.findall(body) for path in parse_owned_files(value)]
        resolution_values = DEPENDENCY_RESOLUTION_FIELD.findall(body)
        delivery_values = DEPENDENCY_DELIVERY_FIELD.findall(body)
        resolution = resolution_values[0].strip().casefold() if len(resolution_values) == 1 else None
        delivery = delivery_values[0].strip().casefold() if len(delivery_values) == 1 else None
        checked = header.group("status").lower() == "x"
        if resolution == "change":
            errors.extend(_resolution_ownership_errors(task_id, files, project_root))
            sequence_error = _change_sequence_error(
                body, files, checked=checked, project_root=project_root
            )
            if sequence_error:
                errors.append(f"dependency-changing task {task_id} {sequence_error}")
        elif resolution == "none":
            owned_resolution = (
                bool(_owned_resolution_paths(files, project_root))
                if project_root is not None
                else any(_is_resolution_path(path) for path in files)
            )
            narrative = header.group("title") + "\n" + body.split("**Files:**", 1)[0]
            if owned_resolution or _affirmative_dependency_change_claim(narrative):
                errors.append(
                    f"task {task_id} contradicts Dependency resolution: none with change prose or ownership"
                )
        if delivery in {"main", "release"}:
            gate_error = _delivery_gate_error(
                body, delivery, checked=checked, project_root=project_root
            )
            if gate_error:
                errors.append(f"delivery gate {task_id} {gate_error}")
    return errors


def compute_execution_view(tasks: list[dict[str, object]]) -> dict[str, object]:
    """Compute the active stage, ready/blocked partition, and delegation split once.

    Both `emit_result`'s ephemeral `--format json` output and the persisted `04_tasks.json`
    sidecar (`build_tasks_sidecar`) derive their `execution`/`concurrency` views from this single
    computation, so the two can never silently diverge.
    """
    by_id = {str(task["id"]): task for task in tasks}
    required_incomplete = [task for task in tasks if not task["checked"] and not task["optional"]]
    optional_incomplete = [task for task in tasks if not task["checked"] and task["optional"]]
    stage_source = required_incomplete or optional_incomplete
    active_stage = min(
        (int(task["stage"]) for task in stage_source if task["stage"] is not None),
        default=None,
    )
    active_pool = [task for task in tasks if not task["checked"] and task["stage"] == active_stage]
    ready: list[dict[str, object]] = []
    blocked: dict[str, list[str]] = {}
    for task in active_pool:
        unmet = [
            dependency
            for dependency in task["depends_on"]
            if dependency not in by_id or not by_id[dependency]["checked"]
        ]
        if unmet:
            blocked[str(task["id"])] = unmet
        else:
            ready.append(task)
    parallel = [task for task in ready if task["delegation"] == "parallel-safe"]
    serial = [task for task in ready if task["delegation"] != "parallel-safe"]
    return {
        "active_stage": active_stage,
        "ready": ready,
        "parallel": parallel,
        "serial": serial,
        "blocked": blocked,
    }


def build_task_waves(view: dict[str, object]) -> list[dict[str, object]]:
    """Group a ready pool into the wave order `spec-execute`'s guarded scheduler follows.

    One parallel wave (every ready `parallel-safe` task at once) comes first when any exist,
    followed by one single-task serial wave per remaining ready task in checklist order — the
    same "parallel batch, then serial tasks one at a time" shape the per-wave subagent loop in
    `spec-execute/SKILL.md` already describes in prose.
    """
    waves: list[dict[str, object]] = []
    parallel_ids = [str(task["id"]) for task in view["parallel"]]
    if parallel_ids:
        waves.append({"wave": len(waves) + 1, "mode": "parallel", "tasks": parallel_ids})
    for task in view["serial"]:
        waves.append({"wave": len(waves) + 1, "mode": "serial", "tasks": [str(task["id"])]})
    return waves


# --- JSON sidecars (generated, hash-verified; see references/artifacts.md) ---------------------
#
# `00_state.json`, `04_tasks.json`, and `05_execution.json` are pure derived artifacts of
# `00_state.md`, `04_tasks.md`, and `05_execution.md`: never hand-maintained, always regenerated
# by `--emit-json` in the same step the Markdown changes, and rejected as stale by
# `sidecar_freshness_errors` (wired into every run, mirroring how `spec-nav.py`'s nav blocks are
# checked unconditionally) once their `generated_from.sha256` no longer matches the current
# Markdown text.

VALID_TASK_CATEGORIES = {"quick_lookup", "code_analysis", "heavy_reasoning", "review"}
# Deterministic, documented mapping from a task's free-text Risk field to the `declared_risk`
# vocabulary `model-router.py` expects (`none`/`elevated`/`high`). Only ever raises the routed
# tier (see model-router.py's risk-escalation step); never lowers it.
RISK_TO_DECLARED_RISK = {"low": "none", "medium": "elevated", "high": "high"}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _task_declared_risk(risk_text: str | None) -> str:
    """Map a task's leading Risk word to model-router.py's declared_risk vocabulary."""
    if not risk_text:
        return "none"
    match = re.match(r"(?i)\s*(low|medium|high)\b", risk_text)
    return RISK_TO_DECLARED_RISK.get(match.group(1).lower(), "none") if match else "none"


def _gantt_safe_id(raw: str) -> str:
    """Sanitize an arbitrary sidecar id into a bare identifier for the gantt IR (ir.md)."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not re.match(r"[A-Za-z_]", safe):
        safe = f"b_{safe}"
    return safe


def build_tasks_sidecar(
    tasks_text: str,
    task_graph: list[dict[str, object]],
    graph_errors: list[str],
    criteria: set[str],
    contract: dict[str, object],
) -> tuple[dict[str, object] | None, list[str]]:
    """Build the `04_tasks.json` payload: the task graph plus per-task model routing.

    Requires every leaf to declare a recognized `Task category` (this is where that field is
    actually enforced — see the comment in `task_dependency_graph`) and resolves each task's
    `capability_tier`/`resolved_model` AND independent `reasoning_level` by calling
    `model-router.py`'s `resolve()` in-process, once per task, never by shelling out. Refuses to
    emit a sidecar for a task graph that already has structural errors, since a stale/invalid
    graph has no well-defined concurrency view.
    """
    if graph_errors:
        return None, ["cannot emit 04_tasks.json while 04_tasks.md has task-graph errors"]
    errors: list[str] = []
    categories_by_id: dict[str, str] = {}
    for task in task_graph:
        task_id = str(task["id"])
        category = task.get("task_category")
        if category is None:
            errors.append(f"task {task_id} must declare exactly one Task category field")
        elif category not in VALID_TASK_CATEGORIES:
            errors.append(
                f"task {task_id} Task category must be one of {sorted(VALID_TASK_CATEGORIES)}"
            )
        else:
            categories_by_id[task_id] = category
    if errors:
        return None, errors

    view = compute_execution_view(task_graph)
    tasks_payload: list[dict[str, object]] = []
    for task in task_graph:
        task_id = str(task["id"])
        category = categories_by_id[task_id]
        declared_risk = _task_declared_risk(task.get("risk"))
        routed = MODEL_ROUTER.resolve(contract, category, declared_risk)
        tasks_payload.append(
            {
                "id": task_id,
                "title": task["title"],
                "checked": task["checked"],
                "optional": task["optional"],
                "stage": task["stage"],
                "depends_on": task["depends_on"],
                "files": task["files"],
                "delegation": task["delegation"],
                "dependency_resolution": task["dependency_resolution"],
                "dependency_delivery": task["dependency_delivery"],
                "interfaces": task["interfaces"],
                "verification": task["verification"],
                "risk": task["risk"],
                "requirements": task["requirements"],
                "task_category": category,
                "capability_tier": routed["capability_tier"],
                "resolved_model": routed["resolved_model"],
                "reasoning_level": routed["reasoning_level"],
            }
        )
    stages: dict[str, list[str]] = {}
    for task in task_graph:
        if task["stage"] is not None:
            stages.setdefault(str(task["stage"]), []).append(str(task["id"]))
    concurrency = {
        "active_stage": view["active_stage"],
        "ready": [str(task["id"]) for task in view["ready"]],
        "parallel_candidates": [str(task["id"]) for task in view["parallel"]],
        "serial_candidates": [str(task["id"]) for task in view["serial"]],
        "blocked": view["blocked"],
        "waves": build_task_waves(view),
    }
    payload = {
        "schema_version": 1,
        "generated_from": {"file": "04_tasks.md", "sha256": _sha256_text(tasks_text)},
        "requirement_count": len(criteria),
        "stages": stages,
        "tasks": tasks_payload,
        "concurrency": concurrency,
    }
    return payload, []


def _parse_elapsed(value: str) -> int | str:
    return value if value in ("pending", "unknown") else int(value)


def _gantt_bar_for_row(
    id_base: str, label_prefix: str, started: str, elapsed: str, outcome: str
) -> dict[str, object] | None:
    """Render one closed timing row to a gantt bar, or None if its duration is not yet known.

    Mirrors `spec-execute/SKILL.md`'s Execution Gantt rules exactly: a completed zero-second
    interval renders as `1s` (the ledger keeps the exact `0`); an `active` row (open, no stop yet)
    or an `interrupted` row with `unknown` elapsed has no known duration and is omitted here —
    callers surface it in `unresolved` instead of fabricating a bar.
    """
    if outcome == "active" or elapsed in ("pending", "unknown"):
        return None
    elapsed_int = int(elapsed)
    start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
    end_dt = start_dt + timedelta(seconds=max(elapsed_int, 1))
    tag = "crit" if outcome in ("failed", "blocked") else "done"
    return {
        "id": _gantt_safe_id(id_base),
        "label": f"{label_prefix} ({outcome}, {elapsed_int}s)",
        "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "end": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "tags": [tag],
    }


def build_execution_sidecar(execution_text: str) -> tuple[dict[str, object] | None, list[str]]:
    """Build the `05_execution.json` payload: the timing ledger plus an embedded gantt IR.

    The `gantt` object is exactly the `timeline`/`gantt` IR `mermaid/scripts/render.py` consumes
    (see `mermaid/reference/ir.md`) — render it directly with `render.py --target gantt` instead
    of hand-transcribing ledger rows into a fenced Mermaid block, then render-validate the
    generated source as usual.
    """
    run_rows, run_error = _table_rows(
        execution_text, "Run Intervals",
        ["Run ID", "Started UTC", "Stopped UTC", "Elapsed Seconds", "Outcome"],
    )
    attempt_rows, attempt_error = _table_rows(
        execution_text, "Task Attempt Intervals",
        [
            "Run ID", "Stage/Wave", "Task", "Attempt", "Started UTC",
            "Stopped UTC", "Elapsed Seconds", "Outcome",
        ],
    )
    errors = [error for error in (run_error, attempt_error) if error]
    if errors:
        return None, errors

    runs: list[dict[str, object]] = []
    run_bars: list[dict[str, object]] = []
    unresolved: list[dict[str, str]] = []
    for row in run_rows:
        if len(row) != 5:
            errors.append(f"run timing row has {len(row)} cells; expected 5")
            continue
        run_id, started, stopped, elapsed, outcome = row
        runs.append(
            {
                "run_id": run_id, "started_utc": started, "stopped_utc": stopped,
                "elapsed_seconds": _parse_elapsed(elapsed), "outcome": outcome,
            }
        )
        bar = _gantt_bar_for_row(run_id, run_id, started, elapsed, outcome)
        if bar is not None:
            run_bars.append(bar)
        elif outcome == "active" or elapsed == "unknown":
            unresolved.append({"kind": "run", "id": run_id, "reason": outcome})

    attempts: list[dict[str, object]] = []
    sections: dict[str, list[dict[str, object]]] = {}
    for row in attempt_rows:
        if len(row) != 8:
            errors.append(f"task attempt timing row has {len(row)} cells; expected 8")
            continue
        run_id, stage_wave, task_id, attempt, started, stopped, elapsed, outcome = row
        attempts.append(
            {
                "run_id": run_id, "stage_wave": stage_wave, "task": task_id,
                "attempt": int(attempt) if attempt.isdigit() else attempt,
                "started_utc": started, "stopped_utc": stopped,
                "elapsed_seconds": _parse_elapsed(elapsed), "outcome": outcome,
            }
        )
        bar_id = f"{task_id}_attempt{attempt}"
        bar = _gantt_bar_for_row(bar_id, f"{task_id} attempt {attempt}", started, elapsed, outcome)
        if bar is not None:
            sections.setdefault(stage_wave, []).append(bar)
        elif outcome == "active" or elapsed == "unknown":
            unresolved.append({"kind": "task_attempt", "id": f"{task_id}#{attempt}", "reason": outcome})
    if errors:
        return None, errors

    gantt_sections: list[dict[str, object]] = []
    if run_bars:
        gantt_sections.append({"name": "Execution Runs", "bars": run_bars})
    for stage_wave, bars in sections.items():
        gantt_sections.append({"name": stage_wave, "bars": bars})

    payload = {
        "schema_version": 1,
        "generated_from": {"file": "05_execution.md", "sha256": _sha256_text(execution_text)},
        "runs": runs,
        "task_attempts": attempts,
        "gantt": {
            "diagram": "timeline",
            "target": "gantt",
            "dateFormat": "YYYY-MM-DDTHH:mm:ss",
            "axisFormat": "%m-%d %H:%M",
            "sections": gantt_sections,
        },
        "unresolved": unresolved,
    }
    return payload, []


STATE_GATE_NAMES = ("Discovery", "Requirements", "Design", "Tasks", "Audit", "Execution")
# Evidence is the canonical template's third column, but tolerate a two-column Gate|Status table
# too (some specs omit it) — an absent Evidence cell means an empty string, not a missing row.
STATE_GATE_ROW = re.compile(
    r"(?m)^\|\s*(" + "|".join(STATE_GATE_NAMES) + r")\s*\|\s*([^|]+?)\s*\|(?:\s*([^|]*?)\s*\|)?\s*$"
)
STATE_CHANGE_CONTROL_SECTION = re.compile(r"(?ms)^##\s+Change Control\s*$(.*?)(?=^##\s+|\Z)")


def build_state_sidecar(state_text: str) -> tuple[dict[str, object] | None, list[str]]:
    """Build the `00_state.json` payload: the canonical Gate/Status/Evidence table, exactly.

    This is the one sidecar `--ready` gate-checking depends on, so it stays a direct structural
    parse of the same table a human reads — no derived/computed fields, so there is nothing here
    that could disagree with the Markdown by construction (only by going stale, which
    `sidecar_freshness_errors` already catches).
    """
    visible = FENCED_CODE.sub("", state_text)
    matches = list(STATE_GATE_ROW.finditer(visible))
    found = {match.group(1) for match in matches}
    missing = [name for name in STATE_GATE_NAMES if name not in found]
    if missing:
        return None, [f"00_state.md is missing the canonical Gate table row(s): {missing}"]
    gates: dict[str, dict[str, str]] = {
        match.group(1).casefold(): {
            "status": match.group(2).strip(),
            "evidence": (match.group(3) or "").strip(),
        }
        for match in matches
    }
    change_control: list[str] = []
    section = STATE_CHANGE_CONTROL_SECTION.search(visible)
    if section:
        for line in section.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and not stripped[2:].strip().startswith("<"):
                change_control.append(stripped[2:].strip())
    payload = {
        "schema_version": 1,
        "generated_from": {"file": "00_state.md", "sha256": _sha256_text(state_text)},
        "gates": gates,
        "change_control": change_control,
    }
    return payload, []


def _read_json_sidecar(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, f"{path.name} is not valid JSON"
    if not isinstance(payload, dict):
        return None, f"{path.name} must be a JSON object"
    return payload, None


def _sidecar_pairs(root: Path) -> list[tuple[Path, Path, str, str]]:
    """Return (json_path, md_path, json_name, md_name) tuples for root and sidecars/."""
    pairs: list[tuple[Path, Path, str, str]] = []
    names = (
        ("00_state.json", "00_state.md"),
        ("01_discovery.json", "01_discovery.md"),
        ("02_requirements.json", "02_requirements.md"),
        ("03_design.json", "03_design.md"),
        ("04_tasks.json", "04_tasks.md"),
        ("05_execution.json", "05_execution.md"),
    )
    for json_name, md_name in names:
        # Check sidecars/ subfolder first, then root
        sidecar_path = root / "sidecars" / json_name
        if not sidecar_path.is_file():
            sidecar_path = root / json_name
        if sidecar_path.is_file():
            pairs.append((sidecar_path, root / md_name, json_name, md_name))
    return pairs


def sidecar_freshness_errors(root: Path) -> list[str]:
    """Report a JSON sidecar whose `generated_from.sha256` no longer matches its Markdown twin.

    Mirrors `spec-nav.py`'s nav-block check in mechanism (unconditional, hash-based) but not in
    mandatoriness: a spec that has never generated sidecars is not penalized — only an existing
    sidecar that has gone stale, or an orphaned sidecar whose Markdown twin disappeared, is an error.
    """
    errors: list[str] = []
    pairs = _sidecar_pairs(root)
    for json_path, md_path, json_name, md_name in pairs:
        payload, error = _read_json_sidecar(json_path)
        if error:
            errors.append(error)
            continue
        if not md_path.is_file():
            errors.append(f"{json_name} exists without {md_name}; remove the orphaned sidecar")
            continue
        generated_from = payload.get("generated_from")
        current_hash = _sha256_text(md_path.read_text(encoding="utf-8"))
        if (
            not isinstance(generated_from, dict)
            or generated_from.get("file") != md_name
            or generated_from.get("sha256") != current_hash
        ):
            errors.append(f"{json_name} is stale; regenerate with --emit-json")
    return errors


def emit_json_sidecars(
    target_dir: Path,
    *,
    tasks_text: str | None,
    task_graph: list[dict[str, object]],
    graph_errors: list[str],
    criteria: set[str],
    execution_text: str | None,
    state_text: str | None = None,
) -> tuple[list[str], list[str]]:
    """Write `00_state.json`/`04_tasks.json`/`05_execution.json`; return (written, errors)."""
    written: list[str] = []
    errors: list[str] = []
    # If sidecars/ folder exists in target_dir, write sidecars there
    out_dir = target_dir / "sidecars" if (target_dir / "sidecars").is_dir() else target_dir

    if state_text is not None:
        payload, state_errors = build_state_sidecar(state_text)
        if state_errors:
            errors.extend(f"00_state.json: {error}" for error in state_errors)
        else:
            (out_dir / "00_state.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            written.append("00_state.json")
    if tasks_text is not None:
        contract = MODEL_ROUTER.load_contract()
        payload, task_errors = build_tasks_sidecar(tasks_text, task_graph, graph_errors, criteria, contract)
        if task_errors:
            errors.extend(f"04_tasks.json: {error}" for error in task_errors)
        else:
            (out_dir / "04_tasks.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            written.append("04_tasks.json")
    if execution_text is not None:
        payload, execution_errors = build_execution_sidecar(execution_text)
        if execution_errors:
            errors.extend(f"05_execution.json: {error}" for error in execution_errors)
        else:
            (out_dir / "05_execution.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            written.append("05_execution.json")
    return written, errors


def emit_result(
    output_format: str,
    root: Path,
    criteria: set[str],
    tasks: list[dict[str, object]],
    warnings: list[str],
    errors: list[str],
) -> int:
    stages: dict[str, list[str]] = {}
    for task in tasks:
        if task["stage"] is not None:
            stages.setdefault(str(task["stage"]), []).append(str(task["id"]))
    view = compute_execution_view(tasks) if not errors else {
        "active_stage": None, "ready": [], "parallel": [], "serial": [], "blocked": {},
    }
    active_stage = view["active_stage"]
    ready_ids = [str(task["id"]) for task in view["ready"]]
    parallel_ids = [str(task["id"]) for task in view["parallel"]]
    serial_ids = [str(task["id"]) for task in view["serial"]]
    blocked = view["blocked"]
    ok = not errors
    if output_format == "json":
        print(
            json.dumps(
                {
                    "ok": ok,
                    "spec_dir": str(root),
                    "requirement_count": len(criteria),
                    "task_graph": {"tasks": tasks, "stages": stages},
                    "execution": {
                        "active_stage": active_stage,
                        "ready": ready_ids,
                        "parallel_candidates": parallel_ids,
                        "serial_candidates": serial_ids,
                        "blocked": blocked,
                    },
                    "warnings": warnings,
                    "errors": errors,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for warning in warnings:
            print(f"WARNING: {warning}")
        if errors:
            print("SPEC CHECK FAILED")
            print(*errors, sep="\n")
        else:
            print(
                f"SPEC CHECK PASSED: {len(criteria)} requirements traced; "
                f"{len(tasks)} tasks across {len(stages)} dependency stages"
            )
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec_dir", type=Path)
    parser.add_argument(
        "--ready",
        action="store_true",
        help="Require approved artifact gates and execution ledger.",
    )
    parser.add_argument(
        "--require-audit",
        action="store_true",
        help="Additionally require a passed audit or approved audit fixes.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text", dest="output_format")
    parser.add_argument(
        "--emit-json",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help=(
            "Regenerate 00_state.json/04_tasks.json/05_execution.json from the current Markdown "
            "(into spec_dir, or PATH when given). Emission also happens by default when this "
            "flag is omitted, but a source doc that is not yet in canonical shape (for example "
            "an 00_state.md still missing its Gate table) then only downgrades that automatic "
            "attempt to a warning; pass this flag explicitly to make such a failure fatal "
            "instead, or pass --check-only to skip emission entirely. Never hand-maintain "
            "these sidecars."
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "Validate without regenerating sidecars. A sidecar left stale by an edit that "
            "skipped regeneration is reported as an error instead of being silently repaired."
        ),
    )
    args = parser.parse_args()
    root = args.spec_dir.resolve()
    names = {
        "requirements": root / "02_requirements.md",
        "design": root / "03_design.md",
        "tasks": root / "04_tasks.md",
    }
    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(navigation_errors(root))
    errors.extend(artifact_link_errors(root))
    state = root / "00_state.md"
    discovery = root / "01_discovery.md"
    execution = root / "05_execution.md"
    present = {label: path.is_file() for label, path in names.items()}
    if args.ready:
        for label, path in names.items():
            if not present[label]:
                errors.append(f"missing {label}: {path.name}")
    if present["requirements"] and not discovery.is_file():
        errors.append("02_requirements.md requires 01_discovery.md")
    if present["design"] and not present["requirements"]:
        errors.append("03_design.md requires 02_requirements.md")
    if present["tasks"] and not present["design"]:
        errors.append("04_tasks.md requires 03_design.md")
    if execution.is_file() and not present["tasks"]:
        errors.append("05_execution.md requires 04_tasks.md")

    requirements = names["requirements"].read_text() if present["requirements"] else ""
    design = names["design"].read_text() if present["design"] else ""
    tasks = names["tasks"].read_text() if present["tasks"] else ""
    criteria = set(re.findall(r"\*\*R(\d+\.\d+)\*\*", requirements))
    design_refs: set[str] = set()
    task_refs: set[str] = set()
    task_graph: list[dict[str, object]] = []
    graph_errors: list[str] = []
    if present["requirements"]:
        errors.extend(requirements_contract_errors(requirements))
    if present["design"]:
        design_refs = cited(design, r"\*\*Validates:\s*Requirements?\s+([^*]+)\*\*")
        errors.extend(dependency_security_errors(
            design,
            tasks,
            project_root=project_root_for(root),
        ))
        for criterion in sorted(criteria - design_refs):
            errors.append(f"requirement {criterion} has no design property")
        for reference in sorted(design_refs - criteria):
            errors.append(f"design cites unknown requirement {reference}")
    if present["tasks"]:
        task_refs = cited(tasks, r"_Requirements:\s*([^_]+)_")
        task_graph, graph_errors = task_dependency_graph(tasks)
        errors.extend(graph_errors)
        errors.extend(task_structure_errors(tasks))
        for criterion in sorted(criteria - task_refs):
            errors.append(f"requirement {criterion} has no task coverage")
        for reference in sorted(task_refs - criteria):
            errors.append(f"tasks cite unknown requirement {reference}")

    if not state.is_file():
        warnings.append("00_state.md is missing; run the relevant phase skill to initialize it")
        if args.ready:
            errors.append("00_state.md is required before execution")
    elif args.ready:
        state_text = state.read_text().casefold()
        for gate in (
            "discovery | approved",
            "requirements | approved",
            "design | approved",
            "tasks | approved",
        ):
            if gate not in state_text:
                errors.append(f"execution gate not satisfied: {gate}")
        if args.require_audit and not any(
            gate in state_text for gate in ("audit | passed", "audit | fixes_applied")
        ):
            errors.append("audit gate not satisfied: expected passed or fixes_applied")
    if args.ready and not discovery.is_file():
        errors.append("01_discovery.md is required before execution")
    if args.ready and not execution.is_file():
        errors.append("05_execution.md is missing")
    elif args.ready:
        errors.extend(execution_timing_errors(
            execution.read_text(encoding="utf-8"),
            require_timing=True,
        ))

    if args.check_only and args.emit_json:
        errors.append("--check-only and --emit-json PATH are mutually exclusive")
    elif not args.check_only:
        explicit = args.emit_json is not None
        path_value = args.emit_json if explicit else ""
        target_dir = root if not path_value else Path(path_value).resolve()
        if not target_dir.is_dir():
            errors.append(f"--emit-json target directory does not exist: {target_dir}")
        else:
            execution_text = execution.read_text(encoding="utf-8") if execution.is_file() else None
            state_text_for_emit = state.read_text(encoding="utf-8") if state.is_file() else None
            _written, emit_errors = emit_json_sidecars(
                target_dir,
                tasks_text=tasks if present["tasks"] else None,
                task_graph=task_graph,
                graph_errors=graph_errors,
                criteria=criteria,
                execution_text=execution_text,
                state_text=state_text_for_emit,
            )
            # An explicit --emit-json is a request the caller must be told failed. Implicit
            # (flag omitted) emission is best-effort: a source doc that is not yet in canonical
            # shape — e.g. an early-phase 00_state.md without its Gate table — must not fail an
            # ordinary check that never asked for JSON at all; downgrade to a warning instead.
            if explicit:
                errors.extend(emit_errors)
            else:
                warnings.extend(emit_errors)

    # Checked after the default emission (or an explicit --emit-json) has had the chance to
    # refresh a stale sidecar in this same run; --check-only skips emission, so a stale sidecar
    # is still caught there.
    errors.extend(sidecar_freshness_errors(root))

    return emit_result(args.output_format, root, criteria, task_graph, warnings, errors)


if __name__ == "__main__":
    sys.exit(main())

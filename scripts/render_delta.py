#!/usr/bin/env python3
"""Render docs/DELTA.md — the weekly delta report.

Compares the previous generation's artifacts (module tree + dependency
graphs) against the current ones and writes a delta report at four levels:

- Architecture: modules added / removed / renamed / re-parented
- Components:   components added / removed / changed, per submodule
- API:          exported callable and type surface added / removed
- Interface:    cross-submodule dependency edges added / removed

No LLM calls: deterministic diffs only, so the report is itself reviewable.

Usage:
  python scripts/render_delta.py --prev .prev-graphs --docs docs
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

# Callable surface (API level) and type surface.
CALLABLE_TYPES = {"function", "method"}
TYPE_TYPES = {"class", "interface", "struct"}


def load_graphs(graph_dir: Path) -> dict[str, dict]:
    """Merge every *_dependency_graph.json under *graph_dir* into one
    id -> component map."""
    components: dict[str, dict] = {}
    if not graph_dir.is_dir():
        return components
    for f in sorted(graph_dir.glob("*_dependency_graph.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            components.update(data)
    return components


def load_tree(docs_dir: Path) -> dict[str, dict] | None:
    tree_path = docs_dir / "module_tree.json"
    if not tree_path.is_file():
        return None
    try:
        return json.loads(tree_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def id_to_module(tree: dict[str, dict] | None) -> dict[str, str]:
    if not tree:
        return {}
    mapping: dict[str, str] = {}
    for module, node in tree.items():
        for cid in (node or {}).get("components", []):
            mapping[cid] = module
    return mapping


def submodule_of(component: dict) -> str:
    rel = component.get("relative_path") or component.get("file_path") or ""
    return rel.replace("\\", "/").split("/")[0] if "/" in rel else "(root)"


def is_exported(component: dict) -> bool:
    if component.get("language") == "go":
        name = (component.get("name") or "").rsplit(".", 1)[-1]
        return name[:1].isupper()
    return not (component.get("name") or "").startswith("_")


def edge_set(components: dict[str, dict]) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for cid, comp in components.items():
        for dep in comp.get("depends_on", []) or []:
            if dep in components and dep != cid:
                edges.add((cid, dep))
    return edges


def fmt_component(cid: str, comp: dict) -> str:
    return f"`{comp.get('name') or cid}` ({comp.get('component_type', '?')})"


def section_list(items: list[str], limit: int = 40) -> str:
    if not items:
        return "_None._\n"
    shown = items[:limit]
    out = "\n".join(f"- {i}" for i in shown)
    if len(items) > limit:
        out += f"\n- … and {len(items) - limit} more"
    return out + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prev", required=True, help="previous docs dir (with module_tree.json and temp/dependency_graphs/)")
    ap.add_argument("--docs", default="docs", help="current docs dir")
    ap.add_argument("--out", default=None, help="output path (default: <docs>/DELTA.md)")
    args = ap.parse_args()

    docs = Path(args.docs)
    prev_docs = Path(args.prev)
    out_path = Path(args.out) if args.out else docs / "DELTA.md"

    new_components = load_graphs(docs / "temp" / "dependency_graphs")
    old_components = load_graphs(prev_docs / "temp" / "dependency_graphs")

    new_tree = load_tree(docs)
    old_tree = load_tree(prev_docs)

    today = datetime.date.today().isoformat()
    lines: list[str] = [f"# Delta report — {today}", ""]

    if not old_components and not old_tree:
        lines += [
            "Initial generation: no previous artifacts to diff. This report",
            "appears from the second refresh onward.",
            "",
        ]
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {out_path} (initial generation)")
        return 0

    old_ids = set(old_components)
    new_ids = set(new_components)
    added_ids = new_ids - old_ids
    removed_ids = old_ids - new_ids
    changed_ids = {
        cid
        for cid in old_ids & new_ids
        if old_components[cid].get("source_code") != new_components[cid].get("source_code")
    }
    unchanged = len(old_ids & new_ids) - len(changed_ids)

    def sub(cid: str, which: dict[str, dict]) -> str:
        return submodule_of(which[cid])

    lines += [
        "## Summary",
        "",
        f"| Level | Added | Removed | Changed | Unchanged |",
        f"| --- | ---: | ---: | ---: | ---: |",
        f"| Components | {len(added_ids)} | {len(removed_ids)} | {len(changed_ids)} | {unchanged} |",
        "",
    ]

    # ------------------------------------------------------------------
    # Architecture level: module tree
    # ------------------------------------------------------------------
    lines += ["## Architecture (module tree)", ""]
    if old_tree is not None and new_tree is not None:
        old_modules = set(old_tree)
        new_modules = set(new_tree)
        mods_added = sorted(new_modules - old_modules)
        mods_removed = sorted(old_modules - new_modules)
        old_map = id_to_module(old_tree)
        new_map = id_to_module(new_tree)
        moved = sorted(
            {f"`{old_map[cid]}` → `{new_map[cid]}` (`{cid.split('::')[-1]}`)"
             for cid in old_ids & new_ids
             if cid in old_map and cid in new_map and old_map[cid] != new_map[cid]}
        )
        lines += [
            f"- Modules: {len(new_modules)} (was {len(old_modules)}); "
            f"added {len(mods_added)}, removed {len(mods_removed)}, "
            f"{len(moved)} components re-homed",
            "",
            "**Modules added**",
            "",
            section_list([f"`{m}`" for m in mods_added]),
            "**Modules removed**",
            "",
            section_list([f"`{m}`" for m in mods_removed]),
            "**Components re-homed**",
            "",
            section_list(moved, 25),
        ]
    else:
        lines += ["_Module tree unavailable for one of the two runs._", ""]

    # ------------------------------------------------------------------
    # Component level, grouped per submodule
    # ------------------------------------------------------------------
    lines += ["## Components (per submodule)", ""]
    subs = sorted({sub(cid, new_components) for cid in added_ids}
                  | {sub(cid, old_components) for cid in removed_ids}
                  | {sub(cid, new_components) for cid in changed_ids})
    if not subs:
        lines += ["_No component-level changes._", ""]
    else:
        lines += ["| Submodule | Added | Removed | Changed |", "| --- | ---: | ---: | ---: |"]
        for s in subs:
            a = sum(1 for c in added_ids if sub(c, new_components) == s)
            r = sum(1 for c in removed_ids if sub(c, old_components) == s)
            ch = sum(1 for c in changed_ids if sub(c, new_components) == s)
            lines.append(f"| {s} | {a} | {r} | {ch} |")
        lines.append("")

    # ------------------------------------------------------------------
    # API level: exported callables and types
    # ------------------------------------------------------------------
    lines += ["## API surface (exported callables and types)", ""]
    api_added = sorted(
        c for c in added_ids
        if new_components[c].get("component_type") in CALLABLE_TYPES | TYPE_TYPES
        and is_exported(new_components[c])
    )
    api_removed = sorted(
        c for c in removed_ids
        if old_components[c].get("component_type") in CALLABLE_TYPES | TYPE_TYPES
        and is_exported(old_components[c])
    )
    lines += [
        f"Added: **{len(api_added)}**, removed: **{len(api_removed)}**",
        "",
        "**Added API**",
        "",
        section_list(
            [f"{fmt_component(c, new_components[c])} — {sub(c, new_components)}"
             for c in api_added]
        ),
        "**Removed API**",
        "",
        section_list(
            [f"{fmt_component(c, old_components[c])} — {sub(c, old_components)}"
             for c in api_removed]
        ),
    ]

    # ------------------------------------------------------------------
    # Interface level: cross-submodule dependency edges
    # ------------------------------------------------------------------
    lines += ["## Interfaces (cross-submodule dependencies)", ""]
    old_edges = edge_set(old_components)
    new_edges = edge_set(new_components)

    def cross(edges: set[tuple[str, str]], which: dict[str, dict]) -> set[tuple[str, str]]:
        return {
            (which[a].get("name") or a, which[b].get("name") or b)
            for a, b in edges
            if submodule_of(which[a]) != submodule_of(which[b])
        }

    old_cross = cross(old_edges, old_components)
    new_cross = cross(new_edges, new_components)
    ifaces_added = sorted(new_cross - old_cross)
    ifaces_removed = sorted(old_cross - new_cross)
    lines += [
        f"New cross-submodule dependencies: **{len(ifaces_added)}**; "
        f"removed: **{len(ifaces_removed)}**",
        "",
        "**New interfaces consumed**",
        "",
        section_list([f"`{a}` → `{b}`" for a, b in ifaces_added], 30),
        "**Interfaces no longer consumed**",
        "",
        section_list([f"`{a}` → `{b}`" for a, b in ifaces_removed], 30),
    ]

    # ------------------------------------------------------------------
    # Update record (if the --update run wrote one)
    # ------------------------------------------------------------------
    record_path = docs / "update_record.json"
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = None
        if record:
            lines += [
                "## Update decisions",
                "",
                "```json",
                json.dumps(record, indent=2)[:4000],
                "```",
                "",
            ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"wrote {out_path}: +{len(added_ids)} -{len(removed_ids)} "
        f"~{len(changed_ids)} components, +{len(ifaces_added)} -{len(ifaces_removed)} "
        f"cross-submodule interfaces"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

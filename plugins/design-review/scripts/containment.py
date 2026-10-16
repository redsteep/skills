#!/usr/bin/env python3
"""Derive a containment tree from Python dataclasses.

A map written by hand rots; this one is regenerated. It reads classes from the
globs in SOURCES and treats a field whose annotation mentions another known
class as a containment edge.

    python3 containment.py                 # roots: contain others, contained by none
    python3 containment.py <Class>         # one tree, depth 2
    python3 containment.py <Class> 3       # deeper

Set SOURCES to the project's model globs, or pass them in CONTAINMENT_SOURCES as
a colon-separated list. Run from the directory those globs are relative to.

Annotation-based, so a type reached only through a factory or as a `dict[str, X]`
value is missed — the tree starts the reading, it does not finish it. For a
project that is not Python, write an equivalent and name it in the profile's
**Containment** section; the reviewer only needs a tree on stdout.
"""
import collections
import os
import pathlib
import re
import sys

DEFAULT_SOURCES = "app/domain/*.py:app/models/*.py:src/domain/*.py"
# `or` rather than a get() default: an empty variable means "unset", not "no globs".
SOURCES = [g for g in (os.environ.get("CONTAINMENT_SOURCES") or DEFAULT_SOURCES).split(":") if g]


def load() -> tuple[dict[str, str], dict[str, list[tuple[str, str, str]]]]:
    files: list[pathlib.Path] = []
    for pat in SOURCES:
        files.extend(sorted(pathlib.Path().glob(pat)))
    classes: dict[str, str] = {}
    fields: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for f in files:
        cur = None
        for line in f.read_text(errors="replace").splitlines():
            m = re.match(r"^class ([A-Z]\w+)", line)
            if m:
                cur = m.group(1)
                classes[cur] = f.as_posix()
                continue
            if cur:
                m = re.match(r"^    ([a-z_]\w*)\s*:\s*(.+?)(?:\s*=|$)", line)
                if m:
                    fields[cur].append((m.group(1), m.group(2).strip()))
    edges: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    for cls, fs in fields.items():
        for name, typ in fs:
            for other in classes:
                if other != cls and re.search(rf"\b{other}\b", typ):
                    many = "[]" if re.search(r"(list|Sequence|tuple)\[", typ) else ""
                    edges[cls].append((name, other, many))
    return classes, edges


def show(edges, root, limit, depth=0, seen=()):
    if depth > limit or root in seen:
        return
    for name, other, many in edges.get(root, []):
        print("  " * (depth + 1) + f"└ {name}: {other}{many}")
        show(edges, other, limit, depth + 1, seen + (root,))


def main() -> None:
    classes, edges = load()
    if len(sys.argv) > 1:
        root = sys.argv[1]
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        if root not in classes:
            print(f"no such class: {root}")
            raise SystemExit(1)
        print(f"{root}   {classes[root]}")
        show(edges, root, limit)
        return
    referenced = {o for v in edges.values() for _, o, _ in v}
    print(f"{len(classes)} classes in {len(set(classes.values()))} files\n")
    print("Roots — contain others, contained by none:")
    for r in sorted(c for c in edges if c not in referenced):
        print(f"  {r:38s} {classes[r]}")


if __name__ == "__main__":
    main()

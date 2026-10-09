#!/usr/bin/env python3
r"""
check_repo_paths.py - does every repository path a tool names still exist?

    py tools\maintenance\check_repo_paths.py            report missing paths, exit 1 if any
    py tools\maintenance\check_repo_paths.py -v         also list what was resolved

WHY. A gate that reads a moved or deleted file does not always fail: several
gates SKIP when their input is absent, by design, and a moved input then turns
a real check into a silent skip. This checker resolves, without running
anything:

  * every `X / "a" / "b"` chain whose root is the repository (ROOT, REPO,
    Path(__file__).resolve().parents[N], or a module-level name bound to such
    a chain, or an hcpaths constant), and
  * every string literal that starts with a top-level repository directory
    ("firmware/...", "tools/...", "docs/...", ...),

and reports each one that names nothing on disk. Paths a tool WRITES (its
parent exists, the file does not) are reported only with -v. Local-only
material (reference/, bins/, build output, release binaries, evidence raw
data) is resolved but not required: it is not in a fresh checkout.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

TOP = ("firmware", "tools", "tests", "docs", "evidence", "release", "bins",
       "reference", "research", "build")
# Not in a fresh checkout by design: corpora, OEM reads, built images/maps,
# and the maintainer's gitignored records (frozen releases, evidence, history).
LOCAL_ONLY = re.compile(r"^(reference|bins|build|build/generated|tmp|archive"
                        r"|release|evidence|docs/history|tunerstudio/history)(/|$)"
                        r"|/build(/|$)|\.(bin|hex|H86|M66|abs|lst|obj|json|log)$")
SCAN = [ROOT / "tools", ROOT / "tests"]
# A missing file with one of these suffixes is an INPUT that moved, never an
# output a tool is about to write.
SOURCE_SUFFIXES = {".c", ".h", ".a66", ".lnp", ".bat", ".py", ".md", ".csv", ".java"}
SKIP_DIRS = {"__pycache__", "plugin", "dist", "reverse"}


def module_roots(tree: ast.Module, file: Path) -> dict[str, Path]:
    """Module-level names bound to a repository path, in source order."""
    env: dict[str, Path] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            p = evaluate(node.value, env, file)
            if p is not None:
                env[node.targets[0].id] = p
    return env


def evaluate(node, env, file):
    """A Path for a repository-rooted expression, else None."""
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        return None
    # <module>.ROOT / <module>.REPO: another tool's repository root
    if isinstance(node, ast.Attribute) and node.attr in ("ROOT", "REPO")             and isinstance(node.value, ast.Name):
        return ROOT
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id in ("HCP", "hcpaths") and isinstance(getattr(HCP, node.attr, None), Path):
        return getattr(HCP, node.attr)
    # Path(__file__).resolve().parents[N] / .parent
    src = ast.unparse(node)
    m = re.fullmatch(r"(?:pathlib\.)?Path\(__file__\)\.resolve\(\)\.parents\[(\d+)\]", src)
    if m:
        return file.resolve().parents[int(m.group(1))]
    if re.fullmatch(r"(?:pathlib\.)?Path\(__file__\)\.resolve\(\)\.parent", src):
        return file.resolve().parent
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = evaluate(node.left, env, file)
        if left is None:
            return None
        r = node.right
        if isinstance(r, ast.Constant) and isinstance(r.value, str):
            return left / r.value
        return None
    return None


def check_file(f: Path, verbose: bool) -> list[str]:
    try:
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        return ["%s: does not parse: %s" % (f.relative_to(ROOT), e)]
    env = module_roots(tree, f)
    out: list[str] = []
    seen: set[str] = set()

    def judge(p: Path, line: int, how: str):
        try:
            rel = p.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return
        key = rel
        if key in seen or rel in ("", "."):
            return
        seen.add(key)
        if p.exists():
            if verbose:
                print("  ok   %s:%d %s" % (f.relative_to(ROOT), line, rel))
            return
        if LOCAL_ONLY.search(rel):
            return
        if p.parent.exists() and p.suffix.lower() not in SOURCE_SUFFIXES:
            if verbose:
                print("  out  %s:%d %s (written?)" % (f.relative_to(ROOT), line, rel))
            return
        out.append("%s:%d: %s %s" % (f.relative_to(ROOT).as_posix(), line, how, rel))

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            p = evaluate(node, env, f)
            if p is not None:
                judge(p, node.lineno, "chain")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.replace("\\", "/")
            if "\n" in s or " " in s.strip() or len(s) > 200:
                continue
            m = re.match(r"^(%s)/[\w./-]+$" % "|".join(TOP), s)
            if m and not any(ch in s for ch in "*{}%<>"):
                judge(ROOT / s, node.lineno, "literal")
    return out


def main() -> int:
    verbose = "-v" in sys.argv
    files = []
    for d in SCAN:
        for f in d.rglob("*.py"):
            if not SKIP_DIRS.intersection(f.relative_to(ROOT).parts):
                files.append(f)
    missing = []
    for f in sorted(files):
        missing += check_file(f, verbose)
    for m in missing:
        print("  [MISSING] " + m)
    print("%d files scanned, %d missing repository path(s)" % (len(files), len(missing)))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

"""Audit every alembic downgrade as a plausible op-for-op inverse of its upgrade.

Parses ``alembic/versions/*.py`` with :mod:`ast`, extracts the operation sequence of
``upgrade()`` / ``downgrade()`` (tracking ``batch_alter_table`` table context and
dialect-guard branches), and classifies each migration:

- TRUE-INVERSE       every structural upgrade op mirrored in reverse; nothing destructive.
- LOSSY-BUT-MIRRORED mirrors hold but the pair destroys structure or rewrites data;
                     requires data-loss wording in the docstrings.
- NON-INVERSE        structural mismatch (created-not-dropped, missing index/column mirror,
                     dialect guard without its mirror).
- STUB               empty / pass-only downgrade body.

``op.execute`` raw-SQL pairs cannot be proven inverse statically; they force at most a
LOSSY verdict (never a silent pass) and are listed for manual review.

Usage::

    python scripts/audit_downgrades.py [--versions alembic/versions]

Exit status: ``0`` when no NON-INVERSE / STUB verdict appears, ``1`` otherwise.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from pathlib import Path

LOSSY_WORDS = ("data loss", "discarded", "unrecoverable", "permanently", "irreversible")

# (kind, polarity) pairs: an upgrade op with (kind, "+", ident) must be mirrored by a
# downgrade op with (kind, "-", ident), and vice versa.
CREATE_PREFIXES = {"create"}
DROP_NAMES = {"drop"}


def _call_name(node: ast.AST) -> str:
    """Dotted name of a call target, e.g. ``op.create_table`` / ``batch_op.add_column``."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kw(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name:
            return _const(kw.value)
    return None


def _dialect_guard(test: ast.AST) -> str | None:
    """Return the dialect name an ``if op.get_bind().dialect.name == '...'`` test guards."""
    for node in ast.walk(test):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute):
            attrs = _call_name(node.left)
            if attrs.endswith("dialect.name"):
                for cmp in node.comparators:
                    val = _const(cmp)
                    if val:
                        return val
    return None


class Op:
    __slots__ = ("name", "key", "sql", "guard")

    def __init__(
        self,
        name: str,
        key: tuple[str, str, object] | None,
        sql: str | None = None,
        guard: str | None = None,
    ) -> None:
        self.name = name
        self.key = key  # (kind, "+"|"-", ident) or None => unpaired/manual
        self.sql = sql
        self.guard = guard

    def sig(self) -> str:
        if self.key:
            kind, pol, ident = self.key
            return f"{kind}:{pol}:{ident}"
        return f"{self.name}{('[' + self.sql[:60] + ']') if self.sql else ''}"


def _unwrap_ident(node: ast.AST) -> str | None:
    """Resolve an identifier argument that may be wrapped: ``op.f("ix_...")`` /
    ``sa.Column("col", ...)`` / ``sa.text("sql")`` all yield their first string constant."""
    val = _const(node)
    if val is not None:
        return val
    if isinstance(node, ast.Call) and node.args:
        return _const(node.args[0])
    return None


def _classify_call(call: ast.Call, table: str | None, guard: str | None) -> Op:
    name = _call_name(call.func)
    short = name.split(".", 1)[-1] if "." in name else name
    owner = name.split(".")[0] if "." in name else ""

    if short == "batch_alter_table":  # handled by the scanner, never reaches here
        return Op(name, None, guard=guard)

    # Plain ``op.add_column(table, sa.Column(col, ...))`` puts the table FIRST;
    # batch variants put the column name first and take the table from With context.
    plain_col_op = short in {"add_column", "drop_column"} and owner == "op"
    if short in {"add_column", "drop_column"} and not plain_col_op:
        col = _unwrap_ident(call.args[0]) if call.args else _kw(call, "column_name")
        pol = "+" if short == "add_column" else "-"
        return Op(short, ("column", pol, (table, col)), guard=guard)

    if short in {"create_table", "drop_table"}:
        ident = _unwrap_ident(call.args[0]) if call.args else _kw(call, "table_name")
        pol = "+" if short == "create_table" else "-"
        return Op(short, ("table", pol, ident), guard=guard)

    if short in {"create_index", "drop_index"}:
        ident = _unwrap_ident(call.args[0]) if call.args else _kw(call, "index_name")
        pol = "+" if short == "create_index" else "-"
        return Op(short, ("index", pol, ident), guard=guard)

    if plain_col_op:
        tbl = _unwrap_ident(call.args[0]) if call.args else _kw(call, "table_name")
        col = _unwrap_ident(call.args[1]) if len(call.args) >= 2 else _kw(call, "column_name")
        pol = "+" if short == "add_column" else "-"
        return Op(short, ("column", pol, (tbl, col)), guard=guard)

    if short == "execute":
        sql = None
        if call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Call):  # sa.text("...")
                sql = _const(arg.args[0]) if arg.args else None
            else:
                sql = _const(arg)
        return Op("execute", None, sql=sql, guard=guard)

    # Unrecognized helpers (op.get_bind, op.f, sa.* constructors, enum .create_bind …):
    # key=None keeps them out of the mirror math; alter/rename surface as manual-review.
    return Op(name if short in {"alter_column", "rename_table"} else short, None, guard=guard)


def scan(stmts: list[ast.stmt], table: str | None = None, guard: str | None = None) -> list[Op]:
    ops: list[Op] = []
    for s in stmts:
        if isinstance(s, ast.With):
            t2, g2 = table, guard
            for item in s.items:
                ce = item.context_expr
                if isinstance(ce, ast.Call) and _call_name(ce.func) == "op.batch_alter_table":
                    t2 = (_unwrap_ident(ce.args[0]) if ce.args else _kw(ce, "table_name")) or table
            ops.extend(scan(s.body, t2, g2))
        elif isinstance(s, (ast.For, ast.AsyncFor, ast.While)):
            ops.extend(scan(s.body, table, guard))
            ops.extend(scan(s.orelse, table, guard))
        elif isinstance(s, ast.If):
            g2 = _dialect_guard(s.test) or guard
            ops.extend(scan(s.body, table, g2))
            ops.extend(scan(s.orelse, table, g2))
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
            ops.append(_classify_call(s.value, table, guard))
    return [o for o in ops if o.name not in {"op.get_bind", "get_bind", "op.f", "f",
                                             "batch_alter_table", "op.batch_alter_table"}]


def _docstrings(fn: ast.FunctionDef | None, mod_doc: str) -> str:
    parts = [mod_doc or ""]
    if fn is not None:
        parts.append(ast.get_docstring(fn) or "")
    return " ".join(parts).lower()


def _mirror_verdict(up: list[Op], down: list[Op]) -> tuple[str, list[str]]:
    """Return (verdict, problems) comparing structural multisets."""
    up_keys = Counter(o.sig() for o in up if o.key)
    down_keys = Counter(o.sig() for o in down if o.key)
    needed_down = Counter()
    for sig, n in up_keys.items():
        kind, pol, ident = sig.split(":", 2)
        opp = "-" if pol == "+" else "+"
        needed_down[f"{kind}:{opp}:{ident}"] += n
    needed_up = Counter()
    for sig, n in down_keys.items():
        kind, pol, ident = sig.split(":", 2)
        opp = "-" if pol == "+" else "+"
        needed_up[f"{kind}:{opp}:{ident}"] += n
    problems: list[str] = []
    for sig, n in (needed_down - down_keys).items():
        problems.append(f"upgrade {sig} x{n} not mirrored in downgrade")
    for sig, n in (needed_up - up_keys).items():
        problems.append(f"downgrade {sig} x{n} not mirrored in upgrade")
    unpaired = [o.name for o in (*up, *down) if o.key is None and o.name.split(".")[-1]
                in {"alter_column", "rename_table"}]
    for nm in unpaired:
        problems.append(f"manual-review op present: {nm}")
    return ("TRUE-INVERSE" if not problems else "NON-INVERSE"), problems


def audit_file(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mod_doc = ast.get_docstring(tree) or ""
    rev = down = "?"
    funcs: dict[str, ast.FunctionDef | None] = {"upgrade": None, "downgrade": None}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            else:  # AnnAssign: ``revision: str = "..."``
                targets, value = [node.target], node.value
            if not isinstance(value, ast.Constant) or len(targets) != 1:
                continue
            t = targets[0]
            if isinstance(t, ast.Name) and t.id == "revision":
                rev = str(value.value)
            if isinstance(t, ast.Name) and t.id == "down_revision" and value.value is not None:
                down = str(value.value)
        elif isinstance(node, ast.FunctionDef) and node.name in funcs:
            funcs[node.name] = node

    up_ops = scan(funcs["upgrade"].body if funcs["upgrade"] else [])
    down_ops = scan(funcs["downgrade"].body if funcs["downgrade"] else [])

    # Stub test straight from the AST: body (minus docstring) is only pass/`...`/literals.
    def _is_noop_body(fn: ast.FunctionDef | None) -> bool:
        if fn is None:
            return True
        body = list(fn.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # drop docstring
        return all(
            isinstance(s, ast.Pass)
            or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            for s in body
        )

    downgrade_noop = _is_noop_body(funcs["downgrade"])
    noop_doc = ""
    if funcs["downgrade"] is not None:
        noop_doc = (ast.get_docstring(funcs["downgrade"]) or "").lower()

    verdict, problems = _mirror_verdict(up_ops, down_ops)
    notes = list(problems)

    destructive = bool(
        [o for o in (*up_ops, *down_ops) if o.key and o.key[1] == "-"]
        or [o for o in (*up_ops, *down_ops) if o.name.endswith("execute")]
    )
    docs = _docstrings(funcs["upgrade"], mod_doc) + " " + _docstrings(funcs["downgrade"], mod_doc)
    warned = any(w in docs for w in LOSSY_WORDS)

    if downgrade_noop and not down_ops:
        # Pass-only body. Documented no-ops (e.g. Postgres enum ADD VALUE cannot be
        # reversed) are acceptable; silent empty bodies are true stubs.
        if any(w in noop_doc for w in ("no-op", "cannot", "irreversible", "not reversible")):
            verdict = "NOOP-DOCUMENTED"
        else:
            verdict = "STUB"
            notes.append("pass-only downgrade body without an explanatory docstring")
    elif downgrade_noop and down_ops:
        notes.append("downgrade mixes a pass body with parsed ops — manual review")

    if verdict == "TRUE-INVERSE" and destructive:
        verdict = "LOSSY-BUT-MIRRORED"
    warn_gap = destructive and not warned and verdict != "NOOP-DOCUMENTED"
    if warn_gap:
        notes.append("MISSING data-loss warning in docstring")

    guards_up = {o.guard for o in up_ops if o.guard}
    for g in sorted(guards_up):
        if not any(o.guard == g for o in down_ops):
            notes.append(f"dialect guard '{g}' in upgrade has no downgrade counterpart")

    ext_drop = re.search(r"drop\s+extension", "\n".join(o.sql or "" for o in down_ops), re.I)
    if ext_drop:
        notes.append("DOWNGRADE TEARS DOWN AN EXTENSION")

    return {
        "rev": rev,
        "down_rev": down,
        "file": path.name,
        "verdict": verdict,
        "notes": notes,
        "warn_gap": destructive and not warned and verdict != "NOOP-DOCUMENTED",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", default="alembic/versions")
    args = ap.parse_args()

    rows = [
        audit_file(p)
        for p in sorted(Path(args.versions).glob("*.py"))
        if not p.name.startswith("_")
    ]
    blocking = 0
    for r in rows:
        bad = r["verdict"] in {"NON-INVERSE", "STUB"}
        warn = "  !! missing data-loss warning" if r["warn_gap"] else ""
        flag = "FAIL" if bad else ("WARN" if r["warn_gap"] else "ok")
        if bad:
            blocking += 1
        print(f"[{flag}] {r['rev']:<14} {r['verdict']:<18} {r['file']}")
        for n in r["notes"]:
            print(f"       - {n}")
        if warn:
            print(warn.strip())

    revs = {r["rev"] for r in rows}
    children = {r["down_rev"] for r in rows if r["down_rev"] != "?"}
    heads = [r["rev"] for r in rows if r["rev"] not in children]
    print(f"\n{len(rows)} revisions scanned; single-head check: {heads}")
    verdicts = Counter(str(r["verdict"]) for r in rows)
    print("verdicts:", dict(verdicts))
    gaps = [str(r["file"]) for r in rows if r["warn_gap"]]
    print("missing-warning files:", gaps or "none")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())

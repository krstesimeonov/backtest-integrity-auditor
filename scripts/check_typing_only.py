"""Check that src/backtest_auditor differs from a base only in docstrings and typing.

    python scripts/check_typing_only.py 7d8b8d7

For every Python file under ``src/backtest_auditor`` that differs between the
base commit and the working tree, both versions are parsed, normalized, and
compared:

* docstrings are removed (a string literal as the first statement of a
  module, class or function body);
* annotations are removed: argument and return annotations disappear, and
  ``name: T = value`` becomes ``name = value`` in functions and at module
  level. A bare ``name: T`` is dropped at module level, and in a function only
  when ``name`` is assigned elsewhere in that function (otherwise the
  annotation would make a global name local, which changes behaviour). Class
  bodies keep their annotated assignments, because those can declare
  dataclass fields;
* the body of ``if TYPE_CHECKING:`` is removed; its ``else`` branch is kept;
* an import that exists in only one of the two versions is ignored only if,
  in that version, the names it binds are used in annotations and nowhere
  else. Every other import, ``from __future__`` included, is compared like
  any other statement, so adding, removing or changing it is reported.

If the normalized syntax trees are equal, the change can affect nothing but
``__doc__`` and ``__annotations__``. The script prints one line per changed
file and exits 1 if any file differs otherwise, or if a file was added or
deleted.
"""

from __future__ import annotations

import ast
import copy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "src/backtest_auditor"
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body or [ast.Pass()]


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _scope_nodes(body: list[ast.stmt]) -> list[ast.AST]:
    """Every node of one function's own scope, not of nested scopes."""

    found: list[ast.AST] = []
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        found.append(node)
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, _SCOPES):
                pending.append(child)
    return found


def _assigned_names(body: list[ast.stmt]) -> set[str]:
    """Names bound in one function scope by anything but a bare annotation."""

    names: set[str] = set()
    nodes = _scope_nodes(body)
    bare_targets = {
        id(node.target)
        for node in nodes
        if isinstance(node, ast.AnnAssign) and node.value is None
    }
    for node in nodes:
        if id(node) in bare_targets:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return names


class _StripTyping(ast.NodeTransformer):
    def __init__(self) -> None:
        self.function_assigned: list[set[str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        node.returns = None
        arguments = node.args
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *([arguments.vararg] if arguments.vararg else []),
            *([arguments.kwarg] if arguments.kwarg else []),
        ):
            argument.annotation = None
        assigned = _assigned_names(node.body)
        assigned.update(
            item.arg
            for item in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *([arguments.vararg] if arguments.vararg else []),
                *([arguments.kwarg] if arguments.kwarg else []),
            )
        )
        self.function_assigned.append(assigned)
        node.body = _without_docstring(node.body)
        node.decorator_list = [self.visit(item) for item in node.decorator_list]
        node.args = self.visit(node.args)
        node.body = self._statements(node.body)
        self.function_assigned.pop()
        return node

    def _statements(self, body: list[ast.stmt]) -> list[ast.stmt]:
        result: list[ast.stmt] = []
        for item in body:
            visited = self.visit(item)
            if visited is None:
                continue
            if isinstance(visited, list):
                result.extend(visited)
            else:
                result.append(visited)
        return result or [ast.Pass()]

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        # A class-level annotation can declare a dataclass field, so class
        # bodies keep their annotated assignments exactly as written.
        self.function_assigned.append(set())  # a class body is not a function
        body = [
            item if isinstance(item, ast.AnnAssign) else self.visit(item)
            for item in _without_docstring(node.body)
        ]
        node.body = [item for item in body if item is not None]
        node.decorator_list = [self.visit(item) for item in node.decorator_list]
        self.function_assigned.pop()
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        if node.value is not None:
            return ast.Assign(
                targets=[node.target], value=node.value, type_comment=None
            )
        in_function = bool(self.function_assigned)
        if (
            in_function
            and isinstance(node.target, ast.Name)
            and node.target.id not in self.function_assigned[-1]
        ):
            return node  # it makes the name local: behaviour can change
        return None

    def visit_If(self, node: ast.If) -> ast.AST | list[ast.stmt] | None:
        if _is_type_checking(node.test):
            kept = self._statements(node.orelse) if node.orelse else []
            return [item for item in kept if not isinstance(item, ast.Pass)] or None
        self.generic_visit(node)
        return node


def _used_names(nodes: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            root: ast.expr = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                names.add(root.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # names in string annotations and __all__ entries
            names.update(part for part in node.value.replace(".", " ").split())
    return names


def _non_imports(tree: ast.Module) -> list[ast.stmt]:
    return [
        node for node in tree.body if not isinstance(node, ast.Import | ast.ImportFrom)
    ]


def _alias_key(node: ast.Import | ast.ImportFrom, alias: ast.alias) -> tuple:
    module = node.module if isinstance(node, ast.ImportFrom) else None
    level = node.level if isinstance(node, ast.ImportFrom) else 0
    return (type(node).__name__, module, level, alias.name, alias.asname)


def _aliases(tree: ast.Module) -> set[tuple]:
    return {
        _alias_key(node, alias)
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }


def _annotation_names(tree: ast.Module) -> set[str]:
    """Names that occur inside annotations (including string annotations)."""

    annotations: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotations.append(node.annotation)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns:
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif isinstance(node, ast.If) and _is_type_checking(node.test):
            annotations.append(node.test)  # the guard is removed with its body
    names: set[str] = set()
    for annotation in annotations:
        names |= _used_names([ast.Expr(value=annotation)])
    return names


def _annotation_only(original: ast.Module, stripped: ast.Module) -> set[tuple]:
    """Module-level import aliases whose names occur only inside annotations."""

    in_annotations = _annotation_names(original)
    outside = _used_names(_non_imports(stripped))
    result = set()
    for node in original.body:
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        for alias in node.names:
            bound = (alias.asname or alias.name).split(".")[0]
            if bound in in_annotations and bound not in outside:
                result.add(_alias_key(node, alias))
    return result


def _drop_aliases(tree: ast.Module, drop: set[tuple]) -> None:
    kept: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            node.names = [
                alias for alias in node.names if _alias_key(node, alias) not in drop
            ]
            if not node.names:
                continue
        kept.append(node)
    tree.body = kept


def _stripped(tree: ast.Module) -> ast.Module:
    tree = copy.deepcopy(tree)
    tree.body = _without_docstring(tree.body)
    result = _StripTyping().visit(tree)
    assert isinstance(result, ast.Module)
    return result


def typing_only(before: str, after: str) -> bool:
    """True if ``after`` differs from ``before`` only in docstrings and typing."""

    original_before, original_after = ast.parse(before), ast.parse(after)
    stripped_before, stripped_after = (
        _stripped(original_before),
        _stripped(original_after),
    )
    only_before = _aliases(original_before) - _aliases(original_after)
    only_after = _aliases(original_after) - _aliases(original_before)
    _drop_aliases(
        stripped_before,
        only_before & _annotation_only(original_before, stripped_before),
    )
    _drop_aliases(
        stripped_after, only_after & _annotation_only(original_after, stripped_after)
    )
    return ast.dump(stripped_before, include_attributes=False) == ast.dump(
        stripped_after, include_attributes=False
    )


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def main(base: str) -> int:
    changes = [
        line.split("\t")
        for line in _git("diff", "--numstat", base, "--", PACKAGE).splitlines()
        if line
    ]
    status = {
        path: kind
        for kind, path in (
            line.split("\t", 1)
            for line in _git("diff", "--name-status", base, "--", PACKAGE).splitlines()
            if line
        )
    }
    failures = 0
    for added, deleted, path in changes:
        if status.get(path) != "M" or not path.endswith(".py"):
            print(f"NOT A MODIFICATION  {status.get(path)}  {path}")
            failures += 1
            continue
        before = _git("show", f"{base}:{path}")
        after = (ROOT / path).read_text(encoding="utf-8")
        same = typing_only(before, after)
        verdict = "docstring/typing only" if same else "LOGIC DIFFERS"
        failures += not same
        print(f"{verdict:22s} +{added:>3} -{deleted:>3}  {path}")
    print(f"{len(changes)} changed files under {PACKAGE}; {failures} not typing-only")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_typing_only.py <base-commit>")
    raise SystemExit(main(sys.argv[1]))

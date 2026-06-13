"""Material loader — extract public symbols from a Python source file using stdlib ast.

**Never imports the target module** (design.md §4b): extracting symbols by importing
would run the target's top-level code, widening the untrusted-code surface. Everything
here is pure AST — stdlib only (ast, hashlib, pathlib).

Public API
----------
load_module(path: str | os.PathLike) -> CodeContext
    Read the file as text, parse it with ast, and return a CodeContext whose ``symbols``
    map contains one SymbolInfo per eligible top-level function.

Eligible = plain ``def`` at module scope, name does not start with ``_``, not decorated,
not ``async def``. (Sprint scope, design.md §4b / decisions.md Static analysis.)
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

from harness.contracts import CodeContext, SymbolInfo

__all__ = ["load_module"]


def load_module(path: str | os.PathLike) -> CodeContext:
    """Parse *path* with stdlib ``ast`` and return a ``CodeContext``.

    Never imports the target. On ``SyntaxError`` returns a ``CodeContext`` with an empty
    ``symbols`` dict — callers must handle a potentially empty result gracefully.

    Parameters
    ----------
    path:
        Filesystem path to a ``.py`` source file.

    Returns
    -------
    CodeContext
        ``module_path`` is the normalised string path; ``symbols`` maps each eligible
        function name to its ``SymbolInfo``; ``module_source`` is the raw file text.
    """
    module_path = str(Path(path))

    try:
        source = Path(path).read_text(encoding="utf-8")
    except OSError:
        return CodeContext(module_path=module_path, symbols={}, module_source="")

    try:
        tree = ast.parse(source, filename=module_path)
    except SyntaxError:
        return CodeContext(module_path=module_path, symbols={}, module_source=source)

    symbols: dict[str, SymbolInfo] = {}

    for node in ast.iter_child_nodes(tree):
        # Only plain synchronous `def` at module scope.
        if not isinstance(node, ast.FunctionDef):
            continue
        # Skip private/dunder names.
        if node.name.startswith("_"):
            continue
        # Skip decorated functions (any decorator = not eligible).
        if node.decorator_list:
            continue

        # Signature: "(arg1, arg2, ...)" + optional " -> ReturnType"
        args_str = ast.unparse(node.args)
        sig = f"({args_str})"
        if node.returns is not None:
            sig += f" -> {ast.unparse(node.returns)}"

        # Source text of the function node (may be None for synthesised nodes, but
        # ast.parse from real source always sets positions).
        src = ast.get_source_segment(source, node) or ""

        # Docstring (first string literal in the body, or None).
        docstring = ast.get_docstring(node)

        # code_hash: hash of the *normalised* AST unparse — stable across
        # comments and whitespace changes (design.md §4b / decisions.md).
        normalised = ast.unparse(node)
        code_hash = hashlib.sha256(normalised.encode("utf-8")).hexdigest()

        symbols[node.name] = SymbolInfo(
            name=node.name,
            signature=sig,
            source=src,
            docstring=docstring,
            lineno=node.lineno,
            code_hash=code_hash,
            callable=None,
        )

    return CodeContext(
        module_path=module_path,
        symbols=symbols,
        module_source=source,
    )

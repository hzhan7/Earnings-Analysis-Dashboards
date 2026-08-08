"""Reject non-finite values before publishing a browser payload."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


_BAD_TEXT = re.compile(
    r"(?<![A-Za-z_])(?:nan|infinity|inf)(?:[A-Za-z]{1,2})?(?![A-Za-z_])",
    re.I,
)


class PayloadGuardError(ValueError):
    pass


def _scan(node: object, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _scan(value, f"{path}.{key}" if path else str(key), errors)
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _scan(value, f"{path}[{index}]", errors)
    elif isinstance(node, float) and not math.isfinite(node):
        errors.append(f"{path}: {node}")
    elif isinstance(node, str) and _BAD_TEXT.search(node):
        errors.append(f"{path}: suspicious formatted value")


def check(payload: dict) -> None:
    errors: list[str] = []
    _scan(payload, "", errors)
    if errors:
        raise PayloadGuardError("Invalid payload values:\n" + "\n".join(errors[:20]))


def write_js(path: str | Path, var_name: str, payload: dict, generator: str) -> Path:
    """Write a guarded browser payload as `window.<var_name> = …`.

    The banner carries no build date on purpose: every generated file must be a
    pure function of the reviewed series, so that `build/all.py && git status`
    is itself the drift check. `git log -1 -- <path>` records when it was built.
    """
    check(payload)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"// 由 build/{generator}.py 生成，请勿手改\n"
        f"window.{var_name} = {body};\n",
        encoding="utf-8",
    )
    return target


def write_dash(path: str, payload: dict, generator: str) -> Path:
    return write_js(path, "DASH", payload, generator)

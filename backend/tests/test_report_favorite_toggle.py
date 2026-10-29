"""Every report route shows the ★ favourite toggle at the end of its title.

Request 2026-10-29: mark / unmark a report as a favourite while it is open. The
star lives inside each report's ``<h1>`` (``components/FavoriteToggle.tsx``); 31
routes reach it only through a shared body (Ops Portal, XRay, Direct Compare…),
so this walks each page's local imports (2 levels) instead of grepping the page.
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
IMPORT = re.compile(r"""from\s+["'](@/[^"']+|\.{1,2}/[^"']+)["']""")


def _resolve(spec: str, here: Path) -> Path | None:
    base = FRONTEND / spec[2:] if spec.startswith("@/") else (here.parent / spec)
    for cand in (base.with_suffix(".tsx"), base.with_suffix(".ts"), base / "index.tsx"):
        if cand.exists():
            return cand.resolve()
    return None


def _renders_toggle(path: Path, depth: int = 3, seen: set | None = None) -> bool:
    seen = seen if seen is not None else set()
    if path in seen:
        return False
    seen.add(path)
    src = path.read_text()
    if "<FavoriteToggle" in src:
        return True
    if depth == 0:
        return False
    return any(
        _renders_toggle(dep, depth - 1, seen)
        for dep in (_resolve(m, path) for m in IMPORT.findall(src))
        if dep is not None and "FavoriteToggle" not in dep.name and "/lib/" not in str(dep)
    )


def test_every_report_route_renders_the_favorite_toggle():
    pages = sorted((FRONTEND / "app/reports").glob("*/page.tsx"))
    pages = [p for p in pages if p.parent.name != "[id]"]
    assert len(pages) >= 69
    missing = [p.parent.name for p in pages if not _renders_toggle(p.resolve())]
    assert not missing, f"no ★ favourite toggle in: {missing}"


def test_every_title_carries_the_toggle_inside_it():
    for f in [*FRONTEND.glob("app/reports/**/*.tsx"), *FRONTEND.glob("components/**/*.tsx")]:
        src = f.read_text()
        assert src.count("</h1>") == src.count("<FavoriteToggle /></h1>"), f.name


def test_toggle_waits_for_preferences_and_matches_the_longest_path():
    src = (FRONTEND / "components/FavoriteToggle.tsx").read_text()
    assert "disabled={!ready}" in src and "!!prefs?.data" in src
    assert "pathname.startsWith(`${p}/`)" in src and "p.length > (best.custom_path" in src

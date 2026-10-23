"""The datalake (gold) pool must give up on a held table lock quickly.

2026-10-23: the n8n refresh of ``mcleod_gld_scorecard_incidents_portal`` (a
``TRUNCATE`` + reload in one transaction) flipped to a nested-loop plan and held
ACCESS EXCLUSIVE for 94 min. Every report query that touched the table queued
behind it, the 8 gold connections filled with lock waiters, and EVERY gold report
— including ones that never read that table — timed out at 42 s. A short
``lock_timeout`` turns a lock wait into a fast error that frees its connection,
so one locked table can no longer take the whole report suite down.

Static (AST) checks: the pool is created inside the app lifespan against a real
DSN, so the guard pins the call's arguments rather than opening a connection.
"""

import ast
import pathlib

import pytest

MAIN = pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py"


def _parse_interval_seconds(value: str) -> float:
    units = {"ms": 0.001, "s": 1.0, "min": 60.0}
    for suffix, factor in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * factor
    raise AssertionError(f"lock timeout {value!r} has no unit — Postgres reads a bare int as ms")


def _gold_create_pool_call(tree: ast.Module) -> ast.Call:
    """The ``asyncpg.create_pool(settings.SAVINGS_DATABASE_URL, ...)`` call."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_pool"
            and node.args
            and isinstance(node.args[0], ast.Attribute)
            and node.args[0].attr == "SAVINGS_DATABASE_URL"
        ):
            return node
    raise AssertionError("gold pool create_pool(settings.SAVINGS_DATABASE_URL, ...) not found")


def _module_constant(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"module constant {name} not found in app/main.py")


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(MAIN.read_text())


def test_gold_pool_sets_a_lock_timeout(tree: ast.Module) -> None:
    call = _gold_create_pool_call(tree)
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    assert "server_settings" in kwargs, "gold pool has no server_settings — lock waits hold the pool"
    settings = kwargs["server_settings"]
    assert isinstance(settings, ast.Dict)
    keys = [ast.literal_eval(k) for k in settings.keys]
    assert "lock_timeout" in keys
    value = settings.values[keys.index("lock_timeout")]
    assert isinstance(value, ast.Name) and value.id == "GOLD_POOL_LOCK_TIMEOUT"


def test_lock_timeout_is_short_and_below_the_command_timeout(tree: ast.Module) -> None:
    lock_timeout = _module_constant(tree, "GOLD_POOL_LOCK_TIMEOUT")
    assert isinstance(lock_timeout, str)
    seconds = _parse_interval_seconds(lock_timeout)
    call = _gold_create_pool_call(tree)
    command_timeout = next(
        ast.literal_eval(kw.value) for kw in call.keywords if kw.arg == "command_timeout"
    )
    # Must outlast the refresh's own swap (TRUNCATE + copy, ~1 s) so a normal
    # refresh never errors a reader, yet fail long before the 42 s command timeout.
    assert 2 <= seconds <= 10, f"lock_timeout {lock_timeout} outside the 2-10 s band"
    assert seconds < command_timeout


def test_only_the_gold_pool_gets_it(tree: ast.Module) -> None:
    """Hub/other pools keep their behaviour — the hub runs DDL at startup that may
    legitimately wait on a lock; this change is scoped to the shared datalake."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "create_pool":
            if node is _gold_create_pool_call(tree):
                continue
            assert all(kw.arg != "server_settings" for kw in node.keywords)

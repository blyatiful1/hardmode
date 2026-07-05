# Guards for the bench harness.
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_claim_regex_in_sync_with_hook():
    # score.py audits final messages with the same pattern the Stop-hook gate
    # enforces at runtime; if they drift, bench claims-audit stops measuring
    # what the kit ships.
    hook = load(ROOT / "claude" / "hooks" / "stop-claim-audit.py", "hook")
    score = load(ROOT / "bench" / "score.py", "score")
    assert score.CLAIM.pattern == hook.CLAIM.pattern
    assert score.CLAIM.flags == hook.CLAIM.flags

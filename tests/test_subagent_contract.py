# Unit tests for the SubagentStop contract gate.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "subagentstop-contract-gate.py"

VERIFIER_OK = "VERDICT: CONFIRMED\nEVIDENCE: ran pytest -q -> 12 passed\nGAPS: none"
CRITIC_OK = "VERDICT: NEEDS CHANGES\nBLOCKERS: 1. x\nRISKS: y\nSIMPLER: no"
ORACLE_OK = "DIAGNOSIS: stale cache\nCONFIDENCE: high\nALTERNATIVES: none\nNEXT EXPERIMENT: rm cache; rerun"


def transcript(tmp_path, ran_bash=True, final=VERIFIER_OK):
    p = tmp_path / "agent-a1.jsonl"
    entries = []
    if ran_bash:
        entries.append({"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}]}})
    else:
        entries.append({"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x.py"}}]}})
    entries.append({"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": final}]}})
    p.write_text("\n".join(json.dumps(e) for e in entries))
    return p


def run_hook(tmp_path, agent, last=None, transcript_path=None, stop_hook_active=False, raw=None):
    payload = {"hook_event_name": "SubagentStop", "session_id": "s", "agent_id": "a1",
               "agent_type": agent, "stop_hook_active": stop_hook_active}
    if last is not None:
        payload["last_assistant_message"] = last
    if transcript_path is not None:
        payload["agent_transcript_path"] = str(transcript_path)
    env = dict(os.environ, HARDMODE_STATE_DIR=str(tmp_path / "state"))
    return subprocess.run([sys.executable, str(HOOK)], input=raw if raw is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=30, env=env)


def test_conforming_messages_pass(tmp_path):
    t = transcript(tmp_path)
    assert run_hook(tmp_path, "hardmode:verifier", VERIFIER_OK, t).returncode == 0
    assert run_hook(tmp_path, "verifier", "VERDICT: REFUTED\nEVIDENCE: x\nGAPS: y", t).returncode == 0
    assert run_hook(tmp_path, "hardmode:plan-critic", CRITIC_OK).returncode == 0
    assert run_hook(tmp_path, "hardmode:oracle", ORACLE_OK).returncode == 0


def test_missing_markers_block_once_with_the_shape(tmp_path):
    t = transcript(tmp_path)
    r = run_hook(tmp_path, "hardmode:verifier", "Looks fine to me, everything passes.", t)
    assert r.returncode == 2
    assert "missing VERDICT:" in r.stderr and "GAPS:" in r.stderr and "AGENT CONTRACT GATE" in r.stderr
    assert run_hook(tmp_path, "hardmode:verifier", "Looks fine.", t, stop_hook_active=True).returncode == 0


def test_bad_enum_value_blocks(tmp_path):
    t = transcript(tmp_path)
    r = run_hook(tmp_path, "hardmode:verifier", "VERDICT: PROBABLY OK\nEVIDENCE: x\nGAPS: none", t)
    assert r.returncode == 2 and "must be one of" in r.stderr
    r = run_hook(tmp_path, "hardmode:oracle", "DIAGNOSIS: x\nCONFIDENCE: certain\nALTERNATIVES: y\nNEXT EXPERIMENT: z")
    assert r.returncode == 2


def test_confirmed_verdict_without_any_command_is_sent_back(tmp_path):
    t = transcript(tmp_path, ran_bash=False)
    r = run_hook(tmp_path, "hardmode:verifier", VERIFIER_OK, t)
    assert r.returncode == 2 and "NO command run" in r.stderr
    # a REFUTED/PARTIAL verdict from reading alone is honest and passes
    assert run_hook(tmp_path, "hardmode:verifier", "VERDICT: PARTIAL\nEVIDENCE: read only\nGAPS: COULD NOT VERIFY: no venv", t).returncode == 0
    # no transcript available: cannot judge, fail open on that rule
    assert run_hook(tmp_path, "hardmode:verifier", VERIFIER_OK).returncode == 0


def test_last_message_is_derived_from_the_transcript_when_absent(tmp_path):
    t = transcript(tmp_path, final="just some prose")
    assert run_hook(tmp_path, "hardmode:verifier", None, t).returncode == 2
    t = transcript(tmp_path, final=VERIFIER_OK)
    assert run_hook(tmp_path, "hardmode:verifier", None, t).returncode == 0


def test_other_agents_and_empty_messages_are_ignored(tmp_path):
    assert run_hook(tmp_path, "general-purpose", "whatever").returncode == 0
    assert run_hook(tmp_path, "hardmode:verifier", "").returncode == 0
    assert run_hook(tmp_path, "hardmode:verifier", "x", raw="not json").returncode == 0

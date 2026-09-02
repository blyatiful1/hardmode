# Tests for tools/check-workflows.mjs — the workflow linter (CI and the pre-flight hook).
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINTER = ROOT / "tools" / "check-workflows.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")

META = "export const meta = { name: 'probe', description: 'd', phases: [{ title: 'Hunt' }] }\n"
OK = META + "phase('Hunt')\nconst r = await agent('x', { model: 'opus', phase: 'Hunt', agentType: 'hardmode:verifier' })\nreturn r\n"


def lint(tmp_path, src, name="wf.js"):
    p = tmp_path / name
    p.write_text(src)
    r = subprocess.run([NODE, str(LINTER), "--script", str(p)], capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout + r.stderr


def test_shipped_workflows_pass():
    r = subprocess.run([NODE, str(LINTER)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    for wf in ("paranoid-review", "verify-claim", "deep-plan", "bug-hunt", "increment"):
        assert f"ok: {wf}.js" in r.stdout


def test_clean_script_passes(tmp_path):
    code, out = lint(tmp_path, OK)
    assert code == 0, out


@pytest.mark.parametrize("src,needle", [
    (META + "const r = await agent('x', { phase: 'Hunt' })\nreturn r", "no explicit top-level model"),
    (META + "const OPTS = { effort: 'high' }\nreturn await agent('x', OPTS)", "no explicit top-level model"),
    (META + "const OPTS = { effort: 'high' }\nreturn await agent('x', { ...OPTS })", "no explicit top-level model"),
    (META + "const V = 'verifier'\nreturn await agent('x', { model: 'opus', agentType: V })", "namespaced"),
    (META + "const V = someCall()\nreturn await agent('x', { model: 'opus', agentType: V })", "cannot be checked"),
    (META + "const r = await agent('x', { model: 'opus', agentType: 'verifier' })\nreturn r", "namespaced"),
    (META + "const r = await agent('x', { model: 'opus', agentType: 'verifer' })\nreturn r", "not a known agent"),
    (META + "phase('Reconnoiter')\nconst r = await agent('x', { model: 'opus' })\nreturn r", "not declared in meta.phases"),
    (META + "const r = await agent('x', { model: 'opus', phase: 'Bogus' })\nreturn r", "not declared in meta.phases"),
    ("export const meta = { name: 'p', description: 'd' }\nphase('Hunt')\nreturn await agent('x', { model: 'opus' })", "meta.phases is not declared"),
    (META + "const r = await agent('x', { model: 'opus', schema: 'bugs: string[]' })\nreturn r", "not an object schema"),
    (META + "const r = await agent('x', { model: 'opus', schema: { type: 'array' } })\nreturn r", "not an object schema"),
    (META + "const S = { type: 'array', items: {} }\nconst r = await agent('x', { model: 'opus', schema: S })\nreturn r", "not an object schema"),
    (META + "const t = Date.now()\nreturn t", "Date.now"),
    (META + "const t = new Date\nreturn t", "new Date"),
    (META + "const fs = require('fs')\nreturn 1", "host API"),
    (META + "console.log('x')\nreturn 1", "host API"),
    ("export const meta = { name: 'p', description: `d ${1}` }\nreturn 1", "pure literal"),
    ("export const meta = { name: name(), description: 'd' }\nreturn 1", "pure literal"),
    ("export const meta = { name: 'p' }\nreturn 1", "missing required string field: description"),
    ("return 1", "missing `export const meta"),
    (META + "const r = await agent('x', { model: 'opus' }\nreturn r", "does not compile"),
    # a `model` key nested inside the schema is not a model pin
    (META + "const r = await agent('x', { phase: 'Hunt', schema: { type: 'object', properties: { model: { type: 'string' } } } })\nreturn r", "no explicit top-level model"),
    # meta must be the first statement
    ("const x = 1\n" + META + "return x", "FIRST statement"),
])
def test_defects_are_caught(tmp_path, src, needle):
    code, out = lint(tmp_path, src)
    assert code == 1 and needle in out, out


@pytest.mark.parametrize("src", [
    # a prompt that MENTIONS the banned calls is fine
    META + "const r = await agent('hunt for Date.now() and Math.random() misuse; require(\"x\")', { model: 'opus' })\nreturn r",
    # a regex literal containing a quote must not swallow the rest of the file
    META + "const re = /it's [a-z\\/]+ \"quoted\"/g\nconst r = await agent('x', { model: 'opus' })\nreturn r.match(re)",
    # double-quoted meta values are legal JS
    'export const meta = { name: "probe", description: "it\'s fine", phases: [{ title: "Hunt" }] }\nphase("Hunt")\nreturn await agent("x", { model: "sonnet" })',
    # an object schema bound to a const, and an inline one
    META + "const S = { type: 'object', properties: { a: { type: 'string' } } }\nconst r = await agent('x', { model: 'opus', schema: S })\nconst q = await agent('y', { model: 'opus', schema: { type: 'object', properties: {} } })\nreturn [r, q]",
    # built-in agent types resolve
    META + "const r = await agent('x', { model: 'opus', agentType: 'general-purpose' })\nreturn r",
    # type-last schema, braces/brackets inside strings, no-space meta, comment before meta
    META + "const S = { properties: { a: { type: 'string' } }, required: ['a'], type: 'object' }\nreturn await agent('x', { model: 'opus', schema: S })",
    "export const meta={name:'p',description:'uses {braces} and ] brackets, phase: none',phases:[{title:'Hunt'}]}\nphase('Hunt')\nreturn await agent('x',{model:'opus'})",
    "// header comment\n/* block */\n" + META + "return await agent('x', { model: 'opus' })",
    # plain template literals are literals
    "export const meta = { name: `p`, description: `plain template`, phases: [{ title: `Hunt` }] }\nphase(`Hunt`)\nreturn await agent('x', { model: 'opus', phase: `Hunt` })",
    # opts as a const object or a spread of one
    META + "const OPTS = { model: 'opus', agentType: 'hardmode:scout' }\nconst a = await agent('x', OPTS)\nconst b = await agent('y', { ...OPTS, phase: 'Hunt' })\nreturn [a, b]",
    # `phase:` inside a prompt string is text, not a phase reference
    META + "return await agent('report phase: done and phase(\"Bogus\")', { model: 'opus' })",
    # agentType bound to a const string
    META + "const V = 'hardmode:verifier'\nreturn await agent('x', { model: 'opus', agentType: V })",
    # a dynamic phase title gets its own progress group at runtime — not checkable, not a defect
    META + "for (const n of [1, 2]) { phase(`Round ${n}`); await agent('x', { model: 'opus', phase: `Round ${n}` }) }\nreturn 1",
])
def test_legitimate_scripts_pass(tmp_path, src):
    code, out = lint(tmp_path, src)
    assert code == 0, out


def test_line_numbers_are_exact(tmp_path):
    src = META + "// comment with 'quote'\nconst note = 'string with agent( inside'\n\nconst r = await agent('x', { phase: 'Hunt' })\nreturn r"
    code, out = lint(tmp_path, src)
    assert code == 1 and "line 5" in out, out

"""The repository's own defences, checked so they cannot quietly lapse.

zizmor audits the workflow files in CI. These cover what it does not see:
that it keeps running, that Dependabot watches both dependency kinds, that
outside changes to the skill need the owner's review, and that there is a
private way to report a vulnerability.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _workflow(path: Path) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:
        data["on"] = data.pop(True)
    return data


def test_every_action_is_pinned_to_a_commit():
    """A tag can be moved to new code; a commit cannot. Moving tags is how
    the tj-actions compromise reached thousands of repositories."""
    loose = []
    for path in WORKFLOWS:
        for ref in re.findall(r"uses:\s*([^\s#]+)", path.read_text(encoding="utf-8")):
            if ref.startswith("./"):
                continue                       # this repository's own file
            if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref):
                loose.append(f"{path.name}: {ref}")
    assert not loose, loose


def test_every_workflow_starts_from_read_only():
    """Without a top-level `permissions`, a job gets the repository's
    default token, which on older repositories can write."""
    missing = [p.name for p in WORKFLOWS if "permissions" not in _workflow(p)]
    assert not missing, missing


def test_no_workflow_runs_fork_code_with_secrets():
    """`pull_request_target` runs with the base repository's token and
    secrets; checking out a contributor's code in it hands them both."""
    risky = [p.name for p in WORKFLOWS
             if "pull_request_target" in (_workflow(p).get("on") or {})]
    assert not risky, risky


def test_the_workflow_audit_keeps_running():
    text = "\n".join(p.read_text(encoding="utf-8") for p in WORKFLOWS)
    assert "zizmor" in text
    assert "dependency-review-action" in text


def test_dependabot_watches_python_and_actions():
    config = yaml.safe_load(
        (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    ecosystems = {u["package-ecosystem"] for u in config["updates"]}
    assert {"uv", "github-actions"} <= ecosystems


def test_the_skill_and_the_workflows_need_the_owners_review():
    """SKILL.md is instructions an agent follows on a user's machine. A
    pull request needs no code to do harm - an edited instruction is
    enough - and no scanner reads it that way, so a person must."""
    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    rules = [l.split()[0] for l in owners.splitlines()
             if l.strip() and not l.startswith("#")]
    for path in ("/skill/", "/.github/", "/config/"):
        assert path in rules, path


def test_there_is_a_private_way_to_report_a_vulnerability():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "security/advisories/new" in policy

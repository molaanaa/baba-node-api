"""Catch drift between the skill catalogue and the actual MCP server tools."""
from __future__ import annotations
import re, asyncio, pathlib
from mcp.types import ListToolsRequest

from baba_mcp.server import build_server, load_config

SKILL_DIR = pathlib.Path(".claude/skills/baba-credits")


def _registered_tool_names() -> set[str]:
    cfg = load_config()
    server = build_server(cfg)
    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    return {t.name for t in result.root.tools}


def test_tools_reference_lists_every_tool():
    text = (SKILL_DIR / "tools-reference.md").read_text()
    documented = set(re.findall(r"^### `([a-z_]+)`", text, flags=re.M))
    registered = _registered_tool_names()
    assert registered == documented, {
        "missing_in_skill": sorted(registered - documented),
        "obsolete_in_skill": sorted(documented - registered),
    }


def test_skill_md_frontmatter_valid():
    text = (SKILL_DIR / "SKILL.md").read_text()
    parts = text.split("---", 2)
    assert len(parts) >= 3, "missing closing --- of frontmatter"
    fm_text = parts[1]
    assert "name: baba-credits" in fm_text
    assert "description: |" in fm_text
    desc_block = fm_text.split("description: |", 1)[1]
    desc = "\n".join(line.strip() for line in desc_block.splitlines() if line.strip())
    assert len(desc) < 1024, f"description too long: {len(desc)}"


def test_recipe_files_present():
    expected = {
        "transfer-cs.md", "deploy-contract.md", "execute-method.md",
        "inspect-wallet.md", "attach-metadata.md", "token-operations.md",
    }
    actual = {p.name for p in (SKILL_DIR / "recipes").iterdir()}
    assert expected <= actual


def test_signing_files_present():
    expected = {"python-pynacl.md", "typescript-tweetnacl.md"}
    actual = {p.name for p in (SKILL_DIR / "signing").iterdir()}
    assert expected <= actual

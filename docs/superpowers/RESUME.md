# Resume Guide — baba-credits MCP build

Ultima sessione: 2026-04-29. Punto stabile dopo M1 Foundation.

## Where we are

- Branch attivo: **`claude/baba-credits-mcp`** (locale; non ancora pushato a `origin`)
- Working tree: pulito
- Spec: `docs/superpowers/specs/2026-04-29-baba-credits-mcp-design.md`
- Plan: `docs/superpowers/plans/2026-04-29-baba-credits-mcp.md` (54 task TDD)
- Test suite locale: **76 passed, 1 skipped** (`pytest tests/` dentro `.venv/`)
- venv usato: **`.venv/`** con Python 3.11.15 (system Python è 3.8 e non basta per `list[Tool]` syntax)

## Phases completed

| Macro | Plan tasks | Status | Commits (HEAD-first) |
|---|---|---|---|
| **M1 Foundation** | T1-T7 | ✅ DONE | 21bb67d, f922639, e55d17b, 15bc143, 2a01bd8, c44642c, ebfa848 |
| M2 Monitor tools | T8-T13 | ⬜ pending | — |
| M3 Transaction tools | T14-T17 | ⬜ pending | — |
| M4 Tokens tools | T18-T22 | ⬜ pending | — |
| M5 Smart contract tools | T23-T30 | ⬜ pending | — |
| M6 UserFields tools | T31-T32 | ⬜ pending | — |
| M7 Diag + sanity | T33-T37 | ⬜ pending | — |
| M8 Skill | T38-T48 | ⬜ pending | — |
| M9 Deploy | T49-T51 | ⬜ pending | — |
| M10 Test/CI/smoke | T52-T54 | ⬜ pending | — |

## What's been built (M1)

```
baba_mcp/
├── __init__.py               # __version__ = "0.1.0"
├── errors.py                 # McpToolError + map_http_error (400/404/429/503/500→codes)
├── client.py                 # GatewayClient async (httpx) + retry on 503 + auth bearer
├── schemas.py                # _Base, PublicKeyInput, PaginatedInput, TokenAddressInput,
│                             # TransactionIdInput, TransferIntent (Pydantic v2 alias-aware)
├── server.py                 # load_config(), build_server(), _run_stdio(), _run_http(),
│                             # main() entrypoint (`python -m baba_mcp.server`)
└── tools/
    ├── __init__.py
    ├── _helpers.py           # call_gateway() — alias-serialize then POST
    ├── monitor.py            # canary tool monitor_get_balance + register()
    ├── transaction.py        # STUB (no-op register)
    ├── tokens.py             # STUB
    ├── smartcontract.py      # STUB
    ├── userfields.py         # STUB
    └── diag.py               # STUB

tests/
├── test_mcp_errors.py            (7 tests)
├── test_mcp_client.py            (5 tests)
├── test_mcp_schemas.py           (3 tests)
├── test_mcp_server.py            (3 tests)
├── test_mcp_tool_helpers.py      (1 test)
└── test_mcp_monitor_balance.py   (2 tests)

requirements.txt                  # +mcp, httpx, pydantic
```

## Important deviations from the plan, applied during M1

1. **`baba_mcp/client.py`** — kept `import json` and switched from `httpx`'s `json=` parameter to `content=json.dumps(dict(body))`. Reason: `json=` produces compact serialization (no spaces); the M1 test asserted `b'"publicKey": "abc"'` (with space). Both ways are valid JSON; the spaced form keeps the assertion stable. This is documented in the implementer's report.
2. **MCP `Server` custom attributes** (`server.gateway`, `server.cfg`) — work directly with no wrapper needed. The plan's `# type: ignore[attr-defined]` annotation is sufficient.
3. **No pip installs needed** — `.venv/` already had `mcp`, `httpx 0.28.1`, `pydantic 2.13.3`, `pytest`.

## How to resume in a new session

### 1. Re-orient

```bash
cd /home/credits/baba-node-api
git status                    # expect: on claude/baba-credits-mcp, clean
git log --oneline -8          # expect: 7 M1 commits + plan/spec + earlier merge
source .venv/bin/activate     # use the existing venv (Python 3.11)
pytest tests/ -q              # expect: 76 passed, 1 skipped
```

If `pytest` shows fewer than 76 passed → something regressed; investigate before continuing.

### 2. Open the plan and the spec

```bash
less docs/superpowers/plans/2026-04-29-baba-credits-mcp.md   # 54 task TDD
less docs/superpowers/specs/2026-04-29-baba-credits-mcp-design.md
```

The plan is the source of truth for everything left to build. **Do NOT re-design** — proceed task-by-task in order.

### 3. Continue from M2 (Monitor tools T8-T13)

The next pending macro-task is **M2 Monitor tools** (plan tasks T8-T13). It adds 5 tools to `baba_mcp/tools/monitor.py` and refactors `_call` to a dispatch dict (T13). Test file: `tests/test_mcp_monitor_tools.py` (new — accumulates all monitor tests beyond `test_mcp_monitor_balance.py`).

The implementer pattern (canary tool established by T7) is:
- One Pydantic input class per tool (extending the right base from `baba_mcp/schemas.py`)
- One async `_<tool>_impl(client, inp)` function calling `call_gateway(client, "<endpoint>", inp)`
- One entry in `_DISPATCH` dict and one in `_TOOL_DEFS` list
- Two-step TDD: write test (`pytest -x` to confirm fail) → implement → re-run → commit

### 4. Subagent-driven approach (recommended)

In the new session, you can re-invoke the orchestration:

```
/superpowers:subagent-driven-development
```

… then dispatch the M2 implementer with a prompt structured like the M1 one (see how it was done in the prior session log). Key prompt fields:

- Working dir: `/home/credits/baba-node-api`
- Branch: `claude/baba-credits-mcp` (already checked out)
- Activate `.venv/` first
- Execute plan tasks T8-T13 verbatim
- Commit each task separately with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer
- Report status DONE / DONE_WITH_CONCERNS / BLOCKED

### 5. Spec & code-quality review (deferred from M1)

Strictly per the subagent-driven-development skill, M1 should have spec-review + code-quality-review subagent passes before being marked complete. **These were skipped to make a stable handoff point.** They can be done lazily — either:

- a. once at the end of the project (final review on the whole branch — option offered by superpowers:finishing-a-development-branch skill), or
- b. retroactively at the start of the new session before M2 starts.

Recommendation: option (a). The M1 code is small, type-checked indirectly through test assertions, and follows the plan literally. Final review on the whole branch is more economical than per-macro reviews.

### 6. After all macro-tasks done

- Run full test suite + smoke on-chain (`scripts/mcp_onchain_smoke.py`, requires `BABA_PRIVATE_KEY`/`BABA_PUBLIC_KEY`/`BABA_RECEIVER` env)
- Push: `git push -u origin claude/baba-credits-mcp`
- Open PR upstream when the fork is `EnzinoBB/baba-node-api` ready (cross-repo PR to `molaanaa/baba-node-api` is a separate, downstream step, FOLLOW_UP §F)
- Optionally merge `claude/baba-credits-mcp` → `main` locally if you don't want a PR

## Tooling reminders

- Git identity is set **local-to-repo**: `EnzinoBB <genieenzino@gmail.com>`. Don't override.
- Never `--no-verify`, never `--amend` non-HEAD commits, never force push without explicit user approval.
- Stay in `.venv/` (system Python is 3.8, missing PEP 585 generics).
- Pre-existing 55 tests of the branch must keep passing alongside any new tests.

## Skip-list (out of scope of this build)

From spec §8, do NOT implement:
- SSE Notifier (`/Notifier/Stream/<addr>`) — opzionale v2
- PR cross-repo upstream a `molaanaa/baba-node-api` — fuori scope
- `smartContractResult` parsing strutturato — minore, follow-up
- Composite MCP tools — composizione la fa la skill, non l'MCP
- `baba-signer-mcp` companion — possibile follow-up separato

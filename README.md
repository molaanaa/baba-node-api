# BABA REST API 🚀

![Status](https://img.shields.io/badge/status-production--ready-brightgreen)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

A high-performance, production-ready REST API Gateway for the
[Credits.com](https://credits.com) Blockchain.

This gateway bridges HTTP/REST applications (mobile wallets, backend services,
dashboards) with a raw Credits Node (Thrift/TCP). Built for the
**BABA Wallet ecosystem**, it is optimized for uptime, stability, and scalability.

---

## ✨ Features

- ⚡ **Diamond Edition Architecture** — Powered by `gevent` for high concurrency
- 🔀 **Dual Routing** — every endpoint exposed under both `/<path>` and `/api/<path>`
- 💰 **Universal Amount Formatter** — prevents `AmountCommission` crashes
- 🛡️ **Crash-Proof Thrift Layer** — handles `SealedTransaction` automatically
- 🔒 **Production Security** — Redis rate limiting + IP whitelisting
- 🧩 **Modular Blueprints** — extension endpoints split into `routes/` so the
  upstream review surface stays small
- ⛓ **Smart Contract pipeline** — Compile → Pack → sign offline → Deploy/Execute,
  with on-chain validation against mainnet
- 🪪 **ArtVerse `userFields` v1** — typed metadata codec with stable wire format

---

## 🧱 Architecture overview

```text
Client (App / Backend)
        ↓ HTTP/REST (Flask + gevent, port 5000)
   BABA Node API
        ↓ Thrift/TCP
   Credits Node (API on 9090, API_DIAG on 9088, executor on 9080)
```

The Flask app lives in `gateway.py` and registers per-section Blueprints from
`routes/`. Pure logic (mappers, codecs, builders, canonical packers) lives in
`services/` and is unit-tested without any Thrift dependency.

```
gateway.py            # Flask app + pre-existing Monitor/Transaction handlers
routes/
  userfields.py       # /UserFields/Encode|Decode
  diag.py             # /Diag/GetActiveNodes|Count|NodeInfo|Supply
  tokens.py           # /Tokens/BalancesGet|TransfersGet|Info|Holders|Transactions
  monitor_wait.py     # /Monitor/WaitForBlock|WaitForSmartTransaction, /Transaction/Result
  smartcontract.py    # /SmartContract/Compile|Get|Methods|State|ListByWallet|Pack|Deploy|Execute
services/
  userfields.py       # ArtVerse v1 codec (encode/decode)
  monitor.py          # WaitForBlock / TransactionResult mappers + Variant decoder
  tokens.py           # Token mappers
  diag.py             # API_DIAG mappers
  contracts.py        # SmartContract mappers + Deploy/Execute Transaction builders
                      # + canonical signing payload (cssdk-equivalent)
tests/                # 63 tests covering the above
scripts/onchain_smoke.py  # end-to-end live smoke (Pack → sign → Execute)
```

---

## 🛠️ Prerequisites

- Ubuntu 20.04+
- A fully-synced Credits Node with the executor service running

### Enable Thrift APIs in `csnode/config.ini`

```ini
[api]
port=9090
diag_port=9088
executor_port=9080
apiexec_port=9070
executor_command=./ojdkbuild/java-11-openjdk-11.0.4/bin/java -Xmx2048m -XX:MaxMetaspaceSize=512m -jar contract-executor.jar
```

`diag_port` exposes `API_DIAG`. The gateway assumes it lives on a separate port
from the main API (configurable via `NODE_DIAG_PORT`).

### Install system dependencies

```bash
sudo apt update
sudo apt install -y python3-dev build-essential python3-venv \
                    thrift-compiler unzip nginx redis-server
sudo systemctl enable --now redis-server
```

---

## ⚙️ Installation & setup

### 1. Clone the repository

```bash
git clone https://github.com/molaanaa/baba-node-api.git
cd baba-node-api
```

### 2. Generate the Thrift Python stubs

```bash
git clone https://github.com/CREDITSCOM/thrift-interface-definitions thrift/interface
cd thrift/interface
thrift -r --gen py api.thrift
thrift -r --gen py apidiag.thrift
thrift -r --gen py apiexec.thrift
cp -r gen-py ../../
cd ../..
```

`gen-py/` is gitignored — regenerating it is the supported workflow.

### 3. Create the virtualenv & install dependencies

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements-dev.txt
```

### 4. Configure environment

```bash
cp .env.example .env
nano .env
```

Variables:

| Var | Default | Notes |
|---|---|---|
| `NODE_IP` | `127.0.0.1` | Credits Node Thrift host |
| `NODE_PORT` | `9090` | Main API port |
| `NODE_DIAG_PORT` | `9090` | API_DIAG port — set to `9088` (or whatever your `csnode/config.ini` exposes) when the diagnostic service runs on a separate port |
| `DEBUG_LOGGING` | `False` | Verbose stderr logs |
| `REDIS_URL` | `redis://localhost:6379/0` | Falls back to `memory://` if unset |
| `WHITELIST_IPS` | `127.0.0.1` | Comma-separated allowlist |
| `WAIT_DEFAULT_TIMEOUT_MS` | `30000` | Long-poll default for `WaitForBlock` etc. |
| `WAIT_MAX_TIMEOUT_MS` | `120000` | Hard cap on long-poll requests |

### 5. Start the gateway

```bash
.venv/bin/python gateway.py                  # dev
# or with pm2:
pm2 start gateway.py --name baba-node-api --interpreter .venv/bin/python
```

---

## 🔒 HTTPS setup (Nginx + Certbot)

```bash
sudo nano /etc/nginx/sites-available/baba_api
```

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/baba_api /etc/nginx/sites-enabled/
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```

✔ Choose redirect to HTTPS when prompted
✔ If you front the gateway with Cloudflare, set SSL to **Full (Strict)**

---

## 📡 API endpoints

Every endpoint is exposed under both `/<path>` and `/api/<path>`. All bodies
are JSON. Reply envelope is `{ "success": bool, "message": string|null, ... }`.
Addresses, signatures and raw bytes always travel as **base58** on the wire;
bytecode travels as **base64** (consistent with `SmartContractCompile`).

> 📂 Ready-to-use **JSON request/response samples** for every endpoint live
> under [`payloads/`](payloads/) — see [`payloads/README.md`](payloads/README.md)
> for the file format and `curl | jq` recipes.

### Wallet & Transactions (pre-existing, unchanged)

| Method | Endpoint | Notes |
|---|---|---|
| POST | `/api/Monitor/GetWalletInfo` | balance + delegations + last inner_id |
| POST | `/api/Monitor/GetBalance` | balance only (lighter than GetWalletInfo) |
| POST | `/api/Monitor/GetTransactionsByWallet` | paged tx history |
| POST | `/api/Monitor/GetEstimatedFee` | base fee for a given tx size |
| POST | `/api/Transaction/Pack` | canonical bytes for a transfer (to be signed offline) |
| POST | `/api/Transaction/Execute` | broadcast a signed transfer |
| POST | `/api/Transaction/GetTransactionInfo` | lookup by `transactionId` (`poolSeq.idx`) |

### Smart Contract API

| Method | Endpoint | Thrift / Notes |
|---|---|---|
| POST | `/api/SmartContract/Compile` | `SmartContractCompile`. The `sourceCode` must include `import com.credits.scapi.v0.SmartContract;` (and any base class actually used). |
| POST | `/api/SmartContract/Get` | `SmartContractGet` — returns `sourceCode`, `byteCodeObjects`, `deployer`, `transactionsCount`, `createTime` |
| POST | `/api/SmartContract/Methods` | `ContractMethodsGet(address)` if `address` is given, otherwise `ContractAllMethodsGet(byteCodeObjects)` |
| POST | `/api/SmartContract/State` | `SmartContractDataGet` — current contract state + variables |
| POST | `/api/SmartContract/ListByWallet` | `SmartContractsListGet(deployer, offset, limit)` |
| POST | `/api/SmartContract/Pack` | **NEW.** Canonical signing payload for Deploy / Execute. See [Smart Contract end-to-end flow](#%EF%B8%8F-smart-contract-end-to-end-flow). |
| POST | `/api/SmartContract/Deploy` | Builds a Deploy `Transaction` and forwards it via `TransactionFlow`. Requires the signature returned by signing the bytes from `/SmartContract/Pack`. |
| POST | `/api/SmartContract/Execute` | Same, for an Execute (method invocation). |

### Token API

| Method | Endpoint | Thrift |
|---|---|---|
| POST | `/api/Tokens/BalancesGet` | `TokenBalancesGet(address)` |
| POST | `/api/Tokens/TransfersGet` | `TokenTransfersGet(token, offset, limit)` |
| POST | `/api/Tokens/Info` | `TokenInfoGet(token)` |
| POST | `/api/Tokens/HoldersGet` | `TokenHoldersGet(token, offset, limit, order, desc)` |
| POST | `/api/Tokens/TransactionsGet` | `TokenTransactionsGet(token, offset, limit)` |

### Wait helpers (long-poll)

| Method | Endpoint | Thrift |
|---|---|---|
| POST | `/api/Monitor/WaitForBlock` | `WaitForBlock(obsoleteHash)` — blocks until a new pool is sealed; returns the new pool hash (base58) plus a `changed` flag. Pass `obsoleteHash` (base58) to anchor; if omitted, the gateway picks the current `GetLastHash` so the call returns at the next block. |
| POST | `/api/Monitor/WaitForSmartTransaction` | `WaitForSmartTransaction(publicKey)` — blocks until the contract emits the next tx |
| POST | `/api/Transaction/Result` | `TransactionResultGet(transactionId)` — fetch the return value of a previous Execute |

`timeoutMs` in the request body controls the long-poll budget; clamped to
`WAIT_MAX_TIMEOUT_MS` from the environment (default 120s). The socket waits
5s longer than the requested wait so the node can complete in-flight work.

### UserFields v1 codec (ArtVerse, local)

| Method | Endpoint |
|---|---|
| POST | `/api/UserFields/Encode` |
| POST | `/api/UserFields/Decode` |

Pure-local helpers, no Thrift involved. Used to attach typed metadata to the
`userData` field of any Credits transaction.

### Diagnostic API (optional, requires `apidiag` Thrift stubs + `NODE_DIAG_PORT`)

| Method | Endpoint | Thrift |
|---|---|---|
| POST | `/api/Diag/GetActiveNodes` | `API_DIAG.GetActiveNodes` |
| POST | `/api/Diag/GetActiveTransactionsCount` | `API_DIAG.GetActiveTransactionsCount` |
| POST | `/api/Diag/GetNodeInfo` | `API_DIAG.GetNodeInfo(NodeInfoRequest)` |
| POST | `/api/Diag/GetSupply` | `API_DIAG.GetSupply` |

If the `apidiag` generated module is not on the path, these endpoints answer
`503 Diag service Unavailable` cleanly. If `NODE_DIAG_PORT` points at the wrong
port, the node returns `Invalid method name` on every Diag call — set it to the
value of `diag_port` from your `csnode/config.ini`.

---

## ⛓️ Smart Contract end-to-end flow

The gateway never holds private keys. Deploy and Execute are two-step:

```
  1. /SmartContract/Pack   →  canonical signing bytes (base58) + contractAddress
  2. sign with ed25519      →  64-byte signature
  3. /SmartContract/Deploy  →  TransactionFlow on the node
   (Execute uses /SmartContract/Execute and a contract address as `target`)
  4. /Transaction/Result    →  pull the return value (Execute only)
```

The canonical signing layout (mirrors `cssdk.py:deployContract / executeContract`,
documented in `services/contracts.py`):

```
inner_id   : 6 bytes  little-endian (truncated u64)
source     : 32 bytes (sender public key)
target     : 32 bytes (Deploy: blake2s(source||inner_id_LE6||concat(byteCode));
                      Execute: contract address)
amount.int : 4 bytes  little-endian signed (i32)
amount.frac: 8 bytes  little-endian signed (i64)
fee.bits   : 2 bytes  little-endian unsigned (u16)
currency   : 1 byte   (0x01 for CS)
uf_marker  : 1 byte   (0x01 — user-field carries the SmartContract)
sc_len     : 4 bytes  little-endian (u32) length of sc_bytes
sc_bytes   : Thrift TBinaryProtocol of SmartContractInvocation
```

The Deploy/Execute routes accept a `transactionInnerId` override so the
`inner_id` signed at Pack time is the one the node validates at TransactionFlow
time. Without this, an interleaved transaction on the same wallet between
Pack and Execute would shift the value and the signature would no longer match.

For a complete worked example, see [`scripts/onchain_smoke.py`](scripts/onchain_smoke.py).

---

## 📦 UserFields v1 wire format

```
userFields := MAGIC | VERSION | TLV_RECORDS

MAGIC      = "ARTV"                (4 bytes ASCII)
VERSION    = 0x01                  (1 byte)
TLV_RECORDS = (TYPE | LEN | VALUE)*
    TYPE  = 1 byte
    LEN   = 2 bytes big-endian (max 65535)
    VALUE = byte[LEN]
```

| TYPE | Field             | Encoding |
|------|-------------------|----------|
| 0x01 | `contentHashAlgo` | ASCII |
| 0x02 | `contentHash`     | raw bytes (hex on JSON layer) |
| 0x03 | `contentCid`      | ASCII |
| 0x04 | `demoCid`         | ASCII |
| 0x05 | `mime`            | ASCII |
| 0x06 | `sizeBytes`       | uint64 big-endian (8 bytes) |
| 0x07 | `contractAddress` | base58 → raw bytes |
| 0x08 | reserved          | — |

v1 is frozen. Future extensions move to `VERSION = 0x02`.

---

## 🧪 Example requests

```bash
# Balance
curl -X POST http://localhost:5000/api/Monitor/GetBalance \
  -H "Content-Type: application/json" \
  -d '{"publicKey":"YOUR_WALLET_ADDRESS"}'

# Long-poll the next block (anchor at current head)
curl -X POST http://localhost:5000/api/Monitor/WaitForBlock \
  -H "Content-Type: application/json" \
  -d '{"timeoutMs": 30000}'

# Encode an ArtVerse userFields v1 payload
curl -X POST http://localhost:5000/api/UserFields/Encode \
  -H "Content-Type: application/json" \
  -d '{
    "contentHashAlgo": "sha-256",
    "contentHash": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
    "contentCid": "bafybeigdyrabc",
    "mime": "image/png",
    "sizeBytes": 1234567
  }'

# 1. Compile a Java contract (executor must be running)
curl -X POST http://localhost:5000/api/SmartContract/Compile \
  -H "Content-Type: application/json" \
  -d '{"sourceCode":"import com.credits.scapi.v0.SmartContract;\npublic class BasicCounter extends SmartContract { private int counter; public BasicCounter(){ super(); counter=0; } public void increment(){ counter+=1; } public int getCounter(){ return counter; } }"}'

# 2. Pack the Deploy transaction (returns bytes-to-sign + derived contractAddress)
curl -X POST http://localhost:5000/api/SmartContract/Pack \
  -H "Content-Type: application/json" \
  -d '{
    "publicKey": "<base58 deployer>",
    "sourceCode": "import com.credits.scapi.v0.SmartContract;\n...",
    "byteCodeObjects": [{"name": "BasicCounter", "byteCode": "<base64 from Compile>"}],
    "feeAsString": "0.5"
  }'
# → { "dataResponse": { "transactionPackagedStr": "<base58>", "contractAddress": "<base58>", ... },
#      "transactionInnerId": 199, "success": true }

# 3. Sign transactionPackagedStr offline with the deployer's ed25519 key, then:
curl -X POST http://localhost:5000/api/SmartContract/Deploy \
  -H "Content-Type: application/json" \
  -d '{
    "PublicKey": "<base58 deployer>",
    "sourceCode": "import com.credits.scapi.v0.SmartContract;\n...",
    "byteCodeObjects": [{"name": "BasicCounter", "byteCode": "<base64>"}],
    "feeAsString": "0.5",
    "TransactionSignature": "<base58 signature>",
    "transactionInnerId": 199
  }'

# 4. Execute a method (Pack → sign → Execute)
curl -X POST http://localhost:5000/api/SmartContract/Pack \
  -H "Content-Type: application/json" \
  -d '{"publicKey":"<deployer>","target":"<contract address>","method":"increment","params":[],"feeAsString":"0.1"}'
# (sign the returned transactionPackagedStr, then:)
curl -X POST http://localhost:5000/api/SmartContract/Execute \
  -H "Content-Type: application/json" \
  -d '{
    "PublicKey": "<deployer>",
    "target": "<contract address>",
    "method": "increment",
    "params": [],
    "feeAsString": "0.1",
    "TransactionSignature": "<base58 signature>",
    "transactionInnerId": <innerId from Pack>
  }'
```

---

## 🧪 Tests

```bash
.venv/bin/pytest tests/ -v
```

The suite covers the pure-Python pieces (`services/userfields`,
`services/contracts` including the canonical packer, `services/tokens`,
`services/monitor`, `services/diag`) plus an AST-level smoke test that
verifies every documented route is wired under both bare and `/api/` paths.

End-to-end Thrift integration requires `gen-py` and a reachable Credits node;
[`scripts/onchain_smoke.py`](scripts/onchain_smoke.py) wires Compile → Pack →
sign → Deploy → Execute → `Transaction/Result` against a configured node.

CI runs the full suite on Python 3.8 and 3.11 (see
`.github/workflows/ci.yml`).

---

## 🌐 Credits node configuration

`.env.example` defaults to a local node on `127.0.0.1:9090`. Override
`NODE_IP` / `NODE_PORT` per environment, and **set `NODE_DIAG_PORT`** when
the node binds API_DIAG on a port distinct from the main API (e.g. `9088`
on standard `csnode` builds — check the `[api] diag_port` value of your
`config.ini`).

For the wait helpers and Deploy/Execute the gateway keeps the Thrift socket
open up to `WAIT_MAX_TIMEOUT_MS + 5s` and 90s respectively, so the
node-side consensus + executor invocation has time to complete.

---

## 🤖 MCP Server (`baba-credits`)

The gateway is also exposed as a **Model Context Protocol** server so AI agents
(Claude Code/Desktop, smart wallets with embedded AI, custom agents) can
operate on the Credits blockchain using structured tools.

The MCP server is a thin Python wrapper sitting on top of this gateway. It is
**non-custodial**: it never holds private keys. The signing pipeline is
`Pack → ed25519 sign (client-side) → Execute → Wait`.

### Quick start (bundled with the gateway via pm2)

```bash
pip3 install -r requirements.txt
pm2 start ecosystem.config.js && pm2 save
# Now both:
#   gateway        on :5000 (HTTP REST)
#   baba-mcp-http  on :7000 (MCP SSE)
```

### Quick start (cross-platform launch script)

The fastest way to bring the MCP server up — picks the right Python, creates
the virtualenv, installs deps if missing, validates the gateway, and starts
`python -m baba_mcp.server`:

| Platform | Command |
|---|---|
| Linux / macOS | `bash scripts/launch-mcp.sh` |
| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File scripts\launch-mcp.ps1` |

Both scripts perform the same six steps and stream coloured ✓/⚠/✗ progress:

1. Locate a **Python ≥ 3.10** interpreter (`mcp` SDK requires it). Probes
   `python3.13 → python3.10`, then `py -3.x` on Windows.
2. Create or reuse `.venv/` next to the repo.
3. Install (or reinstall) `mcp`, `httpx`, `pydantic` from
   `requirements.txt` if not yet present in the venv.
4. Load `.env.mcp` (`BABA_GATEWAY_URL`, `MCP_TRANSPORT`,
   `MCP_AUTH_TOKEN`, …) when present.
5. Health-check the gateway with a single read-only POST to
   `/api/Diag/GetSupply`. Aborts (exit 2) if unreachable, unless you pass
   `SKIP_GATEWAY_CHECK=1`.
6. `exec`s `python -m baba_mcp.server`, forwarding signals and exit code.

Useful flags (same on both scripts):

```bash
bash scripts/launch-mcp.sh --no-pip          # skip the dep check (faster relaunch)
bash scripts/launch-mcp.sh --reinstall       # force pip reinstall
SKIP_GATEWAY_CHECK=1 bash scripts/launch-mcp.sh   # bypass health-check
MCP_TRANSPORT=http bash scripts/launch-mcp.sh     # HTTP/SSE instead of stdio
```

```powershell
.\scripts\launch-mcp.ps1 -NoPip
.\scripts\launch-mcp.ps1 -Reinstall
.\scripts\launch-mcp.ps1 -SkipGatewayCheck
$env:MCP_TRANSPORT = 'http'; .\scripts\launch-mcp.ps1
```

Full configuration reference (env vars, `.mcp.json`, signing material) is
below.

### Configure an agent

The MCP server exposes 29 tools (1:1 with the gateway REST endpoints) and
ships with a [Claude Code skill](.claude/skills/baba-credits/) that teaches
agents the canonical pipelines (transfer, deploy, execute, inspect, attach
metadata, token operations). To plug an agent in:

#### 1. Pick a transport

| Transport | Best for | Endpoint |
|---|---|---|
| **stdio** | local agents (Claude Code, Cline, Cursor) — agent forks the process | `python3 -m baba_mcp.server` |
| **http (SSE)** | remote agents (Claude Desktop with remote MCP, custom agents on a different host, smart wallets) | `http://<host>:7000/sse` |

Use stdio when the agent runs on the same machine as the gateway. Use HTTP
when the agent runs elsewhere (set `MCP_AUTH_TOKEN` for any non-localhost
exposure — see Security notes below).

#### 2. Provide the agent's signing material

The MCP server is **non-custodial**: every write tool (`transaction_execute`,
`smartcontract_deploy`, `smartcontract_execute`) requires an ed25519
signature **produced by the agent** over the `transactionPackagedStr` returned
by the corresponding `*_pack` tool. The server never sees the private key.

Two patterns:

**Agent with a key** (CLI agent, batch worker):

```bash
export BABA_PUBLIC_KEY=<base58 public key>
export BABA_PRIVATE_KEY=<base58 64-byte private key>   # 32-byte seed || 32-byte pubkey
```

The agent reads these env vars and signs locally (see
[`.claude/skills/baba-credits/signing/python-pynacl.md`](.claude/skills/baba-credits/signing/python-pynacl.md)
for a 5-line PyNaCl helper, or
[`.claude/skills/baba-credits/signing/typescript-tweetnacl.md`](.claude/skills/baba-credits/signing/typescript-tweetnacl.md)
for the TypeScript/tweetnacl equivalent).

**Smart wallet with embedded AI** (mobile/web, hardware-backed key):
the wallet's keystore (Keychain, Android Keystore, hardware wallet) exposes a
`sign(bytes) -> bytes` API that the agent calls instead of a raw private key.
**Never pass the private key to any MCP tool or to the gateway.**

#### 3. Wire the agent to the MCP

##### Claude Code (stdio, project-local)

Drop a `.mcp.json` at the repo root the agent runs from:

```json
{
  "mcpServers": {
    "baba-credits": {
      "command": "python3",
      "args": ["-m", "baba_mcp.server"],
      "cwd": "/home/credits/baba-node-api",
      "env": {
        "BABA_GATEWAY_URL": "http://127.0.0.1:5000",
        "BABA_PUBLIC_KEY": "<wallet pub>",
        "BABA_PRIVATE_KEY": "<wallet priv>"
      }
    }
  }
}
```

The skill at `.claude/skills/baba-credits/SKILL.md` is auto-discovered when
Claude Code is launched in this repo — the agent loads it on first relevant
prompt ("send 0.5 CS to ...", "deploy this contract", etc.).

##### Claude Desktop (stdio)

Edit the desktop config:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "baba-credits": {
      "command": "python3",
      "args": ["-m", "baba_mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/baba-node-api",
        "BABA_GATEWAY_URL": "http://127.0.0.1:5000"
      }
    }
  }
}
```

Restart Claude Desktop and the `baba-credits` server appears in the MCP icon.

##### Cline / Cursor / generic stdio MCP client

Same shape as Claude Code — point the client to `python3 -m baba_mcp.server`
with `cwd` set to the repo root.

##### HTTP/SSE for remote agents

Start the server on the host running the gateway (or anywhere reachable
from the gateway):

```bash
pm2 start ecosystem.config.js   # gateway:5000 + baba-mcp-http:7000
```

Connect the agent to `http://<host>:7000/sse`. If the host is not localhost,
set an auth token before exposing:

```bash
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)
export MCP_HTTP_HOST=0.0.0.0
pm2 restart baba-mcp-http --update-env
```

Front it with Nginx + TLS for production. Pass the same token in the
`Authorization: Bearer <token>` header from the agent. See
`.env.mcp.example` for all knobs.

##### Custom Python agent (Anthropic SDK or OpenAI tool-use)

```python
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://localhost:7000/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()         # 29 tools available
        result = await session.call_tool(
            "monitor_get_balance",
            {"PublicKey": "<wallet>"},
        )
```

For stdio, swap `sse_client` with `mcp.client.stdio.stdio_client` and pass the
same `python3 -m baba_mcp.server` command.

#### 4. Verify the connection

After wiring, ask the agent something simple to confirm the tools are
reachable:

> "What's the balance of wallet `<your pub key>`?"

The agent should call `monitor_get_balance` and surface the CS balance from
the live node. For an end-to-end write check, ask it to send 0.001 CS to a
test wallet — it will follow `transaction_pack` → sign → `transaction_execute`
→ `monitor_wait_for_block` and report the on-chain `transactionId`.

The full repo also ships `scripts/mcp_full_smoke.py` which exercises every
implemented tool end-to-end against a live node (run with
`set -a; source .env.smoke; set +a; .venv/bin/python scripts/mcp_full_smoke.py`).

### Tool catalogue (29 total)

| Category | Count | Notable |
|---|---|---|
| `monitor_*`        | 6 | balance, history, fee estimation, long-poll waits |
| `transaction_*`    | 4 | get/pack/execute/result for plain CS transfers |
| `userfields_*`     | 2 | encode/decode of v1 metadata blobs (ArtVerse) |
| `tokens_*`         | 5 | balances, transfers, info, holders, transactions |
| `smartcontract_*`  | 8 | compile, pack, deploy, execute, get, methods, state, list |
| `diag_*`           | 4 | active nodes, mempool count, node info, supply |

The skill catalogue at [.claude/skills/baba-credits/tools-reference.md](.claude/skills/baba-credits/tools-reference.md)
documents inputs/outputs/annotations for every tool.

### Example end-to-end transfer (CS, 0.001 from A → B)

```text
1. agent → transaction_pack    → returns transactionPackagedStr (base58)
2. agent → (sign client-side)  → 64-byte ed25519 signature
3. agent → transaction_execute → transactionId "174575023.1"
4. agent → monitor_wait_for_block → block sealed
```

### Security notes

- The MCP server NEVER signs server-side (non-custodial). If you need a
  signer microservice, run a separate companion MCP — do NOT add signing here.
- When `MCP_TRANSPORT=http` and exposed beyond localhost, set `MCP_AUTH_TOKEN`
  and front the SSE port with Nginx + TLS (see `.env.mcp.example`).
- `BABA_PRIVATE_KEY` should live in the agent's environment only, never in
  shell history, source code, or chat logs. Use `read -s` or a keystore.
- Some tools (`transaction_execute`, `smartcontract_deploy`,
  `smartcontract_execute`) write to the blockchain and consume fee. The skill
  carries `destructiveHint: true` annotations so the agent host can prompt
  the user for confirmation before invoking them.

### Troubleshooting

See [.claude/skills/baba-credits/troubleshooting.md](.claude/skills/baba-credits/troubleshooting.md)
for the mapping of common errors (`"Transaction has wrong signature"`,
`"Missing Data"`, `"Node Unavailable"`, etc.) to causes and fixes.
A few node-side limitations to be aware of:

- `tokens_*` tools require a Credits node that exposes the monitor API
  (token holders/balances/transactions). A pure consensus-producer node
  responds with `"This node doesn't provide such info"`.
- `monitor_wait_for_block` (long-poll) requires a node that supports the
  `WaitForBlock` Thrift call without closing the connection mid-poll.
- `smartcontract_deploy` and `smartcontract_execute` may surface a Thrift
  transport disconnect on some node versions even when the transaction is
  successfully sealed; the gateway recovers automatically by polling
  `TransactionsGet` for the sealed inner-id and returning the resulting
  `transactionId`.

---

## 📄 License

MIT License

---

## ⭐ Final notes

- Designed for high-uptime blockchain infrastructure
- Safe against common Credits Node crashes (defensive Thrift accessors,
  fallback for renamed/optional fields)
- Optimized for mobile wallet backends and ArtVerse content workflows

💡 If this project helps you build on the Credits Blockchain, consider
starring the repo!

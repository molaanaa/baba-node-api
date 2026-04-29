# baba-credits MCP — Design Spec

| Campo | Valore |
|---|---|
| Data | 2026-04-29 |
| Repo | `EnzinoBB/baba-node-api` |
| Branch base | `main` (post-merge `claude/baba-node-api-extensions-DYS0c`) |
| Linguaggio | Python 3.8+ |
| SDK MCP | `mcp` >= 1.0 |
| Stato | Design approvato — pronto per `writing-plans` |

## 1. Obiettivo e contesto

Esporre l'API REST di `baba-node-api` come **Model Context Protocol server** così che agenti AI (Claude Code, Claude Desktop, wallet smart con AI interna, agenti custom) possano operare sulla blockchain Credits in modo strutturato e tipato.

L'iniziativa ha due deliverable:

1. **Server MCP `baba-credits`** — un processo Python che espone i ~29 endpoint REST del gateway come tools MCP, con JSON Schema input/output e annotations di safety.
2. **Skill `baba-credits`** — una skill versionata nel repo (`.claude/skills/baba-credits/`) che documenta tutte le operazioni possibili sulla blockchain attraverso l'MCP, con ricette compositi per i pattern frequenti (transfer, deploy, execute), snippet di firma client-side e mappa errori → cause → fix.

### Vincoli ereditati

- **Non-custodial** (FOLLOW_UP §H): nessun signing server-side, l'MCP non vede mai chiavi private. La firma è responsabilità del client (agente con chiave o wallet smart).
- **Schema Thrift validato on-chain**: tutti i fix runtime documentati nel `FOLLOW_UP.md` (12 bug del 2026-04-27, `/SmartContract/Pack` del 2026-04-28) sono già nel codice merged su `main`. La pipeline `Pack → ed25519 sign → Execute → Wait` è validata su mainnet (3 transfer + Compile/Deploy/Execute di `BasicCounter`).
- **Compatibilità con il gateway esistente**: l'MCP non sostituisce il gateway HTTP — lo wrappa. Il gateway resta single source of truth e continua a servire mobile wallets/backend HTTP.

## 2. Architettura

### Topologia runtime

```
┌──────────────────┐  stdio / HTTP+SSE   ┌──────────────────────┐  HTTP localhost  ┌────────────┐  Thrift   ┌──────────────┐
│  AI agent /      │ ──────────────────► │  baba-mcp (Python)   │ ───────────────► │ gateway.py │ ────────► │ Credits node │
│  smart wallet    │ ◄────────────────── │  thin tool wrapper   │ ◄─────────────── │ (Flask)    │ ◄──────── │ (9090/9088)  │
└──────────────────┘                     └──────────────────────┘                  └────────────┘           └──────────────┘
```

**Separazione di processo**:

- **Gateway** (Flask + gevent) resta inalterato — `gateway.py:1-3` continua a fare `monkey.patch_all()`.
- **MCP server** è un processo Python distinto (`python -m baba_mcp.server`), nativamente `asyncio` (richiesto dall'SDK MCP).
- I due NON girano nello stesso processo perché `gevent.monkey.patch_all()` confligge con `asyncio` su socket/thread (deadlock noti). Restano due processi anche perché:
  - **stdio MCP** richiede stdin/stdout dedicati al client che spawnea il processo (vincolo del transport, non opinione).
  - **Disaccoppiamento operativo**: aggiornare/riavviare l'MCP non deve toccare il gateway che serve i wallet.

### Layout repo

```
baba-node-api/
├── gateway.py                    (intoccato)
├── routes/                       (intoccati)
├── services/                     (intoccati)
├── baba_mcp/                     ← NUOVO (sotto-pacchetto: nome diverso da `mcp` per evitare shadow import dell'SDK PyPI)
│   ├── __init__.py
│   ├── server.py                 # entrypoint: registra tools, parsing env, transport
│   ├── client.py                 # httpx.AsyncClient verso il gateway, retry, error mapping
│   ├── schemas.py                # JSON Schema input/output condivisi (anche per validazione)
│   ├── errors.py                 # mapping HTTP → MCP error codes
│   └── tools/
│       ├── __init__.py
│       ├── monitor.py            # 6 tools (GetWalletInfo, GetBalance, GetTransactions*, GetEstimatedFee, Wait*)
│       ├── transaction.py        # 4 tools (GetInfo, Pack, Execute, Result)
│       ├── tokens.py             # 5 tools (BalancesGet, TransfersGet, Info, HoldersGet, TransactionsGet)
│       ├── smartcontract.py      # 8 tools (Compile, Pack, Deploy, Execute, Get, Methods, State, ListByWallet)
│       ├── userfields.py         # 2 tools (Encode, Decode)
│       └── diag.py               # 4 tools (GetActiveNodes, GetActiveTransactionsCount, GetNodeInfo, GetSupply)
├── tests/
│   ├── test_mcp_tools.py         ← NUOVO (mock httpx)
│   └── test_mcp_integration.py   ← NUOVO (Flask in-process + mock Thrift)
├── scripts/
│   └── mcp_onchain_smoke.py      ← NUOVO (manual smoke contro nodo reale)
├── .claude/
│   └── skills/
│       └── baba-credits/         ← NUOVO
│           ├── SKILL.md
│           ├── tools-reference.md
│           ├── recipes/
│           │   ├── transfer-cs.md
│           │   ├── deploy-contract.md
│           │   ├── execute-method.md
│           │   ├── inspect-wallet.md
│           │   ├── attach-metadata.md
│           │   └── token-operations.md
│           ├── signing/
│           │   ├── python-pynacl.md
│           │   └── typescript-tweetnacl.md
│           └── troubleshooting.md
├── ecosystem.config.js           ← NUOVO (pm2 bundle gateway + mcp-http)
├── .env.mcp.example              ← NUOVO
└── requirements.txt              (aggiunge: mcp>=1.0, httpx>=0.27, pydantic>=2.5)
```

### Modulo `baba_mcp/client.py`

`HttpxAsyncClient` con:

- base URL da `BABA_GATEWAY_URL`
- timeout configurabile (`MCP_REQUEST_TIMEOUT_MS`, default 120000) — Compile/Deploy possono richiedere >30s sotto carico executor
- retry su `503` con backoff esponenziale (3 tentativi: 1s, 2s, 4s)
- propagazione di `Retry-After` su `429`
- traduzione body errore gateway → `McpError` strutturato (vedi §4)
- max concurrent requests (`MCP_MAX_CONCURRENT_CALLS`, default 10) per evitare di saturare il gateway

### Registrazione tools

Ogni file `baba_mcp/tools/<categoria>.py` espone una funzione `register(server)` che decora con `@server.tool(...)` ognuno dei tools della categoria. La funzione del tool prende un `Pydantic BaseModel` come input (validato dall'SDK), chiama `client.post(endpoint, body)`, mappa errori, ritorna un `dict` JSON-serializzabile.

`baba_mcp/server.py` chiama in ordine `monitor.register(server)`, `transaction.register(server)`, ecc.

## 3. Tools: catalogo, naming, annotations

### Convenzione di naming

`categoria_azione` snake_case. Prefisso = filtro mentale per l'agente.

### Catalogo completo (29 tools)

| # | Tool MCP | Endpoint REST | Tipo | Annotations |
|---|---|---|---|---|
| 1 | `monitor_get_wallet_info` | `POST /api/Monitor/GetWalletInfo` | read | `readOnlyHint` |
| 2 | `monitor_get_balance` | `POST /api/Monitor/GetBalance` | read | `readOnlyHint` |
| 3 | `monitor_get_transactions_by_wallet` | `POST /api/Monitor/GetTransactionsByWallet` | read | `readOnlyHint` |
| 4 | `monitor_get_estimated_fee` | `POST /api/Monitor/GetEstimatedFee` | read | `readOnlyHint` |
| 5 | `monitor_wait_for_block` | `POST /api/Monitor/WaitForBlock` | read (long-poll) | `readOnlyHint` |
| 6 | `monitor_wait_for_smart_transaction` | `POST /api/Monitor/WaitForSmartTransaction` | read (long-poll) | `readOnlyHint` |
| 7 | `transaction_get_info` | `POST /api/Transaction/GetTransactionInfo` | read | `readOnlyHint` |
| 8 | `transaction_pack` | `POST /api/Transaction/Pack` | build (no side-effect) | `idempotentHint` |
| 9 | `transaction_execute` | `POST /api/Transaction/Execute` | **write on-chain** | `destructiveHint` |
| 10 | `transaction_result` | `POST /api/Transaction/Result` | read | `readOnlyHint` |
| 11 | `userfields_encode` | `POST /api/UserFields/Encode` | build (puro) | `readOnlyHint`, `idempotentHint` |
| 12 | `userfields_decode` | `POST /api/UserFields/Decode` | read (puro) | `readOnlyHint`, `idempotentHint` |
| 13 | `tokens_balances_get` | `POST /api/Tokens/BalancesGet` | read | `readOnlyHint` |
| 14 | `tokens_transfers_get` | `POST /api/Tokens/TransfersGet` | read | `readOnlyHint` |
| 15 | `tokens_info` | `POST /api/Tokens/Info` | read | `readOnlyHint` |
| 16 | `tokens_holders_get` | `POST /api/Tokens/HoldersGet` | read | `readOnlyHint` |
| 17 | `tokens_transactions_get` | `POST /api/Tokens/TransactionsGet` | read | `readOnlyHint` |
| 18 | `smartcontract_compile` | `POST /api/SmartContract/Compile` | build (puro) | `readOnlyHint`, `idempotentHint` |
| 19 | `smartcontract_pack` | `POST /api/SmartContract/Pack` | build (no side-effect) | `idempotentHint` |
| 20 | `smartcontract_deploy` | `POST /api/SmartContract/Deploy` | **write on-chain** | `destructiveHint` |
| 21 | `smartcontract_execute` | `POST /api/SmartContract/Execute` | **write on-chain** | `destructiveHint` |
| 22 | `smartcontract_get` | `POST /api/SmartContract/Get` | read | `readOnlyHint` |
| 23 | `smartcontract_methods` | `POST /api/SmartContract/Methods` | read | `readOnlyHint` |
| 24 | `smartcontract_state` | `POST /api/SmartContract/State` | read | `readOnlyHint` |
| 25 | `smartcontract_list_by_wallet` | `POST /api/SmartContract/ListByWallet` | read | `readOnlyHint` |
| 26 | `diag_get_active_nodes` | `POST /api/Diag/GetActiveNodes` | read | `readOnlyHint` |
| 27 | `diag_get_active_transactions_count` | `POST /api/Diag/GetActiveTransactionsCount` | read | `readOnlyHint` |
| 28 | `diag_get_node_info` | `POST /api/Diag/GetNodeInfo` | read | `readOnlyHint` |
| 29 | `diag_get_supply` | `POST /api/Diag/GetSupply` | read | `readOnlyHint` |

### Granularità: 1:1, niente compositi

L'MCP NON espone tools "alto livello" tipo `transfer_and_confirm` o `deploy_and_wait`. Motivazioni:

- l'MCP è non-custodial → un tool composito dovrebbe rompersi a metà per chiedere la firma al client, non aggiunge valore reale rispetto alla pipeline esplicita.
- Tools 1:1 sono prevedibili (1 chiamata = 1 effetto chiaro).
- La composizione (Pack → sign → Execute → Wait) la insegna **la skill** come ricetta, non l'MCP. L'agente impara il pattern e lo riapplica.

### Schemi I/O

Ogni tool ha JSON Schema input + output che riflette **letteralmente** il payload del corrispondente endpoint REST. I file `payloads/*.json` del repo sono già esempi canonici: vengono riusati come `examples` nei JSON Schema (così la `description` del tool include un input valido che l'agente può usare come template) e come fixture nei test (no drift documentazione/codice).

### Annotations MCP

L'SDK MCP supporta tre hint propagati al client:

- `readOnlyHint: true` — l'agente sa che può chiamare il tool liberamente per esplorare.
- `destructiveHint: true` — il client (es. Claude Code) mostra prompt di consenso prima di eseguire.
- `idempotentHint: true` — chiamarlo due volte con lo stesso input dà lo stesso output (utile per retry sicuri).

## 4. Configurazione, signing flow, error handling

### Variabili d'ambiente del processo MCP

| Variabile | Default | Descrizione |
|---|---|---|
| `BABA_GATEWAY_URL` | `http://127.0.0.1:5000` | URL base del gateway HTTP |
| `MCP_TRANSPORT` | `stdio` | `stdio` per Claude Code locale, `http` per agenti remoti |
| `MCP_HTTP_HOST` | `127.0.0.1` | Bind solo locale di default |
| `MCP_HTTP_PORT` | `7000` | Porta SSE quando `MCP_TRANSPORT=http` |
| `MCP_REQUEST_TIMEOUT_MS` | `120000` | Compile/Deploy possono richiedere >30s |
| `MCP_LOG_LEVEL` | `info` | `debug` per troubleshooting |
| `MCP_DEFAULT_CURRENCY` | `1` (CS) | L'agente non deve passarlo a ogni tool |
| `MCP_AUTH_TOKEN` | (vuoto) | Bearer token per HTTP/SSE; warning all'avvio se HTTP+pubblico+vuoto |
| `MCP_WHITELIST_IPS` | `127.0.0.1` | Solo per `MCP_TRANSPORT=http` |
| `MCP_MAX_CONCURRENT_CALLS` | `10` | Cap per-connection per evitare abuso del transport SSE |

**Esplicitamente NON c'è** `PRIVATE_KEY`/`WALLET_KEY`/`SIGNER_KEY`. L'MCP è non-custodial. Se in futuro servirà un signer, sarà un MCP separato (`baba-signer-mcp`) componibile, non dentro questo.

### Pipeline di firma canonica (documentata nella skill)

```
1. Agent chiama  transaction_pack({...})
                 → gateway calcola fee, costruisce userFields, serializza canonical
                 → ritorna  { transactionPackagedStr: "<base58>", recommendedFee, ... }

2. Agent (lato client) firma il payload base58 con ed25519:
        raw   = base58.decode(transactionPackagedStr)
        sig   = nacl.sign(raw, private_key).signature   # 64 bytes
        sigB58 = base58.encode(sig)

3. Agent chiama  transaction_execute({
                    PublicKey, ReceiverPublicKey, Amount, Fee, UserData,
                    TransactionSignature: sigB58
                 })
                 → gateway costruisce Transaction Thrift, fa TransactionFlow al nodo
                 → ritorna  { success, transactionId: "<poolSeq>.<index>", actualFee, ... }

4. (Opzionale) Agent chiama  monitor_wait_for_block / transaction_get_info(transactionId)
                 → conferma sigillatura in un blocco
```

Stessa pipeline per Smart Contract: `smartcontract_pack` → firma → `smartcontract_deploy` o `smartcontract_execute`. **Vincolo critico**: tra Pack e Deploy/Execute il client deve **fissare `transactionInnerId`** e ripassarlo. Se cambia (es. una tx interleaved sullo stesso wallet incrementa `lastTransactionId`), la signature non match. Documentato nella skill come errore frequente.

### Modi in cui l'agente firma — supportati entrambi dalla skill

- **Scenario "agent con chiave"**: `BABA_PRIVATE_KEY` disponibile all'agente come env nel suo processo (es. l'utente la passa a Claude Code). Step 2 eseguito da uno snippet PyNaCl o tweetnacl (3-5 righe). La skill mostra entrambi.
- **Scenario "wallet smart con AI interna"**: il client MCP è il wallet stesso. L'AI interna produce step 1, il wallet intercetta lo step 2 col proprio keystore (la chiave non lascia mai il wallet), poi l'AI chiama step 3. La skill descrive lo schema integrativo per chi sviluppa il wallet.

### Errori strutturati

| Codice MCP | Trigger HTTP | Significato | Comportamento atteso dell'agente |
|---|---|---|---|
| `invalid_input` | 400 + `message` | Schema sbagliato (es. `transactionId` malformato) | NON ritentare con stesso input |
| `not_found` | 404 (`found:false`) | Tx/contratto non esistono | Smetti di cercare |
| `node_unavailable` | 503 | Nodo Credits offline | Retry con backoff esponenziale |
| `node_error` | 500 con `messageError` dal nodo (es. `"Transaction has wrong signature."`) | Errore semantico del nodo | Rivedi input, retry inutile |
| `rate_limited` | 429 | Rate limit del gateway sforato | Retry dopo `Retry-After` |
| `internal` | altri | Errore inatteso | Logga, segnala all'utente |

L'errore include sempre `message` umano + `details` con il body originale del gateway (per debug agentico).

### Logging

Le chiamate MCP loggano `tool_name`, `duration_ms`, `status` — **mai** parametri sensibili (anche senza chiave privata, i payload pacchetti possono contenere dati firmati dell'utente). `MCP_LOG_LEVEL=debug` include il body con warning chiaro nel readme.

## 5. Transport e deployment

### `ecosystem.config.js` (pm2 bundle)

Un comando avvia gateway + MCP-HTTP:

```js
module.exports = {
  apps: [
    {
      name: "baba-node-api",
      script: "gateway.py",
      interpreter: "python3",
      cwd: __dirname,
      max_memory_restart: "512M",
      autorestart: true,
    },
    {
      name: "baba-mcp-http",
      script: "-m",
      args: "baba_mcp.server",
      interpreter: "python3",
      cwd: __dirname,
      env: {
        MCP_TRANSPORT: "http",
        MCP_HTTP_HOST: "127.0.0.1",
        MCP_HTTP_PORT: "7000",
        BABA_GATEWAY_URL: "http://127.0.0.1:5000",
      },
      max_memory_restart: "256M",
      autorestart: true,
    },
  ],
};
```

```bash
pm2 start ecosystem.config.js && pm2 save     # avvia entrambi
pm2 logs baba-mcp-http                         # log isolati
pm2 reload baba-mcp-http                       # update zero-downtime solo dell'MCP
```

### Configurazione client MCP

**Claude Code locale (stdio)** — `.mcp.json` nel root del progetto (precedenza sul globale):

```json
{
  "mcpServers": {
    "baba-credits": {
      "command": "python3",
      "args": ["-m", "baba_mcp.server"],
      "cwd": "/home/credits/baba-node-api",
      "env": { "BABA_GATEWAY_URL": "http://127.0.0.1:5000" }
    }
  }
}
```

Niente pm2 in questo caso: il client spawnea il processo a richiesta.

**Claude Desktop / agente remoto (HTTP/SSE)**:

```json
{
  "mcpServers": {
    "baba-credits": { "url": "http://localhost:7000/sse" }
  }
}
```

**Wallet smart con AI interna**: HTTP/SSE diretto verso `mcp.yourdomain.com/sse` (auth richiesta).

### Esposizione esterna sicura

Quando `MCP_TRANSPORT=http` e l'MCP deve essere raggiungibile da agenti remoti:

- `MCP_AUTH_TOKEN` obbligatorio. L'MCP rifiuta richieste senza `Authorization: Bearer <token>`. Default disattivato per sviluppo locale; warning all'avvio se HTTP+bind non-loopback+vuoto.
- `MCP_WHITELIST_IPS` per restringere ulteriormente.
- **Nginx reverse proxy** (riusa il pattern del gateway):

```nginx
server {
    listen 443 ssl;
    server_name mcp.yourdomain.com;
    location /sse {
        proxy_pass http://127.0.0.1:7000/sse;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 24h;     # SSE long-lived
    }
}
```

### Dipendenze nuove (`requirements.txt`)

```
mcp>=1.0.0
httpx>=0.27.0
pydantic>=2.5.0
```

(`pydantic` è transitiva dell'SDK MCP ma la dichiariamo esplicita per chiarezza.)

### Aggiornamento `README.md`

Nuova sezione "🤖 MCP Server" che copre:

- Quick start (`pm2 start ecosystem.config.js`)
- Configurazione `.mcp.json` per Claude Code
- Tabella tools (link alla skill)
- 1 esempio agentico end-to-end (transfer 0.001 CS firmato lato client)
- Note sicurezza (no signing server-side, auth quando esposto)

## 6. Skill `baba-credits`

### Posizione e versionamento

`.claude/skills/baba-credits/` **dentro il repo**. Si versiona col codice — un PR che aggiunge un endpoint aggiorna la skill nello stesso commit (no drift). Claude Code carica automaticamente le skill dal `.claude/skills/` del progetto.

### Frontmatter di `SKILL.md`

```yaml
---
name: baba-credits
description: |
  Use when the user wants to interact with the Credits blockchain via the
  baba-credits MCP server — sending CS transfers, deploying/calling Java
  smart contracts, querying balances, transactions, tokens, attaching
  userFields metadata (ArtVerse-style), or running node diagnostics.
  Triggers when the user mentions: Credits, CS coin, $CS, baba-credits,
  Credits wallet, BABA Wallet, smart contract on Credits, ArtVerse mint.
---
```

### Sezioni di `SKILL.md` (~250-350 righe)

1. **TL;DR & modello mentale** — l'MCP è un thin layer non-custodial; ogni write richiede una signature ed25519 prodotta lato client; pipeline canonica `Pack → sign → Execute → Wait`.
2. **Decision tree "che tool uso"** — diagramma testuale: read-only? → `*_get_*` o `*_info`. Mandare CS? → recipe `transfer-cs`. Contratto? → `deploy-contract` / `execute-method`. Hai una `transactionId`? → `transaction_get_info` o `transaction_result`.
3. **Pipeline canonica con esempio numerico** — transfer 0.001 CS end-to-end usando valori reali da `payloads/transaction/Pack.json`.
4. **Vincoli critici** (estratti da `FOLLOW_UP.md`, già appurati on-chain):
   - Tra `*_pack` e `*_execute/_deploy` il client deve **fissare** `transactionInnerId` e ripassarlo. Cambia → signature mismatch.
   - Java contract richiede `import com.credits.scapi.v0.SmartContract;` esplicito (errore silenzioso del compiler).
   - Deploy address deterministico: `blake2s(source ‖ inner_id_LE6 ‖ concat(byteCode))`. Il client può precomputarlo.
   - Compile può richiedere fino a 120s sotto carico; non timeout-are aggressivamente.
   - `transaction_execute` rifiutato pre-broadcast con "Transaction has wrong signature" non consuma fee (safety) ma indica payload firmato non match: rivedere innerId, userFields, fee.
5. **Lista compatta tools per categoria** con link a `tools-reference.md`.
6. **Link alle recipe** (ogni recipe è un task agentico completo, copia-incollabile).
7. **Snippet di firma** (link a `signing/`).
8. **Tabella errori MCP → significato → cosa fare**.
9. **Quando NON usare la skill** — MCP non connesso; richieste custodial come "creami un wallet".

### `tools-reference.md`

Catalogo completo dei 29 tools, ognuno con:

- nome, endpoint REST sottostante, annotations
- input schema (riassunto + esempio canonico da `payloads/`)
- output schema (riassunto + esempio)
- 1-2 righe di "quando usarlo"
- link alla recipe se ne fa parte

### `recipes/` — pattern compositi

Ogni recipe ha sezioni: **Quando** (trigger user), **Pre-requisiti**, **Step** (lista numerata di chiamate tools), **Errori frequenti**, **Conferme on-chain**.

- `transfer-cs.md` — invio CS classico (3-step Pack/sign/Execute + Wait)
- `deploy-contract.md` — Compile → Pack → sign → Deploy → Wait → Get
- `execute-method.md` — Methods (per scoprire) → Pack → sign → Execute → Result
- `inspect-wallet.md` — esplorazione read-only (balance, history, delegations)
- `attach-metadata.md` — userFields v1 caso ArtVerse (hash + CID + mime)
- `token-operations.md` — Token info, balance, transfers, holders

### `signing/` — snippet di firma client-side

- `python-pynacl.md` — 5 righe, validato on-chain in sessione 2026-04-27 (3 transfer mainnet)
- `typescript-tweetnacl.md` — equivalente JS/TS per wallet web/mobile

```python
# signing/python-pynacl.md (esempio)
import base58, nacl.signing
def sign_packaged(transaction_packaged_str_b58: str, private_key_b58: str) -> str:
    raw = base58.b58decode(transaction_packaged_str_b58)
    sk  = nacl.signing.SigningKey(base58.b58decode(private_key_b58)[:32])
    sig = sk.sign(raw).signature           # 64 bytes
    return base58.b58encode(sig).decode()
```

### `troubleshooting.md`

Mappa errori → causa → fix. Copre i 12 bug runtime già fixati nel branch (con nota "se vedi questo errore, controlla di essere a HEAD") + errori di Thrift schema specifici (`v_boolean` vs `v_bool`, `byteCodeObjects` annidato in `smartContractDeploy`, `ContractAllMethodsGet` vs `ContractMethodsGet`, ecc.).

## 7. Test e validazione

### Livello 1 — Unit test dei tools MCP (`tests/test_mcp_tools.py`)

Client HTTP mockato con `httpx.MockTransport`. Per ogni tool si verifica:

- Input schema validation (input invalido → `invalid_input`, no chiamata HTTP).
- Richiesta HTTP corretta (URL, body, headers).
- Mapping risposta gateway → output MCP.
- Mapping errori HTTP → codici MCP (400→`invalid_input`, 404→`not_found`, 503→`node_unavailable`, 429→`rate_limited`).
- Annotations metadata presenti e corrette.

Fixture richiesta/risposta riusano `payloads/*.json` come ground truth (no drift).

### Livello 2 — Integration test (`tests/test_mcp_integration.py`)

Lancia il Flask gateway in un thread (mock Thrift già usato da `tests/conftest.py`), apre il client MCP via `httpx.AsyncClient`, esercita pipeline complete:

- `transaction_pack` → restituisce un base58 valido decodabile.
- `transaction_execute` con signature stub → flusso fino al `TransactionFlow` mockato.
- `userfields_encode` + `userfields_decode` round-trip preserva campi v1.
- `smartcontract_pack` produce il canonical layout documentato.

### Livello 3 — Smoke on-chain (`scripts/mcp_onchain_smoke.py`)

Opzionale, manuale, eseguito quando c'è un nodo Credits raggiungibile (es. `vmi2403561` del memory). Non gira in CI:

- Read tools contro mainnet (GetWalletInfo su un wallet noto, GetSupply, GetActiveNodes).
- Transfer 0.001 CS end-to-end via tools MCP (Pack → sign con PyNaCl → Execute → WaitForBlock → GetTransactionInfo verifica).
- SmartContract Deploy del `BasicCounter` + Execute `getCounter()`.

### CI

Estende `.github/workflows/ci.yml`:

- `pytest tests/test_mcp_tools.py tests/test_mcp_integration.py -v`
- Lint sui JSON Schema dei tools (validi draft 7, almeno un `example`).
- `python -m compileall baba_mcp/`.

### Validazione skill ↔ codice

Test che catturano drift tra documentazione e implementazione:

- Ogni tool elencato in `tools-reference.md` esiste realmente in `server.list_tools()`.
- Ogni `payloads/*.json` referenziato dalle recipes è ancora valido come input dello schema corrispondente.
- Frontmatter `SKILL.md` valido (YAML, `description` < 1024 char, `name` matcha la directory).

### Coverage

90%+ sui moduli di `baba_mcp/` (codice di routing senza logica complessa). I 55/55 test del branch restano invariati.

### Manuale di QA per release

1. `pytest -v` → 100% pass.
2. `python -m baba_mcp.server` (stdio) → handshake con `mcp-inspector` ufficiale → `list_tools` ritorna 29 tools con annotations corrette.
3. `pm2 start ecosystem.config.js` → entrambi up, log puliti.
4. `curl -X POST http://localhost:7000/sse` con un client MCP HTTP → handshake OK.
5. Smoke on-chain (manuale, contro nodo `vmi2403561`).

## 8. Out of scope (esplicito)

- Endpoint di firma server-side / wallet generation (vincolo H del FOLLOW_UP).
- SSE Notifier (`/Notifier/Stream/<addr>`) — opzionale v2 nel piano originale, fuori scope di questa iniziativa.
- PR upstream a `molaanaa/baba-node-api` — separata, dopo che il fork è in stato "ready".
- Parsing strutturato di `smartContractResult` (FOLLOW_UP §H1) — minore, può essere aggiunto in iterazione successiva.
- Tools MCP "compositi" (es. `transfer_and_confirm`) — la composizione la fa la skill, non l'MCP.
- Signer MCP companion (`baba-signer-mcp`) — possibile follow-up, non in questo design.

## 9. Definition of done

- 29 tools registrati in `baba_mcp/tools/*.py` con JSON Schema + annotations.
- `baba_mcp/server.py` avviabile in modalità stdio e HTTP.
- `ecosystem.config.js` lancia gateway + mcp-http in bundle.
- `.claude/skills/baba-credits/` completa (SKILL + tools-reference + 6 recipe + 2 signing + troubleshooting).
- Test livello 1 e 2 verdi, coverage `baba_mcp/` ≥ 90%.
- Test di drift skill↔codice verdi.
- CI estesa e verde.
- README aggiornato con sezione MCP Server.
- `.env.mcp.example` committato.
- Smoke on-chain manuale eseguito almeno una volta con successo.

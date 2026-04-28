# BABA REST API 🚀

![Status](https://img.shields.io/badge/status-production--ready-brightgreen)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

A high-performance, production-ready REST API Gateway for the [Credits.com](https://credits.com) Blockchain.

This gateway bridges HTTP/REST applications (mobile wallets, backend services, dashboards) with a raw Credits Node (Thrift/TCP). Built for the **BABA Wallet ecosystem**, it is optimized for uptime, stability, and scalability.

---

## ✨ Features

- ⚡ **Diamond Edition Architecture** — Powered by `gevent` for high concurrency  
- 🔀 **Dual Routing Engine** — `/Monitor/*` and `/api/Monitor/*` support  
- 💰 **Universal Amount Formatter** — Prevents `AmountCommission` crashes  
- 🛡️ **Crash-Proof Thrift Layer** — Handles `SealedTransaction` automatically  
- 🔒 **Production Security** — Redis rate limiting + IP whitelisting  
- ❤️ **Battle Tested** — Designed for real blockchain wallet infrastructure  

---

## 🧱 Architecture Overview

```text
Client (App / Backend)
        ↓ HTTP/REST
   BABA Node API (Flask + Gevent)
        ↓ Thrift/TCP
     Credits Node
```

---

## 🛠️ Prerequisites

- Ubuntu 20.04+  
- Fully synced Credits Node  

### Enable Thrift in `config.ini`

```ini
[api]
port=9090
interface=127.0.0.1
executor_command=/usr/bin/java -Xmx768m -XX:MaxMetaspaceSize=256m -jar contract-executor.jar
```

### Install System Dependencies

```bash
sudo apt update
sudo apt install -y python3-pip thrift-compiler unzip nginx npm redis-server
sudo npm install -g pm2
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

---

## ⚙️ Installation & Setup

### 1. Clone Repository

```bash
git clone https://github.com/molaanaa/baba-node-api.git
cd baba-node-api
```

### 2. Compile Thrift Interface

```bash
wget https://github.com/CREDITSCOM/thrift-interface-definitions/archive/master.zip
unzip master.zip
cd thrift-interface-definitions-master

thrift -r --gen py api.thrift

cp -r gen-py ../
cd ..
rm -rf thrift-interface-definitions-master master.zip
```

### 3. Configure Environment

```bash
pip3 install -r requirements.txt

cp .env.example .env
nano .env
```

Edit `.env` to match your Node's IP, Port, and Redis configuration.

### 4. Start Gateway

```bash
pm2 start gateway.py --name "baba-node-api" --interpreter python3
pm2 save
pm2 startup
```

---

## 🔒 HTTPS Setup (Nginx + Certbot)

### Create Nginx Config

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

### Enable + Install SSL

```bash
sudo ln -s /etc/nginx/sites-available/baba_api /etc/nginx/sites-enabled/
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```

✔ Choose redirect to HTTPS when prompted  
✔ If using Cloudflare → set SSL to **Full (Strict)**  

---

## 📡 API Endpoints

All POST endpoints are exposed under both `/<path>` and `/api/<path>`.
Reply envelope is `{ success, message, ... }`. Addresses, signatures and binary
payloads travel as base58 strings on the JSON layer.

### Wallet & Transactions (existing)

| Method | Endpoint |
|--------|----------|
| POST   | `/api/Monitor/GetWalletInfo` |
| POST   | `/api/Monitor/GetBalance` |
| POST   | `/api/Monitor/GetTransactionsByWallet` |
| POST   | `/api/Monitor/GetEstimatedFee` |
| POST   | `/api/Transaction/Pack` |
| POST   | `/api/Transaction/Execute` |
| POST   | `/api/Transaction/GetTransactionInfo` |

### Smart Contract API ([details](docs/SMART_CONTRACTS.md))

| Method | Endpoint | Thrift |
|--------|----------|--------|
| POST | `/api/SmartContract/Compile` | `SmartContractCompile` |
| POST | `/api/SmartContract/Deploy` | `Transaction` (deploy) → `TransactionFlow` |
| POST | `/api/SmartContract/Execute` | `Transaction` (invoke) → `TransactionFlow` |
| POST | `/api/SmartContract/Get` | `SmartContractGet` |
| POST | `/api/SmartContract/Methods` | `SmartContractMethodsGet` / `getContractMethods` |
| POST | `/api/SmartContract/State` | `SmartContractDataGet` |
| POST | `/api/SmartContract/ListByWallet` | `SmartContractsListGet` |

### Token API

| Method | Endpoint | Thrift |
|--------|----------|--------|
| POST | `/api/Tokens/BalancesGet` | `TokenBalancesGet` |
| POST | `/api/Tokens/TransfersGet` | `TokenTransfersGet` |
| POST | `/api/Tokens/Info` | `TokenInfoGet` |
| POST | `/api/Tokens/HoldersGet` | `TokenHoldersGet` |
| POST | `/api/Tokens/TransactionsGet` | `TokenTransactionsGet` |

### Wait helpers (long-poll)

| Method | Endpoint | Thrift |
|--------|----------|--------|
| POST | `/api/Monitor/WaitForBlock` | `WaitForBlock` (blocking) |
| POST | `/api/Monitor/WaitForSmartTransaction` | `WaitForSmartTransaction` (blocking) |
| POST | `/api/Transaction/Result` | `TransactionResultGet` |

`timeoutMs` in the request body controls the long-poll budget; clamped to
`WAIT_MAX_TIMEOUT_MS` from the environment (default 120s). The socket waits
5s longer than the requested wait so the node can complete in-flight work.

### UserFields v1 codec (ArtVerse, local)

| Method | Endpoint |
|--------|----------|
| POST | `/api/UserFields/Encode` |
| POST | `/api/UserFields/Decode` |

Pure-local helpers, no Thrift involved. Used to attach typed metadata to the
`userData` field of any Credits transaction.

### Diagnostic API (optional, requires `apidiag` Thrift stubs)

| Method | Endpoint | Thrift |
|--------|----------|--------|
| POST | `/api/Diag/GetActiveNodes` | `API_DIAG.GetActiveNodes` |
| POST | `/api/Diag/GetActiveTransactionsCount` | `API_DIAG.GetActiveTransactionsCount` |
| POST | `/api/Diag/GetNodeInfo` | `API_DIAG.GetNodeInfo` |
| POST | `/api/Diag/GetSupply` | `API_DIAG.GetSupply` |

If the `apidiag` generated module is not on the path, these endpoints answer
`503 Diag service Unavailable` cleanly.

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

# Long-poll the next block (30s timeout)
curl -X POST http://localhost:5000/api/Monitor/WaitForBlock \
  -H "Content-Type: application/json" \
  -d '{"poolNumber": 0, "timeoutMs": 30000}'

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

# Deploy a smart contract (signature is base58)
curl -X POST http://localhost:5000/api/SmartContract/Deploy \
  -H "Content-Type: application/json" \
  -d '{
    "PublicKey": "<base58 deployer>",
    "byteCodeObjects": [{"name": "AccessRights", "byteCode": "<base64>"}],
    "sourceCode": "...optional...",
    "feeAsString": "0.1",
    "TransactionSignature": "<base58 signature>",
    "userData": "<base58 ArtVerse userFields v1 (optional)>"
  }'
```

---

## 🧪 Tests

```bash
pip3 install -r requirements-dev.txt
pytest tests/ -v
```

Test suite covers the pure-Python pieces (`services/userfields`,
`services/contracts`, `services/tokens`, `services/monitor`, `services/diag`)
plus an AST-level smoke test that verifies every documented route is wired
under both bare and `/api/` paths. End-to-end Thrift integration tests
require `gen-py` and a reachable Credits node; see
[docs/FOLLOW_UP.md](docs/FOLLOW_UP.md).

---

## 🌐 Credits node configuration

`.env.example` defaults to a local node on `127.0.0.1:9090`. Override
`NODE_IP` / `NODE_PORT` per environment, and set `NODE_DIAG_PORT` if
the node exposes API_DIAG on a port distinct from the main API
(commonly `9088` on standard builds).

---

## 📄 License

MIT License

---

## ⭐ Final Notes

- Designed for high uptime blockchain infrastructure  
- Safe against common Credits Node crashes  
- Optimized for mobile wallet backends  

💡 If this project helps you build on the Credits Blockchain, consider starring the repo!

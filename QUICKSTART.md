# Quickstart: Gateway + MCP da zero

Guida passo-passo per avviare il gateway HTTP e l'MCP server partendo da
una macchina pulita.

## 0. Prerequisiti

- Linux (Ubuntu 20.04+) con `python3` >= **3.10** (richiesto dal pacchetto `mcp`),
  `git`, `pip`, `venv`
- Accesso a un nodo Credits (porte API thrift `9090`, diag `9088`)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version    # deve essere >= 3.10
```

Se hai solo Python 3.8 (Ubuntu 20.04), installa 3.11 con `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv python install 3.11
```

## 1. Clone

```bash
cd ~
git clone https://github.com/molaanaa/baba-node-api.git
cd ~/baba-node-api
```

## 2. Virtualenv + dipendenze

```bash
# Con uv (raccomandato se hai installato Python via uv):
uv venv --python 3.11 .venv

# Oppure con venv standard se hai gia' Python >= 3.10:
# python3 -m venv .venv

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` include sia le dipendenze del gateway (Flask, gevent, thrift)
sia quelle dell'MCP (`mcp`, `httpx`, `pydantic`). Le dipendenze MCP vengono
installate solo se Python >= 3.10 (markers nei requirements).

## 3. Config gateway: `.env`

```bash
cp .env.example .env
chmod 600 .env
```

Apri `.env` e imposta almeno:

```
NODE_IP=<ip-del-nodo-credits>     # 127.0.0.1 se locale
NODE_PORT=9090
NODE_DIAG_PORT=9088
WHITELIST_IPS=127.0.0.1
DEBUG_LOGGING=False
```

## 4. Config MCP: `.env.mcp`

```bash
cp .env.mcp.example .env.mcp
chmod 600 .env.mcp

# Genera un bearer random e appendilo
TOKEN=$(openssl rand -hex 32)
echo "MCP_AUTH_TOKEN=$TOKEN" >> .env.mcp

echo
echo "=== TOKEN PER IL CLIENT (salvalo): $TOKEN ==="
```

Il file finale deve contenere:

```
MCP_TRANSPORT=http
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=7000
BABA_GATEWAY_URL=http://127.0.0.1:5000
MCP_LOG_LEVEL=info
MCP_WHITELIST_IPS=0.0.0.0/0    # se sta dietro nginx, non puoi filtrare per IP
MCP_AUTH_TOKEN=<token-generato-sopra>
```

## 5. Avvio (solo localhost)

```bash
mkdir -p logs

# Gateway su 127.0.0.1:5000
GATEWAY_HOST=127.0.0.1 nohup .venv/bin/python gateway.py > logs/gateway.log 2>&1 &
disown

# MCP su 127.0.0.1:7000
set -a; source .env.mcp; set +a
nohup .venv/bin/python -m baba_mcp.server > logs/mcp.log 2>&1 &
disown

# Verifica porte attive
ss -tlnp | grep -E ':(5000|7000)\b'

# Smoke test gateway
curl -X POST http://127.0.0.1:5000/Diag/GetNodeInfo \
  -H 'Content-Type: application/json' -d '{}'
```

## 6. (Opzionale) Esposizione pubblica con HTTPS

Solo se vuoi raggiungerli da Internet.

### a) DNS dinamico (DuckDNS)

Crea il dominio su https://www.duckdns.org e ottieni il token. Aggiungi un cron
ogni 5 minuti:

```bash
sudo tee /etc/cron.d/duckdns >/dev/null <<EOF
*/5 * * * * root curl -s "https://www.duckdns.org/update?domains=<tuo-dominio>&token=<duckdns-token>&ip=" >/dev/null
EOF
```

### b) Cert Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <tuo-dominio>.duckdns.org --redirect
```

### c) Vhost nginx

File `/etc/nginx/sites-available/baba`:

```nginx
server {
    listen 443 ssl http2;
    server_name <tuo-dominio>.duckdns.org;
    ssl_certificate     /etc/letsencrypt/live/<tuo-dominio>.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<tuo-dominio>.duckdns.org/privkey.pem;
    client_max_body_size 16m;

    location / { return 404; }

    # Gateway HTTP REST (no auth)
    location ~ ^/(Monitor|Transaction|UserFields|Tokens|SmartContract|Diag|api)/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 130s;
    }

    # MCP SSE handshake (Bearer richiesto)
    location = /sse {
        proxy_pass http://127.0.0.1:7000/sse;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
        chunked_transfer_encoding off;
    }

    # MCP message channel (autorizzato dal session_id)
    location /messages/ {
        proxy_pass http://127.0.0.1:7000/messages/;
        proxy_buffering off;
        proxy_read_timeout 60s;
    }
}
```

Attiva il vhost e ricarica nginx:

```bash
sudo ln -sf /etc/nginx/sites-available/baba /etc/nginx/sites-enabled/baba
sudo nginx -t && sudo systemctl reload nginx
```

## 7. Test pubblico

```bash
# Gateway (nessuna auth)
curl -X POST https://<tuo-dominio>.duckdns.org/api/Diag/GetSupply \
  -H 'Content-Type: application/json' -d '{}'

# MCP /sse (Bearer richiesto)
curl -H "Authorization: Bearer $TOKEN" https://<tuo-dominio>.duckdns.org/sse
# Risposta attesa:
#   event: endpoint
#   data: /messages/?session_id=<uuid>
```

## 8. Stop / restart

```bash
# Stop
pkill -f "python gateway.py"
pkill -f "baba_mcp.server"

# Restart: ripeti i comandi del passo 5
```

## 9. Configurare il client MCP (es. Claude Code)

Nel client aggiungi un server MCP di tipo `sse`:

- URL: `https://<tuo-dominio>.duckdns.org/sse`
- Header: `Authorization: Bearer <il_tuo_token>`

Per Claude Code da CLI:

```bash
claude mcp add baba-credits \
  --transport sse \
  --url https://<tuo-dominio>.duckdns.org/sse \
  --header "Authorization: Bearer <il_tuo_token>"
```

## Note di sicurezza

- Il **gateway HTTP** e' aperto pubblicamente: e' un proxy verso il nodo
  Credits, le scritture richiedono comunque transazioni firmate dal client.
  Il server non detiene chiavi private.
- L'**MCP** e' gated da Bearer **solo sulla `GET /sse`** (handshake). Le
  successive `POST /messages/?session_id=...` sono autorizzate dal
  `session_id` UUID v4 generato dopo l'handshake (capability non indovinabile,
  funzionalmente equivalente a un bearer monouso). Questo e' necessario perche'
  alcuni client (es. Claude mobile) inviano l'`Authorization` solo
  sull'apertura SSE.
- **Non committare** `.env` ne' `.env.mcp`: sono gia' in `.gitignore`. Tieni
  permessi `600` su entrambi.

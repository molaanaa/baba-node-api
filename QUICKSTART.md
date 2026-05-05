# Quickstart: Gateway + MCP from scratch

Step-by-step guide to bring up the HTTP gateway and the MCP server on a
clean machine.

## 0. Prerequisites

- Linux (Ubuntu 20.04+) with `python3` >= **3.10** (required by the `mcp`
  package), `git`, `pip`, `venv`
- Access to a Credits node (thrift API on port `9090`, diag on `9088`)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version    # must be >= 3.10
```

If you only have Python 3.8 (Ubuntu 20.04), install 3.11 with `uv`:

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

## 2. Virtualenv + dependencies

```bash
# With uv (recommended if you installed Python via uv):
uv venv --python 3.11 .venv

# Or with the standard venv if you already have Python >= 3.10:
# python3 -m venv .venv

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` covers both the gateway dependencies (Flask, gevent,
thrift) and the MCP ones (`mcp`, `httpx`, `pydantic`). The MCP packages
are only installed when Python is >= 3.10 (markers in the requirements).

## 3. Gateway config: `.env`

```bash
cp .env.example .env
chmod 600 .env
```

Open `.env` and set at least:

```
NODE_IP=<credits-node-ip>     # 127.0.0.1 if local
NODE_PORT=9090
NODE_DIAG_PORT=9088
WHITELIST_IPS=127.0.0.1
DEBUG_LOGGING=False
```

## 4. MCP config: `.env.mcp`

```bash
cp .env.mcp.example .env.mcp
chmod 600 .env.mcp

# Generate a random bearer and append it
TOKEN=$(openssl rand -hex 32)
echo "MCP_AUTH_TOKEN=$TOKEN" >> .env.mcp

echo
echo "=== TOKEN FOR THE CLIENT (save it): $TOKEN ==="
```

The final file should contain:

```
MCP_TRANSPORT=http
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=7000
BABA_GATEWAY_URL=http://127.0.0.1:5000
MCP_LOG_LEVEL=info
MCP_WHITELIST_IPS=0.0.0.0/0    # behind nginx, IP filtering is not effective
MCP_AUTH_TOKEN=<token-generated-above>
```

## 5. Startup (localhost only)

```bash
mkdir -p logs

# Gateway on 127.0.0.1:5000
GATEWAY_HOST=127.0.0.1 nohup .venv/bin/python gateway.py > logs/gateway.log 2>&1 &
disown

# MCP on 127.0.0.1:7000
set -a; source .env.mcp; set +a
nohup .venv/bin/python -m baba_mcp.server > logs/mcp.log 2>&1 &
disown

# Verify the ports are listening
ss -tlnp | grep -E ':(5000|7000)\b'

# Smoke-test the gateway
curl -X POST http://127.0.0.1:5000/Diag/GetNodeInfo \
  -H 'Content-Type: application/json' -d '{}'
```

## 6. (Optional) Public exposure with HTTPS

Only if you need to reach the services from the public Internet.

### a) Dynamic DNS (DuckDNS)

Register a domain on https://www.duckdns.org and grab the token. Add a
cron job that refreshes the IP every 5 minutes:

```bash
sudo tee /etc/cron.d/duckdns >/dev/null <<EOF
*/5 * * * * root curl -s "https://www.duckdns.org/update?domains=<your-domain>&token=<duckdns-token>&ip=" >/dev/null
EOF
```

### b) Let's Encrypt certificate

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <your-domain>.duckdns.org --redirect
```

### c) nginx vhost

`/etc/nginx/sites-available/baba`:

```nginx
server {
    listen 443 ssl http2;
    server_name <your-domain>.duckdns.org;
    ssl_certificate     /etc/letsencrypt/live/<your-domain>.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<your-domain>.duckdns.org/privkey.pem;
    client_max_body_size 16m;

    location / { return 404; }

    # HTTP REST gateway (no auth)
    location ~ ^/(Monitor|Transaction|UserFields|Tokens|SmartContract|Diag|api)/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 130s;
    }

    # MCP SSE handshake (Bearer required)
    location = /sse {
        proxy_pass http://127.0.0.1:7000/sse;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
        chunked_transfer_encoding off;
    }

    # MCP message channel (authorised by session_id)
    location /messages/ {
        proxy_pass http://127.0.0.1:7000/messages/;
        proxy_buffering off;
        proxy_read_timeout 60s;
    }
}
```

Enable the vhost and reload nginx:

```bash
sudo ln -sf /etc/nginx/sites-available/baba /etc/nginx/sites-enabled/baba
sudo nginx -t && sudo systemctl reload nginx
```

## 7. Public test

```bash
# Gateway (no auth)
curl -X POST https://<your-domain>.duckdns.org/api/Diag/GetSupply \
  -H 'Content-Type: application/json' -d '{}'

# MCP /sse (Bearer required)
curl -H "Authorization: Bearer $TOKEN" https://<your-domain>.duckdns.org/sse
# Expected response:
#   event: endpoint
#   data: /messages/?session_id=<uuid>
```

## 8. Stop / restart

```bash
# Stop
pkill -f "python gateway.py"
pkill -f "baba_mcp.server"

# Restart: re-run the commands from step 5
```

## 9. Configure the MCP client (e.g. Claude Code)

In your client, add an MCP server of type `sse`:

- URL: `https://<your-domain>.duckdns.org/sse`
- Header: `Authorization: Bearer <your_token>`

For Claude Code via CLI:

```bash
claude mcp add baba-credits \
  --transport sse \
  --url https://<your-domain>.duckdns.org/sse \
  --header "Authorization: Bearer <your_token>"
```

## Security notes

- The **HTTP gateway** is publicly reachable: it is a thin proxy in front
  of the Credits node, and write operations require the client to submit
  **already-signed** transactions. The server holds no private keys.
- The **MCP** is gated by Bearer **only on `GET /sse`** (handshake). The
  subsequent `POST /messages/?session_id=...` calls are authorised by the
  unguessable UUID v4 `session_id` minted after the handshake — a
  one-shot capability that is functionally equivalent to a single-use
  bearer. This is necessary because some clients (notably Claude mobile)
  only attach `Authorization` on the SSE handshake.
- **Do not commit** `.env` or `.env.mcp`: both are already in `.gitignore`.
  Keep them at mode `600`.

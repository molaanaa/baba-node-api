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

| Method | Endpoint |
|--------|----------|
| POST   | `/api/Monitor/GetBalance` |
| POST   | `/api/Monitor/GetTransactions` |
| POST   | `/api/Monitor/GetTransactionsByWallet` |
| POST   | `/api/Monitor/GetWalletData` |
| POST   | `/api/Transaction/Execute` |
| POST   | `/api/Monitor/GetEstimatedFee` |
| GET    | `/health` |

✔ All POST endpoints also work without the `/api` prefix.

---

## 🧪 Example Request

```bash
curl -X POST http://localhost:5000/api/Monitor/GetBalance \
-H "Content-Type: application/json" \
-d '{"publicKey":"YOUR_WALLET_ADDRESS"}'
```

---

## 📄 License

MIT License

---

## ⭐ Final Notes

- Designed for high uptime blockchain infrastructure  
- Safe against common Credits Node crashes  
- Optimized for mobile wallet backends  

💡 If this project helps you build on the Credits Blockchain, consider starring the repo!

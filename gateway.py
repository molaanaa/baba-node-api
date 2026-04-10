# BABA WALLET GATEWAY - DIAMOND EDITION
# Features: Gunicorn (Gevent), Redis Rate Limiting, Env Config, Strict Socket Management
from gevent import monkey
monkey.patch_all()

import os
import sys
import struct
import base58
from datetime import datetime
from decimal import Decimal, getcontext
from dotenv import load_dotenv

from flask import Flask, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# --- CONFIGURATION (Loaded from .env) ---
load_dotenv()

NODE_IP = os.getenv('NODE_IP', '127.0.0.1')
NODE_PORT = int(os.getenv('NODE_PORT', 9090))
DEBUG_LOGGING = os.getenv('DEBUG_LOGGING', 'False').lower() in ('true', '1', 't')
REDIS_URL = os.getenv('REDIS_URL', 'memory://') # Falls back to memory if Redis isn't set
WHITELIST_IPS = os.getenv('WHITELIST_IPS', '127.0.0.1').split(',')

# --- THRIFT SETUP ---
sys.path.append('gen-py')
from thrift.transport import TSocket, TTransport
from thrift.protocol import TBinaryProtocol
from api import API
import general.ttypes as general_types
import api.ttypes as api_types

Transaction = api_types.Transaction
Amount = general_types.Amount
AmountCommission = api_types.AmountCommission

getcontext().prec = 30

app = Flask(__name__)
# SECURITY: Trust Nginx/Cloudflare Headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# SECURITY: Distributed Rate Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "5 per second"],
    storage_uri=REDIS_URL
)

@limiter.request_filter
def ip_whitelist():
    """Skips the rate limiter for IPs defined in the environment whitelist."""
    return request.remote_addr in WHITELIST_IPS

app.url_map.strict_slashes = False

# --- HELPERS ---
def log(msg, is_error=False):
    """Sanitized logging. Only prints to stdout/stderr, never sent to client."""
    if DEBUG_LOGGING or is_error:
        prefix = "[ERROR]" if is_error else "[INFO]"
        print(f"{prefix} [{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_node_client():
    transport = None
    try:
        socket = TSocket.TSocket(NODE_IP, NODE_PORT)
        socket.setTimeout(5000)
        transport = TTransport.TBufferedTransport(socket)
        protocol = TBinaryProtocol.TBinaryProtocol(transport)
        client = API.Client(protocol)
        transport.open()
        return client, transport
    except Exception as e:
        log(f"Thrift Connection Error: {e}", is_error=True)
        if transport: transport.close()
        return None, None

def get_json_val(data, keys, default=None):
    if not data: return default
    for k in keys:
        if k in data: return data[k]
    return default

def safe_int(val, default=0):
    if val is None: return default
    try:
        if hasattr(val, 'index'): return val.index
        return int(val)
    except: return default

def fee_to_bits(fee_str):
    try:
        val = Decimal(str(fee_str).strip())
        if val <= 0: return 0
        constant = Decimal('26214400')
        value = val * constant
        best_m, best_e, min_diff = 0, 0, Decimal('inf')
        for e in range(9):
            power = Decimal(2) ** e
            m_temp = (value / power).to_integral_value(rounding='ROUND_HALF_UP')
            m = int(m_temp)
            if m > 2047: m = 2047
            if m < 0: m = 0
            diff = abs(value - Decimal(m) * power)
            if diff < min_diff or (diff == min_diff and e > best_e):
                min_diff = diff
                best_m, best_e = m, e
        return (best_e << 11) | best_m
    except: return 18431

def bits_to_fee(bits):
    try:
        raw = getattr(bits, 'commission', getattr(bits, 'value', int(bits) if isinstance(bits, (int,str)) else 0))
        if raw == 0: return Decimal('0')
        mantissa = Decimal(raw & 0x7FF)
        exponent = raw >> 11
        return mantissa * (Decimal(2) ** exponent) / Decimal(26214400)
    except: return Decimal('0')

def parse_amount(amount_val):
    amount_str = str(amount_val).strip()
    try:
        if not amount_str: return Amount(0, 0)
        if '.' in amount_str:
            p = amount_str.split('.')
            return Amount(int(p[0]), int(p[1][:18].ljust(18, '0')))
        return Amount(int(amount_str), 0)
    except: return Amount(0, 0)

def full_decimal(val):
    try: return f"{Decimal(str(val)):.18f}"
    except: return str(val)

def get_fee_multiplier(size):
    if size < 5120: return Decimal(1)
    elif size < 20480: return Decimal(4)
    elif size < 51200: return Decimal(16)
    else: return Decimal(2048)

# --- SERIALIZATION ---
def serialize_transaction(inner_id, source, target, amt_i, amt_f, fee_bits, currency=1, user_data=b''):
    data = struct.pack('<Q', inner_id)[:6] + source + target
    data += struct.pack('<i', amt_i) + struct.pack('<q', amt_f)
    data += struct.pack('<H', fee_bits) + struct.pack('B', currency)
    if len(user_data) == 0: data += b'\x00'
    else: data += struct.pack('B', len(user_data)) + user_data
    return data

def serialize_delegation(inner_id, source, target, amt_i, amt_f, fee_bits, is_revoke, expiry):
    header = struct.pack('<Q', inner_id)[:6] + source + target
    header += struct.pack('<i', amt_i) + struct.pack('<q', amt_f)
    header += struct.pack('<H', fee_bits) + b'\x01'
    payload = b'\x01' + struct.pack('<q', 2 if is_revoke else expiry)
    return header + payload

def format_amount(obj, as_str=False, force_decimal=False):
    if obj is None: return "0" if as_str else 0
    if hasattr(obj, 'integral'):
        integral = obj.integral or 0
        fraction = obj.fraction or 0
        if fraction == 0:
            return f"{integral}.0" if as_str and force_decimal else (f"{integral}" if as_str else integral)
        val_str = f"{integral}.{str(fraction).zfill(18)}".rstrip('0').rstrip('.')
        return val_str if as_str else float(val_str)
    val = bits_to_fee(obj) if hasattr(obj, 'commission') else Decimal(str(obj))
    if as_str:
        s = format(val, '.18f').rstrip('0').rstrip('.')
        return s + '.0' if force_decimal and '.' not in s else s
    return float(val)

def map_delegated_item(item):
    if not item: return None
    pub_key = base58.b58encode(getattr(item, 'wallet', b'')).decode('utf-8')
    sum_val = format_amount(getattr(item, 'sum', None) or getattr(item, 'amount', None))
    return {
        "publicKey": pub_key,
        "sum": int(sum_val) if sum_val == int(sum_val) else sum_val,
        "validUntil": safe_int(getattr(item, 'validUntil', 0)),
        "validFrom": safe_int(getattr(item, 'fromTime', 0)),
        "coeff": getattr(item, 'coeff', 0)
    }

def map_transaction_to_dict(tx, inner_id):
    data = getattr(tx, 'trxn', tx)
    tx_id_raw = getattr(tx, 'id', 0)
    final_id = f"{getattr(tx_id_raw, 'poolSeq', 0)}.{getattr(tx_id_raw, 'index', 0) + 1}" if hasattr(tx_id_raw, 'poolSeq') else "0"
    source = base58.b58encode(getattr(data, 'source', b'')).decode('utf-8')
    target = base58.b58encode(getattr(data, 'target', b'')).decode('utf-8')
    fee_val = bits_to_fee(getattr(data, 'fee', None))
    t_val = getattr(data, 'timeCreation', 0) or getattr(tx, 'timeCreation', 0)
    time_str = datetime.utcnow().isoformat() + "Z"
    if t_val:
        try: time_str = datetime.utcfromtimestamp(t_val / 1000.0).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        except: pass

    return {
        "currency": "CS",
        "fee": format_amount(fee_val, as_str=True, force_decimal=True),
        "fromAccount": source,
        "id": final_id,
        "innerId": inner_id,
        "status": "Success",
        "sum": format_amount(getattr(data, 'amount', None), as_str=True, force_decimal=True),
        "time": time_str,
        "toAccount": target,
        "type": str(getattr(data, 'type', 0))
    }

# --- ENDPOINTS ---

@app.route('/Monitor/GetWalletInfo', methods=['POST'])
@app.route('/api/Monitor/GetWalletInfo', methods=['POST'])
@limiter.limit("10 per second; 200 per minute")
def get_wallet_info():
    data = request.json
    if not data: return jsonify({"success": False, "message": "Empty Body"}), 400
    pub = get_json_val(data, ['publicKey', 'PublicKey'], '')
    client, transport = get_node_client()
    if not client: return jsonify({"success": False, "message": "Node Unavailable"}), 503
    
    try:
        pk_bytes = base58.b58decode(pub)
        res = client.WalletDataGet(pk_bytes)
        wdata = getattr(res, 'walletData', getattr(res, 'wallet', res))
        delegated_data = {"incoming": 0, "outgoing": 0, "donors": [], "recipients": []}
        if wdata and getattr(wdata, 'delegated', None):
            d = wdata.delegated
            delegated_data["incoming"] = format_amount(getattr(d, 'incoming', None))
            delegated_data["outgoing"] = format_amount(getattr(d, 'outgoing', None))
            delegated_data["donors"] = [map_delegated_item(x) for x in (getattr(d, 'donors', []) or []) if x]
            delegated_data["recipients"] = [map_delegated_item(x) for x in (getattr(d, 'recipients', []) or []) if x]
        return jsonify({
            "balance": format_amount(getattr(wdata, 'balance', None)),
            "lastTransaction": safe_int(getattr(wdata, 'lastTransactionId', 0)),
            "delegated": delegated_data, "success": True, "message": None
        })
    except Exception as e:
        log(f"GetWalletInfo Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to retrieve wallet data"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()

@app.route('/Monitor/GetTransactionsByWallet', methods=['POST'])
@app.route('/api/Monitor/GetTransactionsByWallet', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def get_history():
    data = request.json
    if not data: return jsonify({"success": False}), 400
    pub = get_json_val(data, ['publicKey', 'PublicKey'], '')
    client, transport = get_node_client()
    if not client: return jsonify({"success": False}), 503
    
    try:
        pk_bytes = base58.b58decode(pub)
        off = int(data.get('offset', 0))
        lim = int(data.get('limit', 10))
        wdata = getattr(client.WalletDataGet(pk_bytes), 'walletData', None)
        last_tx = safe_int(getattr(wdata, 'lastTransactionId', 0))
        res = client.TransactionsGet(pk_bytes, off, lim)
        mapped = [map_transaction_to_dict(tx, last_tx - off - i) for i, tx in enumerate(getattr(res, 'transactions', []))]
        return jsonify({"message": None, "success": True, "transactions": mapped})
    except Exception as e:
        log(f"GetHistory Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to retrieve transactions"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()

@app.route('/Monitor/GetEstimatedFee', methods=['POST'])
@app.route('/api/Monitor/GetEstimatedFee', methods=['POST'])
@limiter.limit("5 per second")
def get_fee():
    data = request.json
    if not data: return jsonify({"success": False}), 400
    tx_size = int(get_json_val(data, ['transactionSize'], 0))
    client, transport = get_node_client()
    if not client: return jsonify({"success": False}), 503
    
    try:
        base_fee = bits_to_fee(getattr(client.ActualFeeGet(0), 'fee', 0))
        return jsonify({"fee": float(base_fee * get_fee_multiplier(tx_size)), "success": True, "message": ""})
    except Exception as e:
        log(f"GetFee Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to estimate fee"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()

@app.route('/Monitor/GetBalance', methods=['POST'])
@app.route('/api/Monitor/GetBalance', methods=['POST'])
@limiter.limit("10 per second; 200 per minute")
def get_balance():
    data = request.json
    if not data: return jsonify({"success": False}), 400
    pub = get_json_val(data, ['publicKey', 'PublicKey'], '')
    client, transport = get_node_client()
    if not client: return jsonify({"success": False}), 503
    
    try:
        res = client.WalletBalanceGet(base58.b58decode(pub))
        d = getattr(res, 'delegated', None)
        return jsonify({
            "balance": format_amount(getattr(res, 'balance', None)), "tokens": [],
            "delegatedOut": format_amount(getattr(d, 'outgoing', None)) if d else 0,
            "delegatedIn": format_amount(getattr(d, 'incoming', None)) if d else 0,
            "success": True, "message": "Tokens not supported"
        })
    except Exception as e:
        log(f"GetBalance Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to retrieve balance"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()

@app.route('/Transaction/Pack', methods=['POST'])
@app.route('/api/Transaction/Pack', methods=['POST'])
@limiter.limit("2 per 10 seconds")
def pack_transaction():
    data = request.json
    if not data: return jsonify({"success": False, "message": "Empty"}), 400
    pub = get_json_val(data, ['PublicKey', 'publicKey'])
    rec_pub = get_json_val(data, ['ReceiverPublicKey', 'receiverPublicKey'])
    amt_str = get_json_val(data, ['amountAsString', 'Amount'], "0")
    fee_str = get_json_val(data, ['feeAsString', 'Fee'], "0")
    user_data = get_json_val(data, ['UserData', 'userData'], "")
    del_en = get_json_val(data, ['DelegateEnable', 'delegateEnable'], False)
    del_dis = get_json_val(data, ['DelegateDisable', 'delegateDisable'], False)
    date_exp = get_json_val(data, ['DateExpiredUtc', 'dateExpiredUtc'], "")
    
    if not pub or not rec_pub: return jsonify({"success": False, "message": "Missing Keys"}), 400
    client, transport = get_node_client()
    if not client: return jsonify({"success": False}), 503
    
    try:
        sender = base58.b58decode(pub)
        target = base58.b58decode(rec_pub)
        wdata = None
        try: wdata = getattr(client.WalletDataGet(sender), 'walletData', None)
        except: pass
        
        new_id = safe_int(getattr(wdata, 'lastTransactionId', 0)) + 1
        is_del = del_en or del_dis
        size = 9 if is_del else len(user_data.encode('utf-8'))
        base_res = client.ActualFeeGet(0)
        
        
        base_fee = bits_to_fee(getattr(base_res, 'fee', base_res))
        rec_fee = float(base_fee) * float(get_fee_multiplier(size))
        use_fee = float(fee_str) if float(fee_str) > 0 else rec_fee
        fee_bits = fee_to_bits(use_fee)
        amt = parse_amount(amt_str)
        
        if is_del:
            exp_val = 2 if del_dis else (int(date_exp) if date_exp else 1)
            packed = serialize_delegation(new_id, sender, target, amt.integral, amt.fraction, fee_bits, del_dis, exp_val)
        else:
            ud = user_data.encode('utf-8') if user_data else b''
            packed = serialize_transaction(new_id, sender, target, amt.integral, amt.fraction, fee_bits, user_data=ud)
            
        return jsonify({
            "success": True,
            "dataResponse": {
                "transactionPackagedStr": base58.b58encode(packed).decode('utf-8'),
                "recommendedFee": rec_fee, "actualSum": 0, "publicKey": None, "smartContractResult": None
            },
            "actualFee": 0, "actualSum": 0, "amount": 0, "blockId": 0, "extraFee": None, "flowResult": None, "listItem": [], "listTransactionInfo": None, "message": None, "transactionId": None, "transactionInfo": None, "transactionInnerId": None
        })
    except Exception as e:
        log(f"Transaction Pack Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to pack transaction"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()

@app.route('/Transaction/Execute', methods=['POST'])
@app.route('/api/Transaction/Execute', methods=['POST'])
@limiter.limit("2 per 10 seconds")
def execute():
    data = request.json
    if not data: return jsonify({"success": False, "message": "Empty"}), 400
    pub = get_json_val(data, ['PublicKey', 'publicKey'])
    rec_pub = get_json_val(data, ['ReceiverPublicKey', 'receiverPublicKey'])
    amt_str = get_json_val(data, ['amountAsString', 'Amount'], "0")
    fee_str = get_json_val(data, ['feeAsString', 'Fee'], "0")
    sig = get_json_val(data, ['TransactionSignature', 'signature'], "")
    user_data = get_json_val(data, ['UserData', 'userData'], "")
    del_en = get_json_val(data, ['DelegateEnable', 'delegateEnable'], False)
    del_dis = get_json_val(data, ['DelegateDisable', 'delegateDisable'], False)
    date_exp = get_json_val(data, ['DateExpiredUtc', 'dateExpiredUtc'], "")
    
    if not pub or not sig: return jsonify({"success": False, "message": "Missing Data"}), 400
    client, transport = get_node_client()
    if not client: return jsonify({"success": False}), 503
    
    try:
        sender = base58.b58decode(pub)
        wdata = None
        try: wdata = getattr(client.WalletDataGet(sender), 'walletData', None)
        except: pass
        
        new_id = safe_int(getattr(wdata, 'lastTransactionId', 0)) + 1
        is_del = del_en or del_dis
        size = 9 if is_del else len(user_data.encode('utf-8'))
        base_fee = bits_to_fee(getattr(client.ActualFeeGet(0), 'fee', 0))
        rec_fee = float(base_fee) * float(get_fee_multiplier(size))
        use_fee = float(fee_str) if float(fee_str) > 0 else rec_fee
        fee_bits = fee_to_bits(use_fee)
        
        tx = Transaction()
        tx.id = new_id
        tx.source = sender
        tx.target = base58.b58decode(rec_pub)
        tx.amount = parse_amount(amt_str)
        tx.balance = Amount(0, 0)
        tx.currency = 1
        tx.fee = AmountCommission(commission=int(fee_bits))
        tx.signature = base58.b58decode(sig)
        
        if is_del:
            exp_val = 2 if del_dis else (int(date_exp) if date_exp else 1)
            payload = b'\x01' + struct.pack('<q', exp_val)
            node_header = bytes.fromhex("000105000000")
            tx.userFields = node_header + payload
            tx.type = 7
        else:
            ud = user_data.encode('utf-8') if user_data else b''
            tx.userFields = ud
            tx.type = 0
            
        res = client.TransactionFlow(tx)
        
        status = getattr(res, 'status', None)
        success = getattr(status, 'code', 1) == 0
        tx_id = getattr(res, 'id', None)
        tx_id_str = f"{getattr(tx_id, 'poolSeq', 0)}.{getattr(tx_id, 'index', 0) + 1}" if tx_id and hasattr(tx_id, 'poolSeq') else None
        
        return jsonify({
            "amount": full_decimal(amt_str),
            "dataResponse": {
                "actualSum": 0, "publicKey": None, "recommendedFee": float(rec_fee), "smartContractResult": None, "transactionPackagedStr": None
            },
            "actualSum": full_decimal(getattr(res, 'sum', amt_str)),
            "actualFee": full_decimal(getattr(res, 'fee', rec_fee)),
            "extraFee": None, "flowResult": None, "listItem": [], "listTransactionInfo": None, "message": None,
            "messageError": getattr(status, 'message', None) if not success else None,
            "success": success, "transactionId": tx_id_str, "transactionInfo": None, "transactionInnerId": new_id, "blockId": 0
        })
    except Exception as e:
        log(f"Transaction Execute Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to execute transaction"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

# BABA WALLET GATEWAY - DIAMOND EDITION (V33 - UserData Parsing Optimized)

from gevent import monkey
monkey.patch_all()

import os
import sys
import struct
import base58
import math
from datetime import datetime, timezone
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
WAIT_DEFAULT_TIMEOUT_MS = int(os.getenv('WAIT_DEFAULT_TIMEOUT_MS', 30000))
WAIT_MAX_TIMEOUT_MS = int(os.getenv('WAIT_MAX_TIMEOUT_MS', 120000))

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
    
    return request.remote_addr in WHITELIST_IPS

app.url_map.strict_slashes = False

# --- HELPERS ---
def log(msg, is_error=False):
   
    if DEBUG_LOGGING or is_error:
        prefix = "[ERROR]" if is_error else "[INFO]"
        print(f"{prefix} [{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_node_client(timeout_ms=10000):
    transport = None
    try:
        socket = TSocket.TSocket(NODE_IP, NODE_PORT)
        socket.setTimeout(int(timeout_ms))
        transport = TTransport.TBufferedTransport(socket)
        protocol = TBinaryProtocol.TBinaryProtocol(transport)
        client = API.Client(protocol)
        transport.open()
        return client, transport
    except Exception as e:
        log(f"Thrift Connection Error: {e}", is_error=True)
        if transport: transport.close()
        return None, None


def _resolve_wait_timeout(data):
    """Pick a timeout in ms from the request body, clamped to the configured max."""
    try:
        ms = int(get_json_val(data, ['timeoutMs', 'TimeoutMs'], WAIT_DEFAULT_TIMEOUT_MS))
    except (TypeError, ValueError):
        ms = WAIT_DEFAULT_TIMEOUT_MS
    if ms <= 0:
        ms = WAIT_DEFAULT_TIMEOUT_MS
    return min(ms, WAIT_MAX_TIMEOUT_MS)

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

def get_k_ten(index):
   
    k_tens = (1e-18, 1e-17, 1e-16, 1e-15, 1e-14, 1e-13, 1e-12, 1e-11, 
              1e-10, 1e-9,  1e-8,  1e-7,  1e-6,  1e-5,  1e-4,  1e-3,
              1e-2,  1e-1,  1.0,   1e1,   1e2,   1e3,   1e4,   1e5,   
              1e6,   1e7,   1e8,   1e9,   1e10,  1e11,  1e12,  1e13)
    return k_tens[index] if 0 <= index < 32 else 0.0

def fee_to_bits(fee_val):
    
    try:
        val = float(fee_val)
        fee_commission = 0
        
        if val < 0.0:
            fee_commission += 32768
        else:
            
            val = math.fabs(val)
            expf = 0.0 if val == 0.0 else math.log10(val)
            expi = int(expf + 0.5 if expf >= 0.0 else expf - 0.5)
            
            # Avoid division by zero issues by checking val
            if val > 0:
                val /= math.pow(10, expi)
                
            if val >= 1.0:
                val *= 0.1
                expi += 1
                
            fee_commission += int(1024 * (expi + 18))
            fee_commission += int(val * 1024)
            
        return fee_commission
    except (ValueError, TypeError):
        return 0

def bits_to_fee(bits):
    try:
        raw = getattr(bits, 'commission', getattr(bits, 'value', int(bits) if isinstance(bits, (int,str)) else 0))
        if raw == 0: 
            return Decimal('0')

        sign = -1.0 if int(raw / 32768) != 0 else 1.0
        idx = int(raw % 32768 / 1024)
        mantissa = float(raw % 1024)
        
        fee_double = sign * mantissa * (1.0 / 1024.0) * get_k_ten(idx)
        
        return Decimal(str(fee_double))
    except Exception:
        return Decimal('0')

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
    """Ensures a clean string representation with at least one decimal place (e.g., '1.0')."""
    if not val: 
        return "0.0"
        
    try:
        # If it's a Thrift Amount object, format it first
        if hasattr(val, 'integral'):
            val = format_amount(val, as_str=True)
            
        # Use Decimal to normalize (strips trailing zeros)
        dec_val = Decimal(str(val)).normalize()
        
        # Determine string output, forcing .0 if it's an integer
        str_val = f"{dec_val:f}"
        return str_val if '.' in str_val else f"{str_val}.0"
    except Exception:
        return "0.0"

def get_fee_multiplier(size):
    if size < 5120: return Decimal(1)
    elif size < 20480: return Decimal(4)
    elif size < 51200: return Decimal(16)
    else: return Decimal(2048)

# --- SERIALIZATION ---
def build_user_fields(user_data_text=None, is_delegation=False, del_dis=False, date_exp=None):
    
    if is_delegation:
        exp_val = 2 if del_dis else (int(date_exp) if date_exp else 1)
        val_bytes = struct.pack('<q', exp_val) # 8-byte integer
        
        # Node payload (ufBytes)
        uf_bytes = bytearray(b'\x00')           
        uf_bytes.extend(b'\x01')          
        uf_bytes.extend(b'\x05\x00\x00\x00')    
        uf_bytes.extend(b'\x01')                 
        uf_bytes.extend(val_bytes)          
        
        # Signature payload (sfBytes)
        sf_bytes = bytearray(b'\x01')       
        sf_bytes.extend(val_bytes)                    
        
        return bytes(uf_bytes), bytes(sf_bytes)

    if user_data_text:
        ud_bytes = user_data_text.encode('utf-8')
        ud_len = len(ud_bytes)

        # Node payload (ufBytes)
        uf_bytes = bytearray(b'\x00')
        uf_bytes.extend(b'\x01')                    
        uf_bytes.extend(b'\x01\x00\x00\x00')     
        uf_bytes.extend(b'\x02')                      
        uf_bytes.extend(ud_len.to_bytes(4, 'little'))
        uf_bytes.extend(ud_bytes)

        # Signature payload (sfBytes)
        sf_bytes = bytearray(b'\x01')
        sf_bytes.extend(ud_len.to_bytes(4, 'little'))
        sf_bytes.extend(ud_bytes)

        return bytes(uf_bytes), bytes(sf_bytes)

    return b'', b'\x00'

def serialize_transaction(inner_id, source, target, amt_i, amt_f, fee_bits, currency=1, sf_bytes=b'\x00'):
    data = struct.pack('<Q', inner_id)[:6] + source + target
    data += struct.pack('<i', amt_i) + struct.pack('<q', amt_f)
    data += struct.pack('<H', fee_bits) + struct.pack('B', currency)
    data += sf_bytes
    return data

MAX_FRACTION_RANGE = Decimal('1000000000000000000') # 1e18

def format_amount(amt_obj, as_str=False, force_decimal=False):
    """Converts Thrift Amount object to numeric/string, avoiding float precision loss."""
    if not amt_obj: return "0.0" if as_str else 0
    
    integral = getattr(amt_obj, 'integral', 0)
    fraction = getattr(amt_obj, 'fraction', 0)
    
    if fraction == 0 and not force_decimal:
        return str(integral) if as_str else integral
        
    val = Decimal(integral) + (Decimal(fraction) / MAX_FRACTION_RANGE)
    return str(val) if as_str else float(val)



# --- UNIFIED PARSING HELPERS ---

def parse_currency(curr_code):
    
    curr_code = safe_int(curr_code, 1)
    
    return "CS" if curr_code == 1 else str(curr_code)

def parse_status(obj):
    
    status_obj = getattr(obj, 'status', None)
    if status_obj:
        code = getattr(status_obj, 'code', 0)
        message = getattr(status_obj, 'message', '')
        if code == 0 or 'Success' in message:
            return "Success"
        return message.strip() if message else "Failed"
    
    return "Success"

def parse_node_time(t_val):
    
    if not t_val:
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    try:
        
        dt = datetime.fromtimestamp(t_val / 1000.0, tz=timezone.utc)
        return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except Exception:
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def safe_b58(val):
    
    if not val:
        return None
    try:
        return base58.b58encode(val).decode('utf-8')
    except Exception:
        return None

# --- STANDARDIZED MAPPING FUNCTIONS ---

def map_delegated_item(item):
    if not item: return None
    
    sum_val = format_amount(getattr(item, 'sum', None) or getattr(item, 'amount', None))
    
    return {
        "publicKey": safe_b58(getattr(item, 'wallet', b'')),
        "sum": int(sum_val) if sum_val == int(sum_val) else sum_val,
        "validUntil": safe_int(getattr(item, 'validUntil', 0)),
        "validFrom": safe_int(getattr(item, 'fromTime', 0)),
        "coeff": getattr(item, 'coeff', 0)
    }

def map_transaction_to_dict(tx, inner_id):
    if not tx: return None
    
    
    data = getattr(tx, 'trxn', tx)
    
  
    tx_id_raw = getattr(tx, 'id', 0)
    final_id = "0"
    if hasattr(tx_id_raw, 'poolSeq') and hasattr(tx_id_raw, 'index'):
        final_id = f"{tx_id_raw.poolSeq}.{tx_id_raw.index + 1}"
    
    
    currency_code = getattr(data, 'currency', 1) 
    
    return {
        "id": final_id,
        "innerId": inner_id,
        "type": str(getattr(data, 'type', 0)),
        "status": parse_status(tx),                     
        "currency": parse_currency(currency_code),      
        "fromAccount": safe_b58(getattr(data, 'source', b'')),
        "toAccount": safe_b58(getattr(data, 'target', b'')),
        "sum": format_amount(getattr(data, 'amount', None), as_str=True, force_decimal=True),
        "fee": full_decimal(bits_to_fee(getattr(data, 'fee', None))),
        "time": parse_node_time(getattr(data, 'timeCreation', 0) or getattr(tx, 'timeCreation', 0))
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




@app.route('/api/Transaction/GetTransactionInfo', methods=['POST'])
@limiter.limit("5 per 10 seconds")
def handle_get_transaction_info():
    data_req = request.json
    if not data_req: return jsonify({"success": False, "message": "Empty"}), 400
    
    tx_id_str = get_json_val(data_req, ['transactionId', 'TransactionId'], '')
    if not tx_id_str or '.' not in tx_id_str:
        return jsonify({"success": False, "message": "Invalid Transaction ID format"}), 400
        
    client, transport = get_node_client()
    if not client: return jsonify({"success": False}), 503
    
    try:
        pool_seq_str, index_str = tx_id_str.split('.')
        pool_seq = int(pool_seq_str)
        tx_index = int(index_str) - 1 
        
        tx_id_obj = api_types.TransactionId()
        tx_id_obj.poolSeq = pool_seq
        tx_id_obj.index = tx_index
        
        tx_res = client.TransactionGet(tx_id_obj)
        
        found = getattr(tx_res, 'found', False)
        sealed_tx = getattr(tx_res, 'transaction', None)
        
        if not found or not sealed_tx:
            return jsonify({"success": False, "message": "Transaction not found on node", "found": False}), 404
            
        data = getattr(sealed_tx, 'trxn', sealed_tx)
        
        base_fee_dec = Decimal(str(bits_to_fee(getattr(data.fee, 'commission', 0) if hasattr(data, 'fee') else 0)))
        
        extra_fees = getattr(data, 'extraFee', []) or getattr(sealed_tx, 'extraFee', [])
        mapped_extra_fees = []
        
        if extra_fees:
            total_extra_dec = Decimal('0.0')
            for ef in extra_fees:
                
                ef_val_dec = Decimal(str(bits_to_fee(getattr(ef, 'commission', 0))))
                total_extra_dec += ef_val_dec
                mapped_extra_fees.append({}) 
                
            total_fee_dec = base_fee_dec + total_extra_dec
            fee_str = f"(sum of {len(extra_fees)}) {total_fee_dec}"
        else:
            fee_str = str(base_fee_dec)
        
        amt_val = format_amount(getattr(data, 'amount', None))
        type_int = getattr(data, 'type', 0)
        
        
        type_defs = {
            0: "TT_Normal", 1: "TT_SmartDeploy", 2: "TT_SmartExecute", 
            3: "TT_SmartState", 4: "TT_ContractReplenish"
        }
        
        return jsonify({
            "id": tx_id_str,
            "fromAccount": safe_b58(getattr(data, 'source', b'')),
            "toAccount": safe_b58(getattr(data, 'target', b'')),
            "time": parse_node_time(getattr(data, 'timeCreation', 0) or getattr(sealed_tx, 'timeCreation', 0)),
            "value": str(amt_val),
            "val": float(amt_val),
            "fee": fee_str, 
            "currency": parse_currency(getattr(data, 'currency', 1)),
            "innerId": getattr(data, 'id', 0),
            "index": tx_index,
            "status": parse_status(sealed_tx) or parse_status(data),
            "transactionType": type_int,
            "transactionTypeDefinition": type_defs.get(type_int, f"TT_Unknown_{type_int}"),
            "blockNum": pool_seq_str,
            "found": True,
            "userData": getattr(data, 'userFields', b'').decode('utf-8', 'ignore'),
            "signature": safe_b58(getattr(data, 'signature', b'') or getattr(sealed_tx, 'signature', b'')),
            "extraFee": mapped_extra_fees, 
            "bundle": None,
            "success": True,
            "message": None
        })
        
    except Exception as e:
        log(f"GetTransactionInfo Error: {e}", is_error=True)
        return jsonify({"success": False, "message": str(e), "found": False}), 500
        
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
        
        uf_bytes, sf_bytes = build_user_fields(
            user_data_text=user_data, 
            is_delegation=is_del, 
            del_dis=del_dis, 
            date_exp=date_exp
        )
        size = 9 if is_del else len(uf_bytes)
        
        base_res = client.ActualFeeGet(0)
        base_fee = bits_to_fee(getattr(base_res, 'fee', base_res))
        rec_fee = float(base_fee) * float(get_fee_multiplier(size))
        use_fee = float(fee_str) if float(fee_str) > 0 else rec_fee
        fee_bits = fee_to_bits(use_fee)
        amt = parse_amount(amt_str)
        
        packed = serialize_transaction(
            new_id, sender, target, amt.integral, amt.fraction, fee_bits, sf_bytes=sf_bytes
        )
            
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
        
        uf_bytes, sf_bytes = build_user_fields(
            user_data_text=user_data, 
            is_delegation=is_del, 
            del_dis=del_dis, 
            date_exp=date_exp
        )
        size = 9 if is_del else len(uf_bytes)
        
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
        
        tx.userFields = uf_bytes
        
            
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


# --- DIAGNOSTIC API (API_DIAG service) ---
from services import diag as _diag


def get_diag_client(timeout_ms=10000):
    """Open a Thrift client against the node's API_DIAG service.

    The diagnostic service is exposed on the same port as the main API but
    uses a separate Thrift interface (``apidiag.thrift``). If the generated
    module is missing (e.g. operator forgot to compile apidiag.thrift), this
    returns ``(None, None)`` so the endpoint can answer 503 cleanly.
    """
    try:
        from apidiag import API_DIAG  # type: ignore
    except Exception as e:
        log(f"apidiag stubs unavailable: {e}", is_error=True)
        return None, None
    transport = None
    try:
        socket = TSocket.TSocket(NODE_IP, NODE_PORT)
        socket.setTimeout(int(timeout_ms))
        transport = TTransport.TBufferedTransport(socket)
        protocol = TBinaryProtocol.TBinaryProtocol(transport)
        client = API_DIAG.Client(protocol)
        transport.open()
        return client, transport
    except Exception as e:
        log(f"Diag Thrift Connection Error: {e}", is_error=True)
        if transport: transport.close()
        return None, None


def _diag_call(method_name, mapper, error_label):
    client, transport = get_diag_client()
    if not client:
        return jsonify({"success": False, "message": "Diag service Unavailable"}), 503
    try:
        method = getattr(client, method_name)
        return jsonify(mapper(method()))
    except Exception as e:
        log(f"{error_label} Error: {e}", is_error=True)
        return jsonify({"success": False, "message": f"{error_label} failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/Diag/GetActiveNodes', methods=['POST'])
@app.route('/api/Diag/GetActiveNodes', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def diag_get_active_nodes():
    return _diag_call('GetActiveNodes', _diag.map_active_nodes, 'GetActiveNodes')


@app.route('/Diag/GetActiveTransactionsCount', methods=['POST'])
@app.route('/api/Diag/GetActiveTransactionsCount', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def diag_get_active_tx_count():
    return _diag_call('GetActiveTransactionsCount', _diag.map_active_transactions_count, 'GetActiveTransactionsCount')


@app.route('/Diag/GetNodeInfo', methods=['POST'])
@app.route('/api/Diag/GetNodeInfo', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def diag_get_node_info():
    return _diag_call('GetNodeInfo', _diag.map_node_info, 'GetNodeInfo')


@app.route('/Diag/GetSupply', methods=['POST'])
@app.route('/api/Diag/GetSupply', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def diag_get_supply():
    return _diag_call('GetSupply', _diag.map_supply, 'GetSupply')


# --- SMART CONTRACT API ---
from services import contracts as _contracts


def _decode_address(value, field_name):
    if not value:
        return None, (f"Missing {field_name}", 400)
    try:
        return base58.b58decode(value), None
    except Exception:
        return None, (f"{field_name} is not valid base58", 400)


@app.route('/SmartContract/Compile', methods=['POST'])
@app.route('/api/SmartContract/Compile', methods=['POST'])
@limiter.limit("2 per second; 60 per minute")
def smart_contract_compile():
    data = request.json or {}
    source = get_json_val(data, ['sourceCode', 'SourceCode'], '')
    if not source:
        return jsonify({"success": False, "message": "Missing sourceCode"}), 400

    client, transport = get_node_client(timeout_ms=30000)
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        return jsonify(_contracts.map_compile_result(client.SmartContractCompile(source)))
    except Exception as e:
        log(f"SmartContractCompile Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "SmartContractCompile failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/SmartContract/Get', methods=['POST'])
@app.route('/api/SmartContract/Get', methods=['POST'])
@limiter.limit("10 per second; 200 per minute")
def smart_contract_get():
    data = request.json or {}
    addr_b, err = _decode_address(get_json_val(data, ['address', 'Address']), 'address')
    if err: return jsonify({"success": False, "message": err[0]}), err[1]

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        return jsonify(_contracts.map_get(client.SmartContractGet(addr_b)))
    except Exception as e:
        log(f"SmartContractGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "SmartContractGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/SmartContract/Methods', methods=['POST'])
@app.route('/api/SmartContract/Methods', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def smart_contract_methods():
    data = request.json or {}
    bcos_raw = get_json_val(data, ['byteCodeObjects', 'ByteCodeObjects'], None)
    if not bcos_raw:
        return jsonify({"success": False, "message": "Missing byteCodeObjects"}), 400
    try:
        bcos = _contracts.build_byte_code_objects(api_types, bcos_raw)
    except (ValueError, AttributeError) as e:
        return jsonify({"success": False, "message": str(e)}), 400

    client, transport = get_node_client(timeout_ms=20000)
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        # Method name in the published Thrift API; falls back to executor-style
        # naming if a future node version renames it.
        if hasattr(client, 'SmartContractMethodsGet'):
            res = client.SmartContractMethodsGet(bcos)
        else:
            res = client.getContractMethods(bcos)
        return jsonify(_contracts.map_methods(res))
    except Exception as e:
        log(f"SmartContractMethodsGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "SmartContractMethodsGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/SmartContract/State', methods=['POST'])
@app.route('/api/SmartContract/State', methods=['POST'])
@limiter.limit("10 per second; 200 per minute")
def smart_contract_state():
    data = request.json or {}
    addr_b, err = _decode_address(get_json_val(data, ['address', 'Address']), 'address')
    if err: return jsonify({"success": False, "message": err[0]}), err[1]

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        res = client.SmartContractDataGet(addr_b)
        return jsonify(_contracts.map_state(res))
    except Exception as e:
        log(f"SmartContractDataGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "SmartContractDataGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/SmartContract/ListByWallet', methods=['POST'])
@app.route('/api/SmartContract/ListByWallet', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def smart_contract_list_by_wallet():
    data = request.json or {}
    addr_b, err = _decode_address(get_json_val(data, ['publicKey', 'PublicKey']), 'publicKey')
    if err: return jsonify({"success": False, "message": err[0]}), err[1]

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        return jsonify(_contracts.map_list_by_wallet(client.SmartContractsListGet(addr_b)))
    except Exception as e:
        log(f"SmartContractsListGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "SmartContractsListGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


def _common_smart_tx_setup(data, *, require_target):
    """Shared validation and fee/wallet lookup for Deploy and Execute."""
    pub = get_json_val(data, ['PublicKey', 'publicKey'], '')
    sig = get_json_val(data, ['TransactionSignature', 'signature'], '')
    if not pub:
        return None, ({"success": False, "message": "Missing PublicKey"}, 400)
    if not sig:
        return None, ({"success": False, "message": "Missing TransactionSignature"}, 400)
    sender_b, err = _decode_address(pub, 'PublicKey')
    if err: return None, ({"success": False, "message": err[0]}, err[1])
    try:
        sig_b = base58.b58decode(sig)
    except Exception:
        return None, ({"success": False, "message": "TransactionSignature is not valid base58"}, 400)

    target_b = b""
    if require_target:
        target_pub = get_json_val(data, ['target', 'Target', 'contractAddress', 'ContractAddress'], '')
        target_b, err = _decode_address(target_pub, 'target')
        if err: return None, ({"success": False, "message": err[0]}, err[1])

    user_data_payload = get_json_val(data, ['userData', 'UserData'], '')
    user_fields = b""
    if user_data_payload:
        try:
            user_fields = base58.b58decode(user_data_payload)
        except Exception:
            return None, ({"success": False, "message": "userData is not valid base58"}, 400)

    return (sender_b, target_b, sig_b, user_fields), None


def _execute_smart_tx(tx, rec_fee, inner_id, amount_str="0"):
    client, transport = get_node_client(timeout_ms=30000)
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        res = client.TransactionFlow(tx)
        status = getattr(res, 'status', None)
        success = getattr(status, 'code', 1) == 0
        tx_id = getattr(res, 'id', None)
        tx_id_str = (
            f"{getattr(tx_id, 'poolSeq', 0)}.{getattr(tx_id, 'index', 0) + 1}"
            if tx_id and hasattr(tx_id, 'poolSeq') else None
        )
        return jsonify({
            "amount": full_decimal(amount_str),
            "dataResponse": {
                "actualSum": 0, "publicKey": None, "recommendedFee": float(rec_fee),
                "smartContractResult": getattr(res, 'smart_contract_result', None),
                "transactionPackagedStr": None,
            },
            "actualSum": full_decimal(getattr(res, 'sum', amount_str)),
            "actualFee": full_decimal(getattr(res, 'fee', rec_fee)),
            "extraFee": None, "flowResult": None, "listItem": [], "listTransactionInfo": None,
            "message": None,
            "messageError": getattr(status, 'message', None) if not success else None,
            "success": success, "transactionId": tx_id_str,
            "transactionInfo": None, "transactionInnerId": inner_id, "blockId": 0,
        })
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/SmartContract/Deploy', methods=['POST'])
@app.route('/api/SmartContract/Deploy', methods=['POST'])
@limiter.limit("1 per 5 seconds; 30 per minute")
def smart_contract_deploy():
    data = request.json or {}
    parsed, err = _common_smart_tx_setup(data, require_target=False)
    if err:
        body, code = err
        return jsonify(body), code
    sender_b, target_b, sig_b, user_fields = parsed

    bcos_raw = get_json_val(data, ['byteCodeObjects', 'ByteCodeObjects'], None)
    if not bcos_raw:
        return jsonify({"success": False, "message": "Missing byteCodeObjects"}), 400
    source_code = get_json_val(data, ['sourceCode', 'SourceCode'], '')

    fee_str = get_json_val(data, ['feeAsString', 'Fee'], "0")
    try:
        fee_bits = fee_to_bits(float(fee_str)) if float(fee_str) > 0 else 0
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid feeAsString"}), 400

    client_ref, ref_transport = get_node_client()
    inner_id = 1
    rec_fee = 0.0
    if client_ref:
        try:
            wdata = getattr(client_ref.WalletDataGet(sender_b), 'walletData', None)
            inner_id = safe_int(getattr(wdata, 'lastTransactionId', 0)) + 1
            base_fee = bits_to_fee(getattr(client_ref.ActualFeeGet(0), 'fee', 0))
            rec_fee = float(base_fee) * float(get_fee_multiplier(len(user_fields) or 1))
        finally:
            if ref_transport and ref_transport.isOpen(): ref_transport.close()

    try:
        tx = _contracts.build_deploy_transaction(
            api_types,
            deployer_bytes=sender_b,
            target_bytes=target_b,
            byte_code_objects=bcos_raw,
            source_code=source_code,
            fee_bits=fee_bits,
            signature_bytes=sig_b,
            inner_id=inner_id,
            user_fields=user_fields,
        )
    except (ValueError, AttributeError) as e:
        return jsonify({"success": False, "message": str(e)}), 400

    try:
        return _execute_smart_tx(tx, rec_fee, inner_id)
    except Exception as e:
        log(f"SmartContract Deploy Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "SmartContract Deploy failed"}), 400


@app.route('/SmartContract/Execute', methods=['POST'])
@app.route('/api/SmartContract/Execute', methods=['POST'])
@limiter.limit("2 per second; 60 per minute")
def smart_contract_execute():
    data = request.json or {}
    parsed, err = _common_smart_tx_setup(data, require_target=True)
    if err:
        body, code = err
        return jsonify(body), code
    sender_b, contract_b, sig_b, user_fields = parsed

    method = get_json_val(data, ['method', 'Method'], '')
    if not method:
        return jsonify({"success": False, "message": "Missing method"}), 400
    params = get_json_val(data, ['params', 'Params'], []) or []
    forget_new_state = bool(get_json_val(data, ['forgetNewState', 'ForgetNewState'], False))

    fee_str = get_json_val(data, ['feeAsString', 'Fee'], "0")
    try:
        fee_bits = fee_to_bits(float(fee_str)) if float(fee_str) > 0 else 0
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid feeAsString"}), 400

    client_ref, ref_transport = get_node_client()
    inner_id = 1
    rec_fee = 0.0
    if client_ref:
        try:
            wdata = getattr(client_ref.WalletDataGet(sender_b), 'walletData', None)
            inner_id = safe_int(getattr(wdata, 'lastTransactionId', 0)) + 1
            base_fee = bits_to_fee(getattr(client_ref.ActualFeeGet(0), 'fee', 0))
            rec_fee = float(base_fee) * float(get_fee_multiplier(len(user_fields) or 1))
        finally:
            if ref_transport and ref_transport.isOpen(): ref_transport.close()

    try:
        tx = _contracts.build_execute_transaction(
            api_types,
            sender_bytes=sender_b,
            contract_bytes=contract_b,
            method=method,
            params=params,
            fee_bits=fee_bits,
            signature_bytes=sig_b,
            inner_id=inner_id,
            user_fields=user_fields,
            forget_new_state=forget_new_state,
        )
    except (ValueError, AttributeError) as e:
        return jsonify({"success": False, "message": str(e)}), 400

    try:
        return _execute_smart_tx(tx, rec_fee, inner_id)
    except Exception as e:
        log(f"SmartContract Execute Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "SmartContract Execute failed"}), 400


# --- TOKEN API ---
from services import tokens as _tokens


def _decode_token_address(value):
    if not value:
        return None, ("Missing token address", 400)
    try:
        return base58.b58decode(value), None
    except Exception:
        return None, ("token is not valid base58", 400)


@app.route('/Tokens/BalancesGet', methods=['POST'])
@app.route('/api/Tokens/BalancesGet', methods=['POST'])
@limiter.limit("10 per second; 200 per minute")
def tokens_balances_get():
    data = request.json or {}
    pub = get_json_val(data, ['publicKey', 'PublicKey'], '')
    if not pub:
        return jsonify({"success": False, "message": "Missing publicKey"}), 400
    try:
        pk_bytes = base58.b58decode(pub)
    except Exception:
        return jsonify({"success": False, "message": "publicKey is not valid base58"}), 400

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        return jsonify(_tokens.map_balances(client.TokenBalancesGet(pk_bytes)))
    except Exception as e:
        log(f"TokenBalancesGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "TokenBalancesGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/Tokens/TransfersGet', methods=['POST'])
@app.route('/api/Tokens/TransfersGet', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def tokens_transfers_get():
    data = request.json or {}
    token_b, err = _decode_token_address(get_json_val(data, ['token', 'Token'], ''))
    if err: return jsonify({"success": False, "message": err[0]}), err[1]
    offset = int(get_json_val(data, ['offset', 'Offset'], 0) or 0)
    limit = int(get_json_val(data, ['limit', 'Limit'], 50) or 50)

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        return jsonify(_tokens.map_transfers(client.TokenTransfersGet(token_b, offset, limit)))
    except Exception as e:
        log(f"TokenTransfersGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "TokenTransfersGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/Tokens/Info', methods=['POST'])
@app.route('/api/Tokens/Info', methods=['POST'])
@limiter.limit("10 per second; 200 per minute")
def tokens_info():
    data = request.json or {}
    token_b, err = _decode_token_address(get_json_val(data, ['token', 'Token'], ''))
    if err: return jsonify({"success": False, "message": err[0]}), err[1]

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        return jsonify(_tokens.map_info(client.TokenInfoGet(token_b)))
    except Exception as e:
        log(f"TokenInfoGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "TokenInfoGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/Tokens/HoldersGet', methods=['POST'])
@app.route('/api/Tokens/HoldersGet', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def tokens_holders_get():
    data = request.json or {}
    token_b, err = _decode_token_address(get_json_val(data, ['token', 'Token'], ''))
    if err: return jsonify({"success": False, "message": err[0]}), err[1]
    offset = int(get_json_val(data, ['offset', 'Offset'], 0) or 0)
    limit = int(get_json_val(data, ['limit', 'Limit'], 50) or 50)
    order = int(get_json_val(data, ['order', 'Order'], 0) or 0)
    desc = bool(get_json_val(data, ['desc', 'Desc'], True))

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        # Some node versions expose (token, offset, limit, order, desc); fall back
        # to the trailing-arg variant if signature differs.
        try:
            res = client.TokenHoldersGet(token_b, offset, limit, order, desc)
        except TypeError:
            res = client.TokenHoldersGet(token_b, offset, limit, order)
        return jsonify(_tokens.map_holders(res))
    except Exception as e:
        log(f"TokenHoldersGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "TokenHoldersGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/Tokens/TransactionsGet', methods=['POST'])
@app.route('/api/Tokens/TransactionsGet', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def tokens_transactions_get():
    data = request.json or {}
    token_b, err = _decode_token_address(get_json_val(data, ['token', 'Token'], ''))
    if err: return jsonify({"success": False, "message": err[0]}), err[1]
    offset = int(get_json_val(data, ['offset', 'Offset'], 0) or 0)
    limit = int(get_json_val(data, ['limit', 'Limit'], 50) or 50)

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503
    try:
        return jsonify(_tokens.map_token_transactions(client.TokenTransactionsGet(token_b, offset, limit)))
    except Exception as e:
        log(f"TokenTransactionsGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "TokenTransactionsGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


# --- WAIT HELPERS / LONG-POLL ---
from services import monitor as _monitor


@app.route('/Monitor/WaitForBlock', methods=['POST'])
@app.route('/api/Monitor/WaitForBlock', methods=['POST'])
@limiter.limit("2 per second; 60 per minute")
def wait_for_block():
    data = request.json or {}
    try:
        pool_number = int(get_json_val(data, ['poolNumber', 'PoolNumber'], 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid poolNumber"}), 400

    timeout_ms = _resolve_wait_timeout(data)
    # Add headroom so the socket waits slightly longer than the node-side block.
    client, transport = get_node_client(timeout_ms=timeout_ms + 5000)
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503

    try:
        res = client.WaitForBlock(pool_number)
        return jsonify(_monitor.map_block_response(res, pool_number))
    except Exception as e:
        log(f"WaitForBlock Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "WaitForBlock failed"}), 504
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/Monitor/WaitForSmartTransaction', methods=['POST'])
@app.route('/api/Monitor/WaitForSmartTransaction', methods=['POST'])
@limiter.limit("2 per second; 60 per minute")
def wait_for_smart_transaction():
    data = request.json or {}
    pub = get_json_val(data, ['publicKey', 'PublicKey', 'smartContract', 'SmartContract'], '')
    if not pub:
        return jsonify({"success": False, "message": "Missing publicKey"}), 400
    try:
        pk_bytes = base58.b58decode(pub)
    except Exception:
        return jsonify({"success": False, "message": "publicKey is not valid base58"}), 400

    timeout_ms = _resolve_wait_timeout(data)
    client, transport = get_node_client(timeout_ms=timeout_ms + 5000)
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503

    try:
        res = client.WaitForSmartTransaction(pk_bytes)
        return jsonify(_monitor.map_smart_tx_response(res))
    except Exception as e:
        log(f"WaitForSmartTransaction Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "WaitForSmartTransaction failed"}), 504
    finally:
        if transport and transport.isOpen(): transport.close()


@app.route('/Transaction/Result', methods=['POST'])
@app.route('/api/Transaction/Result', methods=['POST'])
@limiter.limit("5 per second; 100 per minute")
def transaction_result():
    data = request.json or {}
    tx_id_str = get_json_val(data, ['transactionId', 'TransactionId'], '')
    if not tx_id_str or '.' not in tx_id_str:
        return jsonify({"success": False, "message": "Invalid Transaction ID format"}), 400

    client, transport = get_node_client()
    if not client:
        return jsonify({"success": False, "message": "Node Unavailable"}), 503

    try:
        pool_seq_str, index_str = tx_id_str.split('.')
        tx_id_obj = api_types.TransactionId()
        tx_id_obj.poolSeq = int(pool_seq_str)
        tx_id_obj.index = int(index_str) - 1
        res = client.TransactionResultGet(tx_id_obj)
        return jsonify(_monitor.map_tx_result(res))
    except Exception as e:
        log(f"TransactionResultGet Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "TransactionResultGet failed"}), 400
    finally:
        if transport and transport.isOpen(): transport.close()


# --- USERFIELDS V1 CODEC (ArtVerse) ---
# Pure local helpers, no Thrift involved. See services/userfields.py for the wire format.
from services import userfields as _userfields


@app.route('/UserFields/Encode', methods=['POST'])
@app.route('/api/UserFields/Encode', methods=['POST'])
@limiter.limit("20 per second; 600 per minute")
def userfields_encode():
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Empty Body"}), 400
    try:
        raw = _userfields.encode(data)
        return jsonify({
            "success": True,
            "message": None,
            "userData": base58.b58encode(raw).decode('utf-8'),
            "sizeBytes": len(raw),
            "version": _userfields.VERSION,
        })
    except _userfields.UserFieldsError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        log(f"UserFields Encode Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to encode userFields"}), 400


@app.route('/UserFields/Decode', methods=['POST'])
@app.route('/api/UserFields/Decode', methods=['POST'])
@limiter.limit("20 per second; 600 per minute")
def userfields_decode():
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Empty Body"}), 400
    payload = get_json_val(data, ['userData', 'UserData'], '')
    if not payload:
        return jsonify({"success": False, "message": "Missing userData"}), 400
    try:
        raw = base58.b58decode(payload)
    except Exception:
        return jsonify({"success": False, "message": "userData is not valid base58"}), 400
    try:
        decoded = _userfields.decode(raw)
        return jsonify({"success": True, "message": None, "fields": decoded})
    except _userfields.UserFieldsError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        log(f"UserFields Decode Error: {e}", is_error=True)
        return jsonify({"success": False, "message": "Failed to decode userFields"}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

"""Long-poll wait helpers + Transaction/Result endpoint.

- /Monitor/WaitForBlock           — long-poll for next pool after obsoleteHash
- /Monitor/WaitForSmartTransaction — long-poll for the next smart contract tx
- /Transaction/Result             — fetch the result of a previous smart-tx
"""

from __future__ import annotations

import base58
from flask import Blueprint, jsonify, request

from services import monitor as _monitor


def make_blueprint(*, limiter, log, get_node_client, get_json_val,
                   resolve_wait_timeout, api_types) -> Blueprint:
    bp = Blueprint("monitor_wait", __name__)

    @bp.route("/Monitor/WaitForBlock", methods=["POST"])
    @bp.route("/api/Monitor/WaitForBlock", methods=["POST"])
    @limiter.limit("2 per second; 60 per minute")
    def wait_for_block():
        """Long-poll for the next pool after ``obsoleteHash`` (PoolHash bytes).

        Clients pass the last hash they have seen (base58); if missing or
        empty we fetch the current ``GetLastHash()`` so the call returns
        as soon as a new block is sealed.
        """
        data = request.json or {}
        obsolete_b58 = get_json_val(data, ["obsoleteHash", "ObsoleteHash", "hash", "Hash"], "")
        obsolete_bytes = b""
        if obsolete_b58:
            try:
                obsolete_bytes = base58.b58decode(obsolete_b58)
            except Exception:
                return jsonify({"success": False, "message": "obsoleteHash is not valid base58"}), 400

        timeout_ms = resolve_wait_timeout(data)
        client, transport = get_node_client(timeout_ms=timeout_ms + 5000)
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503

        try:
            if not obsolete_bytes:
                try:
                    obsolete_bytes = client.GetLastHash() or b""
                except Exception:
                    obsolete_bytes = b""
            res = client.WaitForBlock(obsolete_bytes)
            return jsonify(_monitor.map_block_response(res, obsolete_bytes))
        except Exception as e:
            log(f"WaitForBlock Error: {type(e).__name__}: {e!r}", is_error=True)
            return jsonify({"success": False, "message": f"WaitForBlock failed: {type(e).__name__}: {e}"}), 504
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/Monitor/WaitForSmartTransaction", methods=["POST"])
    @bp.route("/api/Monitor/WaitForSmartTransaction", methods=["POST"])
    @limiter.limit("2 per second; 60 per minute")
    def wait_for_smart_transaction():
        data = request.json or {}
        pub = get_json_val(data, ["publicKey", "PublicKey", "smartContract", "SmartContract",
                                  "address", "Address"], "")
        if not pub:
            return jsonify({"success": False, "message": "Missing publicKey"}), 400
        try:
            pk_bytes = base58.b58decode(pub)
        except Exception:
            return jsonify({"success": False, "message": "publicKey is not valid base58"}), 400

        timeout_ms = resolve_wait_timeout(data)
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
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/Transaction/Result", methods=["POST"])
    @bp.route("/api/Transaction/Result", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def transaction_result():
        data = request.json or {}
        tx_id_str = get_json_val(data, ["transactionId", "TransactionId"], "")
        if not tx_id_str or "." not in tx_id_str:
            return jsonify({"success": False, "message": "Invalid Transaction ID format"}), 400

        client, transport = get_node_client()
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503

        try:
            pool_seq_str, index_str = tx_id_str.split(".")
            tx_id_obj = api_types.TransactionId()
            tx_id_obj.poolSeq = int(pool_seq_str)
            tx_id_obj.index = int(index_str) - 1

            inner_id = None
            try:
                tx_get = client.TransactionGet(tx_id_obj)
                sealed = getattr(tx_get, "transaction", None)
                trxn = getattr(sealed, "trxn", None) if sealed else None
                inner_id = getattr(trxn, "id", None) if trxn else None
            except Exception as lookup_err:
                log(f"TransactionResult: lookup failed: {type(lookup_err).__name__}: {lookup_err!r}", is_error=True)

            if inner_id is None:
                return jsonify({
                    "success": False, "found": False,
                    "message": "Transaction not found or has no innerId — required for TransactionResultGet",
                }), 404

            res = client.TransactionResultGet(int(inner_id))
            return jsonify(_monitor.map_tx_result(res))
        except Exception as e:
            log(f"TransactionResultGet Error: {type(e).__name__}: {e!r}", is_error=True)
            return jsonify({"success": False, "message": f"TransactionResultGet failed: {type(e).__name__}: {e}"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    return bp

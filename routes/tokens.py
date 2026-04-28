"""Token API endpoints (Tokens/*).

References (CREDITSCOM/node):
- TokenBalancesGet      apihandler.cpp:1849
- TokenTransfersGet     apihandler.cpp:1855 (paged)
- TokenInfoGet          apihandler.cpp:1873
- TokenHoldersGet       apihandler.cpp:1881 (paged + sort + desc)
- TokenTransactionsGet  apihandler.cpp:1898 (paged)
"""

from __future__ import annotations

import base58
from flask import Blueprint, jsonify, request

from services import tokens as _tokens


def make_blueprint(*, limiter, log, get_node_client, get_json_val) -> Blueprint:
    bp = Blueprint("tokens", __name__)

    def _decode_token(value):
        if not value:
            return None, ("Missing token address", 400)
        try:
            return base58.b58decode(value), None
        except Exception:
            return None, ("token is not valid base58", 400)

    @bp.route("/Tokens/BalancesGet", methods=["POST"])
    @bp.route("/api/Tokens/BalancesGet", methods=["POST"])
    @limiter.limit("10 per second; 200 per minute")
    def balances_get():
        data = request.json or {}
        pub = get_json_val(data, ["publicKey", "PublicKey"], "")
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
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/Tokens/TransfersGet", methods=["POST"])
    @bp.route("/api/Tokens/TransfersGet", methods=["POST"])
    @limiter.limit("10 per second; 200 per minute")
    def transfers_get():
        data = request.json or {}
        token_b, err = _decode_token(get_json_val(data, ["token", "Token"], ""))
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            offset = int(get_json_val(data, ["offset", "Offset"], 0))
            limit = int(get_json_val(data, ["limit", "Limit"], 50))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "offset/limit must be integers"}), 400
        client, transport = get_node_client()
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503
        try:
            return jsonify(_tokens.map_transfers(client.TokenTransfersGet(token_b, offset, limit)))
        except Exception as e:
            log(f"TokenTransfersGet Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "TokenTransfersGet failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/Tokens/Info", methods=["POST"])
    @bp.route("/api/Tokens/Info", methods=["POST"])
    @limiter.limit("10 per second; 200 per minute")
    def info():
        data = request.json or {}
        token_b, err = _decode_token(get_json_val(data, ["token", "Token"], ""))
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        client, transport = get_node_client()
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503
        try:
            return jsonify(_tokens.map_info(client.TokenInfoGet(token_b)))
        except Exception as e:
            log(f"TokenInfoGet Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "TokenInfoGet failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/Tokens/HoldersGet", methods=["POST"])
    @bp.route("/api/Tokens/HoldersGet", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def holders_get():
        data = request.json or {}
        token_b, err = _decode_token(get_json_val(data, ["token", "Token"], ""))
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            offset = int(get_json_val(data, ["offset", "Offset"], 0))
            limit = int(get_json_val(data, ["limit", "Limit"], 50))
            order = int(get_json_val(data, ["order", "Order"], 0))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "offset/limit/order must be integers"}), 400
        desc = bool(get_json_val(data, ["desc", "Desc"], False))
        client, transport = get_node_client()
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503
        try:
            try:
                res = client.TokenHoldersGet(token_b, offset, limit, order, desc)
            except TypeError:
                # Older node builds may not have the desc parameter.
                res = client.TokenHoldersGet(token_b, offset, limit, order)
            return jsonify(_tokens.map_holders(res))
        except Exception as e:
            log(f"TokenHoldersGet Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "TokenHoldersGet failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/Tokens/TransactionsGet", methods=["POST"])
    @bp.route("/api/Tokens/TransactionsGet", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def transactions_get():
        data = request.json or {}
        token_b, err = _decode_token(get_json_val(data, ["token", "Token"], ""))
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]
        try:
            offset = int(get_json_val(data, ["offset", "Offset"], 0))
            limit = int(get_json_val(data, ["limit", "Limit"], 50))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "offset/limit must be integers"}), 400
        client, transport = get_node_client()
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503
        try:
            return jsonify(_tokens.map_token_transactions(
                client.TokenTransactionsGet(token_b, offset, limit)))
        except Exception as e:
            log(f"TokenTransactionsGet Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "TokenTransactionsGet failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    return bp

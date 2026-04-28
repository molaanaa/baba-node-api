"""Smart Contract API endpoints (SmartContract/*).

References (CREDITSCOM/node):
    SmartContractCompile      apihandler.cpp:2548
    SmartContractGet          apihandler.hpp:111
    ContractMethodsGet        apihandler.cpp:2571 (executor)
    ContractAllMethodsGet     apihandler.cpp:2571 (executor, by bytecode)
    SmartContractDataGet      apihandler.hpp:150 / apihandler.cpp:2611
    SmartContractsListGet     apihandler.hpp:113
    Deploy/Execute            built locally as Transaction + TransactionFlow

The node does not expose dedicated Deploy/Execute RPCs; the gateway shapes
a ``Transaction`` struct with the right type/smartContract fields and
forwards it via ``TransactionFlow`` exactly as the existing
/Transaction/Execute path does.
"""

from __future__ import annotations

import base58
from flask import Blueprint, jsonify, request

from services import contracts as _contracts


def _decode_address(value, field_name):
    if not value:
        return None, (f"Missing {field_name}", 400)
    try:
        return base58.b58decode(value), None
    except Exception:
        return None, (f"{field_name} is not valid base58", 400)


def make_blueprint(*, limiter, log, get_node_client, get_json_val,
                   safe_int, fee_to_bits, bits_to_fee, get_fee_multiplier,
                   full_decimal, thrift_ns) -> Blueprint:
    bp = Blueprint("smartcontract", __name__)

    def _common_smart_tx_setup(data, *, require_target):
        pub = get_json_val(data, ["PublicKey", "publicKey"], "")
        sig = get_json_val(data, ["TransactionSignature", "signature"], "")
        if not pub:
            return None, ({"success": False, "message": "Missing PublicKey"}, 400)
        if not sig:
            return None, ({"success": False, "message": "Missing TransactionSignature"}, 400)
        sender_b, err = _decode_address(pub, "PublicKey")
        if err:
            return None, ({"success": False, "message": err[0]}, err[1])
        try:
            sig_b = base58.b58decode(sig)
        except Exception:
            return None, ({"success": False, "message": "TransactionSignature is not valid base58"}, 400)

        target_b = b""
        if require_target:
            target_pub = get_json_val(data,
                                      ["target", "Target", "contractAddress", "ContractAddress"], "")
            target_b, err = _decode_address(target_pub, "target")
            if err:
                return None, ({"success": False, "message": err[0]}, err[1])

        user_data_payload = get_json_val(data, ["userData", "UserData"], "")
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
            status = getattr(res, "status", None)
            success = getattr(status, "code", 1) == 0
            tx_id = getattr(res, "id", None)
            tx_id_str = (
                f"{getattr(tx_id, 'poolSeq', 0)}.{getattr(tx_id, 'index', 0) + 1}"
                if tx_id and hasattr(tx_id, "poolSeq") else None
            )
            return jsonify({
                "amount": full_decimal(amount_str),
                "dataResponse": {
                    "actualSum": 0, "publicKey": None, "recommendedFee": float(rec_fee),
                    "smartContractResult": getattr(res, "smart_contract_result", None),
                    "transactionPackagedStr": None,
                },
                "actualSum": full_decimal(getattr(res, "sum", amount_str)),
                "actualFee": full_decimal(getattr(res, "fee", rec_fee)),
                "extraFee": None, "flowResult": None, "listItem": [], "listTransactionInfo": None,
                "message": None,
                "messageError": getattr(status, "message", None) if not success else None,
                "success": success, "transactionId": tx_id_str,
                "transactionInfo": None, "transactionInnerId": inner_id, "blockId": 0,
            })
        finally:
            if transport and transport.isOpen():
                transport.close()

    def _resolve_inner_id_and_fee(sender_b, user_fields):
        client_ref, ref_transport = get_node_client()
        inner_id = 1
        rec_fee = 0.0
        if client_ref:
            try:
                wdata = getattr(client_ref.WalletDataGet(sender_b), "walletData", None)
                inner_id = safe_int(getattr(wdata, "lastTransactionId", 0)) + 1
                base_fee = bits_to_fee(getattr(client_ref.ActualFeeGet(0), "fee", 0))
                rec_fee = float(base_fee) * float(get_fee_multiplier(len(user_fields) or 1))
            finally:
                if ref_transport and ref_transport.isOpen():
                    ref_transport.close()
        return inner_id, rec_fee

    @bp.route("/SmartContract/Compile", methods=["POST"])
    @bp.route("/api/SmartContract/Compile", methods=["POST"])
    @limiter.limit("2 per second; 60 per minute")
    def smart_contract_compile():
        data = request.json or {}
        source = get_json_val(data, ["sourceCode", "SourceCode"], "")
        if not source:
            return jsonify({"success": False, "message": "Missing sourceCode"}), 400

        # Compile dispatches to the executor service via the node and may
        # take tens of seconds for non-trivial sources; bump the socket
        # timeout. The sourceCode must include
        # `import com.credits.scapi.v0.SmartContract;` for the executor
        # to resolve the base class.
        client, transport = get_node_client(timeout_ms=120000)
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503
        try:
            return jsonify(_contracts.map_compile_result(client.SmartContractCompile(source)))
        except Exception as e:
            log(f"SmartContractCompile Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "SmartContractCompile failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/SmartContract/Get", methods=["POST"])
    @bp.route("/api/SmartContract/Get", methods=["POST"])
    @limiter.limit("10 per second; 200 per minute")
    def smart_contract_get():
        data = request.json or {}
        addr_b, err = _decode_address(get_json_val(data, ["address", "Address"]), "address")
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]

        client, transport = get_node_client()
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503
        try:
            return jsonify(_contracts.map_get(client.SmartContractGet(addr_b)))
        except Exception as e:
            log(f"SmartContractGet Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "SmartContractGet failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/SmartContract/Methods", methods=["POST"])
    @bp.route("/api/SmartContract/Methods", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def smart_contract_methods():
        """List the methods of a smart contract.

        Accepts either:
          * ``address``: base58 address of an already-deployed contract
            (calls ``ContractMethodsGet``); or
          * ``byteCodeObjects``: list of {name, byteCode(base64)} (calls
            ``ContractAllMethodsGet``) — useful right after a Compile and
            before a Deploy.
        """
        data = request.json or {}
        addr_raw = get_json_val(data, ["address", "Address"], "")
        bcos_raw = get_json_val(data, ["byteCodeObjects", "ByteCodeObjects"], None)
        if not addr_raw and not bcos_raw:
            return jsonify({"success": False,
                            "message": "Provide either 'address' or 'byteCodeObjects'"}), 400

        addr_b = None
        bcos = None
        if addr_raw:
            addr_b, err = _decode_address(addr_raw, "address")
            if err:
                return jsonify({"success": False, "message": err[0]}), err[1]
        else:
            try:
                bcos = _contracts.build_byte_code_objects(thrift_ns, bcos_raw)
            except (ValueError, AttributeError) as e:
                return jsonify({"success": False, "message": str(e)}), 400

        client, transport = get_node_client(timeout_ms=20000)
        if not client:
            return jsonify({"success": False, "message": "Node Unavailable"}), 503
        try:
            if addr_b is not None:
                res = client.ContractMethodsGet(addr_b)
            else:
                res = client.ContractAllMethodsGet(bcos)
            return jsonify(_contracts.map_methods(res))
        except Exception as e:
            log(f"ContractMethodsGet Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "ContractMethodsGet failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/SmartContract/State", methods=["POST"])
    @bp.route("/api/SmartContract/State", methods=["POST"])
    @limiter.limit("10 per second; 200 per minute")
    def smart_contract_state():
        data = request.json or {}
        addr_b, err = _decode_address(get_json_val(data, ["address", "Address"]), "address")
        if err:
            return jsonify({"success": False, "message": err[0]}), err[1]

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
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/SmartContract/ListByWallet", methods=["POST"])
    @bp.route("/api/SmartContract/ListByWallet", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def smart_contract_list_by_wallet():
        data = request.json or {}
        addr_b, err = _decode_address(get_json_val(data, ["publicKey", "PublicKey"]), "publicKey")
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
            res = client.SmartContractsListGet(addr_b, offset, limit)
            return jsonify(_contracts.map_list_by_wallet(res))
        except Exception as e:
            log(f"SmartContractsListGet Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "SmartContractsListGet failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/SmartContract/Deploy", methods=["POST"])
    @bp.route("/api/SmartContract/Deploy", methods=["POST"])
    @limiter.limit("1 per 5 seconds; 30 per minute")
    def smart_contract_deploy():
        data = request.json or {}
        parsed, err = _common_smart_tx_setup(data, require_target=False)
        if err:
            body, code = err
            return jsonify(body), code
        sender_b, target_b, sig_b, user_fields = parsed

        bcos_raw = get_json_val(data, ["byteCodeObjects", "ByteCodeObjects"], None)
        if not bcos_raw:
            return jsonify({"success": False, "message": "Missing byteCodeObjects"}), 400
        source_code = get_json_val(data, ["sourceCode", "SourceCode"], "")

        fee_str = get_json_val(data, ["feeAsString", "Fee"], "0")
        try:
            fee_bits = fee_to_bits(float(fee_str)) if float(fee_str) > 0 else 0
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Invalid feeAsString"}), 400

        inner_id, rec_fee = _resolve_inner_id_and_fee(sender_b, user_fields)

        try:
            tx = _contracts.build_deploy_transaction(
                thrift_ns,
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

    @bp.route("/SmartContract/Execute", methods=["POST"])
    @bp.route("/api/SmartContract/Execute", methods=["POST"])
    @limiter.limit("2 per second; 60 per minute")
    def smart_contract_execute():
        data = request.json or {}
        parsed, err = _common_smart_tx_setup(data, require_target=True)
        if err:
            body, code = err
            return jsonify(body), code
        sender_b, contract_b, sig_b, user_fields = parsed

        method = get_json_val(data, ["method", "Method"], "")
        if not method:
            return jsonify({"success": False, "message": "Missing method"}), 400
        params = get_json_val(data, ["params", "Params"], []) or []
        forget_new_state = bool(get_json_val(data, ["forgetNewState", "ForgetNewState"], False))

        fee_str = get_json_val(data, ["feeAsString", "Fee"], "0")
        try:
            fee_bits = fee_to_bits(float(fee_str)) if float(fee_str) > 0 else 0
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Invalid feeAsString"}), 400

        inner_id, rec_fee = _resolve_inner_id_and_fee(sender_b, user_fields)

        try:
            tx = _contracts.build_execute_transaction(
                thrift_ns,
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

    return bp

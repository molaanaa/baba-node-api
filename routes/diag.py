"""Diagnostic API endpoints (apidiag.thrift / API_DIAG service).

The diagnostic service uses a separate Thrift interface and on most node
builds is exposed on a dedicated port — set NODE_DIAG_PORT accordingly.
If the generated ``apidiag`` module is missing the endpoint answers 503.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from services import diag as _diag


def make_blueprint(*, limiter, log, node_ip, node_diag_port,
                   t_socket_factory, t_transport_factory, t_protocol_factory) -> Blueprint:
    """Build the /Diag/* blueprint.

    Thrift transport plumbing is injected as factories so this module has
    no top-level dependency on the generated stubs (which may be missing
    in fresh checkouts before ``thrift -r --gen py`` runs).
    """
    bp = Blueprint("diag", __name__)

    def _open_client(timeout_ms=10000):
        try:
            from apidiag import API_DIAG  # type: ignore
        except Exception as e:
            log(f"apidiag stubs unavailable: {e}", is_error=True)
            return None, None
        transport = None
        try:
            socket = t_socket_factory(node_ip, node_diag_port)
            socket.setTimeout(int(timeout_ms))
            transport = t_transport_factory(socket)
            protocol = t_protocol_factory(transport)
            client = API_DIAG.Client(protocol)
            transport.open()
            return client, transport
        except Exception as e:
            log(f"Diag Thrift Connection Error: {e}", is_error=True)
            if transport:
                transport.close()
            return None, None

    def _call(method_name, mapper, error_label, *args):
        client, transport = _open_client()
        if not client:
            return jsonify({"success": False, "message": "Diag service Unavailable"}), 503
        try:
            method = getattr(client, method_name)
            return jsonify(mapper(method(*args)))
        except Exception as e:
            log(f"{error_label} Error: {e}", is_error=True)
            return jsonify({"success": False, "message": f"{error_label} failed"}), 400
        finally:
            if transport and transport.isOpen():
                transport.close()

    @bp.route("/Diag/GetActiveNodes", methods=["POST"])
    @bp.route("/api/Diag/GetActiveNodes", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def get_active_nodes():
        return _call("GetActiveNodes", _diag.map_active_nodes, "GetActiveNodes")

    @bp.route("/Diag/GetActiveTransactionsCount", methods=["POST"])
    @bp.route("/api/Diag/GetActiveTransactionsCount", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def get_active_tx_count():
        return _call("GetActiveTransactionsCount", _diag.map_active_transactions_count,
                     "GetActiveTransactionsCount")

    @bp.route("/Diag/GetNodeInfo", methods=["POST"])
    @bp.route("/api/Diag/GetNodeInfo", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def get_node_info():
        try:
            from apidiag.ttypes import NodeInfoRequest  # type: ignore
            req = NodeInfoRequest()
        except Exception as e:
            log(f"NodeInfoRequest stub unavailable: {e}", is_error=True)
            return jsonify({"success": False, "message": "Diag service Unavailable"}), 503
        return _call("GetNodeInfo", _diag.map_node_info, "GetNodeInfo", req)

    @bp.route("/Diag/GetSupply", methods=["POST"])
    @bp.route("/api/Diag/GetSupply", methods=["POST"])
    @limiter.limit("5 per second; 100 per minute")
    def get_supply():
        return _call("GetSupply", _diag.map_supply, "GetSupply")

    return bp

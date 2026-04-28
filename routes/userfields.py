"""UserFields v1 codec endpoints — pure local helpers, no Thrift involved.

Wire format documented in ``services/userfields.py``.
"""

from __future__ import annotations

import base58
from flask import Blueprint, jsonify, request

from services import userfields as _userfields


def make_blueprint(*, limiter, log, get_json_val) -> Blueprint:
    bp = Blueprint("userfields", __name__)

    @bp.route("/UserFields/Encode", methods=["POST"])
    @bp.route("/api/UserFields/Encode", methods=["POST"])
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
                "userData": base58.b58encode(raw).decode("utf-8"),
                "sizeBytes": len(raw),
                "version": _userfields.VERSION,
            })
        except _userfields.UserFieldsError as e:
            return jsonify({"success": False, "message": str(e)}), 400
        except Exception as e:
            log(f"UserFields Encode Error: {e}", is_error=True)
            return jsonify({"success": False, "message": "Failed to encode userFields"}), 400

    @bp.route("/UserFields/Decode", methods=["POST"])
    @bp.route("/api/UserFields/Decode", methods=["POST"])
    @limiter.limit("20 per second; 600 per minute")
    def userfields_decode():
        data = request.json
        if not data:
            return jsonify({"success": False, "message": "Empty Body"}), 400
        payload = get_json_val(data, ["userData", "UserData"], "")
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

    return bp

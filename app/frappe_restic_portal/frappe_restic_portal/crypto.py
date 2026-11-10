"""Verify Press-only Ed25519 envelopes, domain separated from existing restore transport."""
import base64
import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOMAIN = b"FRAPPE_RESTIC_SITE_PORTAL_V1\n"


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def verify_envelope(envelope, pubkey):
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ValueError("Invalid signed envelope")
    if not pubkey.is_file() or pubkey.is_symlink() or pubkey.stat().st_size > 4096:
        raise ValueError("Trusted Press public key unavailable")
    try:
        sig = base64.b64decode(envelope["signature"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Malformed signature") from exc
    if len(sig) != 64:
        raise ValueError("Wrong signature length")
    with tempfile.TemporaryDirectory() as tmp:
        body = Path(tmp) / "message"
        signature = Path(tmp) / "signature"
        body.write_bytes(DOMAIN + canonical(envelope["payload"]))
        signature.write_bytes(sig)
        result = subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin",
            "-inkey", str(pubkey), "-in", str(body), "-sigfile", str(signature)],
            capture_output=True, timeout=10, check=False)
        if result.returncode:
            raise ValueError("Untrusted platform signature")
    return envelope["payload"]


def validate_payload(payload, site, now=None):
    if not isinstance(payload, dict) or set(payload) != {"format", "request_id", "action", "site", "created_at", "data"}:
        raise ValueError("Unexpected payload fields")
    if payload["format"] != "restic-site-portal-v1" or payload["site"] != site:
        raise ValueError("Wrong site or protocol")
    if not re.fullmatch(r"[0-9a-f]{32}", str(payload["request_id"])):
        raise ValueError("Invalid message ID")
    if payload["action"] not in {"inventory", "list", "status"} or not isinstance(payload["data"], dict):
        raise ValueError("Unsupported platform request")
    stamp = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    elapsed = (now or datetime.now(timezone.utc)) - stamp.astimezone(timezone.utc)
    if elapsed > timedelta(minutes=5) or elapsed < -timedelta(minutes=1):
        raise ValueError("Message expired or from the future")
    return payload

"""
The local-auth-token fix SECURITY.md flagged: right now the backend accepts
a connection from any local process on this Mac, no auth at all. Not a
credential Joshua configures (that's ANTHROPIC_API_KEY, in .env) — a
machine-generated local secret, shared between the backend and the desktop
app via a file only this device's processes can read.

Deliberately scoped to today's real threat model (one machine, no cloud
sync, a loopback-only backend) — this is not the per-device Keychain/Secure
Enclave keypair auth TECH_STACK.md eventually wants for multi-device trust,
which is a different, larger problem for a different day.
"""

import secrets
from pathlib import Path

TOKEN_PATH = Path(__file__).parent.parent / "data" / "auth_token"


def get_or_create_token() -> str:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token)
    return token

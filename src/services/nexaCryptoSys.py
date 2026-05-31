import base64
import secrets
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes


def generate_keypair():
    """Generate a fresh RSA-2048 keypair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key


def public_key_to_pem(private_key) -> str:
    """Export the public key as a PEM string."""
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def private_key_to_pem(private_key) -> str:
    """Export the private key as a PEM string (stored locally, never transmitted)."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def build_auth_token(name: str, public_key_pem: str) -> str:
    """
    Build an authorization token in the format:
      {keyStartIndex}-{nameAsBase64}-{RSAPublicKey}

    keyStartIndex is the character offset where the RSA key begins,
    allowing the receiving party to delimit the fields unambiguously.
    Used by both client and server to build their respective tokens.
    """
    name_b64 = base64.b64encode(name.encode("utf-8")).decode("utf-8")
    prefix = f"0-{name_b64}-"
    key_start_index = len(prefix)
    token = f"{key_start_index}-{name_b64}-{public_key_pem}"
    return token


def parse_auth_token(token: str) -> tuple[str, str]:
    """
    Parse an authorization token issued by either side.
    Returns (name, public_key_pem).
    Raises ValueError on malformed input.
    Used by both client and server to read the other party's token.
    """
    try:
        parts = token.split("-", 2)
        if len(parts) != 3:
            raise ValueError("Token must have exactly three dash-delimited fields.")
        key_start_index = int(parts[0])
        name_b64 = parts[1]
        name = base64.b64decode(name_b64).decode("utf-8")
        public_key_pem = token[key_start_index:]
        return name, public_key_pem
    except Exception as e:
        raise ValueError(f"Malformed token: {e}")
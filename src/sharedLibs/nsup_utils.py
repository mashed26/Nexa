"""
NSUP-utils.py
Shared cryptographic and NSUP utility library for Nexa and Nexa Desktop.

Functions:
    getInfoFromAuthToken(authTokenString)
    constructKeyPair(name)
    encryptFileWithAuthToken(filePath, authToken)
    decryptNSUPFile(filePath, privateKeyPem)
    buildHWID()
    verifyHWID(hwid)
"""

import os
import base64
import hashlib
import platform
import uuid
import json
from pathlib import Path
from typing import List

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.asymmetric.padding import OAEP, MGF1
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ── Auth Token Utilities ──────────────────────────────────────────────────────

def getInfoFromAuthToken(authTokenString: str) -> List[str]:
    """
    Returns data about an auth token as:
        ["nameDecodedFromBase64", "publicKeyPem"]

    Raises ValueError if the token is malformed.
    """
    try:
        # Find the first dash to get keyStartIndex
        first_dash = authTokenString.index("-")
        key_start_index = int(authTokenString[:first_dash])

        # Find the second dash to delimit the name field
        second_dash = authTokenString.index("-", first_dash + 1)
        name_b64 = authTokenString[first_dash + 1:second_dash]
        name = base64.b64decode(name_b64.encode("utf-8")).decode("utf-8")

        # keyStartIndex may point at the trailing separator '-' before the PEM
        # (as Nexa does), or directly at the PEM header itself.
        # A valid PEM header starts with '-----BEGIN', so check for that explicitly.
        pem_start = key_start_index
        if not authTokenString[pem_start:].startswith('-----BEGIN'):
            pem_start += 1
        public_key_pem = authTokenString[pem_start:]
        return [name, public_key_pem]
    except Exception as e:
        raise ValueError(f"Malformed auth token: {e}")


def constructKeyPair(name: str) -> List[str]:
    """
    Generates a fresh RSA-2048 keypair and constructs an auth token.
    Returns:
        ["authToken", "privateKeyPem"]

    The auth token format is:
        {keyStartIndex}-{nameAsBase64}-{publicKeyPem}
    """
    # Generate keypair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Export public key as PEM
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    # Export private key as PEM
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # Build auth token — PEM is embedded raw, name is base64-encoded.
    # keyStartIndex marks where the PEM begins so the receiver can slice it cleanly.
    # We compute the index iteratively since the index length affects itself.
    name_b64 = base64.b64encode(name.encode("utf-8")).decode("utf-8")
    # Estimate prefix length, then correct for the actual digit count
    for digits in range(1, 6):  # handles index up to 99999
        candidate_index = digits + 1 + len(name_b64) + 1  # "{index}-{name_b64}-"
        if len(str(candidate_index)) == digits:
            key_start_index = candidate_index
            break
    auth_token = f"{key_start_index}-{name_b64}-{public_key_pem}"

    return [auth_token, private_key_pem]


# ── Encryption / Decryption ───────────────────────────────────────────────────

def encryptFileWithAuthToken(filePath: Path, authToken: str) -> Path:
    """
    Encrypts a file using hybrid RSA+AES-GCM encryption.

    Process:
        1. Extract the RSA public key from the auth token.
        2. Generate a random 32-byte ephemeral AES key.
        3. Encrypt the file contents with AES-GCM using the ephemeral key.
        4. Encrypt the ephemeral AES key with the RSA public key.
        5. Write a .nsup file containing both.

    The output file is written to the same directory as the input,
    with the same name and a .nsup extension appended.

    Returns the Path of the written .nsup file.
    Raises ValueError if the auth token is malformed.
    Raises FileNotFoundError if the input file does not exist.
    """
    filePath = Path(filePath)
    if not filePath.exists():
        raise FileNotFoundError(f"File not found: {filePath}")

    # Extract public key from token
    _, public_key_pem = getInfoFromAuthToken(authToken)
    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))

    # Read file contents
    file_contents = filePath.read_bytes()

    # Generate ephemeral AES-256 key and nonce
    aes_key = os.urandom(32)
    nonce = os.urandom(12)

    # Encrypt file contents with AES-GCM
    aesgcm = AESGCM(aes_key)
    encrypted_contents = aesgcm.encrypt(nonce, file_contents, None)

    # Encrypt the AES key with RSA public key (OAEP + SHA-256)
    encrypted_aes_key = public_key.encrypt(
        aes_key,
        OAEP(
            mgf=MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    # Bundle: base64-encode both for safe JSON storage
    bundle = {
        "encryptedKey": base64.b64encode(encrypted_aes_key).decode("utf-8"),
        "nonce": base64.b64encode(nonce).decode("utf-8"),
        "payload": base64.b64encode(encrypted_contents).decode("utf-8"),
    }

    # Write .nsup file
    output_path = filePath.parent / (filePath.name + ".nsup")
    output_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    return output_path


def decryptNSUPFile(filePath: Path, privateKeyPem: str) -> bytes:
    """
    Decrypts a .nsup file produced by encryptFileWithAuthToken.

    Process:
        1. Load the bundle from the .nsup file.
        2. Decrypt the ephemeral AES key using the RSA private key.
        3. Decrypt the payload using the recovered AES key and nonce.

    Returns the decrypted file contents as bytes.
    Raises ValueError if the file is malformed or decryption fails.
    """
    filePath = Path(filePath)
    if not filePath.exists():
        raise FileNotFoundError(f"File not found: {filePath}")

    try:
        bundle = json.loads(filePath.read_text(encoding="utf-8"))
        encrypted_aes_key = base64.b64decode(bundle["encryptedKey"])
        nonce = base64.b64decode(bundle["nonce"])
        encrypted_contents = base64.b64decode(bundle["payload"])
    except (json.JSONDecodeError, KeyError) as e:
        raise ValueError(f"Malformed .nsup bundle: {e}")

    # Load private key
    try:
        private_key = serialization.load_pem_private_key(
            privateKeyPem.encode("utf-8"),
            password=None
        )
    except Exception as e:
        raise ValueError(f"Failed to load private key: {e}")

    # Decrypt AES key with RSA private key
    try:
        aes_key = private_key.decrypt(
            encrypted_aes_key,
            OAEP(
                mgf=MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
    except Exception as e:
        raise ValueError(f"Failed to decrypt AES key: {e}")

    # Decrypt payload with AES-GCM
    try:
        aesgcm = AESGCM(aes_key)
        return aesgcm.decrypt(nonce, encrypted_contents, None)
    except Exception as e:
        raise ValueError(f"Failed to decrypt payload: {e}")


# ── HWID Utilities ────────────────────────────────────────────────────────────

def buildHWID() -> str:
    """
    Collects hardware information and returns a SHA-256 hash
    as a hex string. Used to verify packages originate from
    the expected machine.
    """
    system    = platform.system()
    node      = platform.node()
    release   = platform.release()
    version   = platform.version()
    machine   = platform.machine()
    processor = platform.processor()
    mac       = ':'.join([
        '{:02x}'.format((uuid.getnode() >> elements) & 0xff)
        for elements in range(0, 2*6, 8)
    ][::-1])

    hardware_info = f"{system}-{node}-{release}-{version}-{machine}-{processor}-{mac}"
    return hashlib.sha256(hardware_info.encode()).hexdigest()


def verifyHWID(hwid: str) -> bool:
    """
    Verifies a provided HWID against the current machine.
    Returns True if the HWID matches, False otherwise.
    """
    return hwid == buildHWID()
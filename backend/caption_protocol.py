"""Authenticated captions for hidden LiveKit agents (whose wire sender is empty).

The worker generates a fresh P-256 key per claimed session. Only its public JWK is
bound to that session through the authenticated worker claim. The private key lives
only in worker memory; neither browser receives it. WebCrypto verifies signatures
over the exact UTF-8 payload bytes, not a reserialized JSON object.
"""
import base64
import json
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def encoded(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def validate_public_key(jwk):
    if set(jwk) != {"kty", "crv", "x", "y"} or jwk["kty"] != "EC" or jwk["crv"] != "P-256":
        raise ValueError("Invalid caption verification key")
    try:
        values = [base64.b64decode(jwk[name] + "=", altchars=b"-_", validate=True) for name in ("x", "y")]
        if any(len(value) != 32 for value in values):
            raise ValueError()
        ec.EllipticCurvePublicNumbers(int.from_bytes(values[0], "big"), int.from_bytes(values[1], "big"), ec.SECP256R1()).public_key()
    except Exception:
        raise ValueError("Invalid caption verification key") from None
    return dict(jwk)


class CaptionSigner:
    def __init__(self):
        self._key = ec.generate_private_key(ec.SECP256R1())
        numbers = self._key.public_key().public_numbers()
        self.public_key = {"kty": "EC", "crv": "P-256", "x": encoded(numbers.x.to_bytes(32, "big")),
                           "y": encoded(numbers.y.to_bytes(32, "big"))}

    def envelope(self, event):
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
        der = self._key.sign(payload, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        # WebCrypto expects IEEE-P1363 r||s, not ASN.1/DER.
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return {"v": 1, "payload": encoded(payload), "signature": encoded(signature)}

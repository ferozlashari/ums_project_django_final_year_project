"""
Digital Student ID - signed QR verification.

The QR code printed on a student's digital ID never encodes raw personal
data. It encodes a signed token (HMAC'd with Django's SECRET_KEY via
`django.core.signing`) that identifies *which* student record to look up.
Whoever scans it only ever sees data re-fetched live from the database at
verification time - so a suspended/withdrawn student's card correctly
shows as not-active even if the physical/QR card itself was issued while
they were still active. The token cannot be forged or edited (tampering
invalidates the signature), but it is not a secret in itself - it grants
no access beyond "view this student's public verification summary".
"""
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired

SALT = "ums-digital-student-id-v1"
signer = signing.TimestampSigner(salt=SALT)


def issue_token(student):
    """Return a signed, URL-safe token identifying this student."""
    payload = signing.dumps({"sid": student.pk}, salt=SALT)
    return payload


def verify_token(token, max_age_seconds=None):
    """Decode a token issued by issue_token(). Returns the student's pk on
    success, or None if the token is missing, tampered with, or expired.
    Never raises - callers always get a clean None on any failure."""
    if not token:
        return None
    try:
        data = signing.loads(token, salt=SALT, max_age=max_age_seconds)
        return data.get("sid")
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None


def qr_data_uri(text):
    """Render `text` as a QR code PNG and return it as a base64 data: URI,
    so it can go straight into an <img src="..."> with no extra route or
    on-disk file. Returns None if the qrcode library isn't available."""
    try:
        import qrcode
        import io
        import base64

        img = qrcode.make(text, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return None

"""Quick test to verify Kalshi API key + PEM authentication works."""

import sys
import time
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

try:
    import httpx
except ImportError:
    print("Install httpx first: pip install httpx")
    sys.exit(1)


def test_auth(key_id: str, pem_path: str, env: str = "prod"):
    base_url = (
        "https://demo-api.kalshi.co/trade-api/v2"
        if env == "demo"
        else "https://api.elections.kalshi.com/trade-api/v2"
    )

    # Load key
    with open(pem_path, "r") as f:
        pem_data = f.read()

    try:
        private_key = serialization.load_pem_private_key(pem_data.encode(), password=None)
        print(f"[OK] PEM loaded from {pem_path}")
    except Exception as e:
        print(f"[FAIL] Cannot load PEM: {e}")
        return

    # Sign — Kalshi requires full path including /trade-api/v2
    path = "/portfolio/balance"
    full_path = "/trade-api/v2" + path
    timestamp_ms = str(int(time.time() * 1000))
    message = f"{timestamp_ms}GET{full_path}".encode()

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(signature).decode()

    headers = {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    }

    print(f"\nTesting against: {base_url}")
    print(f"Key ID: {key_id}")

    # Test balance endpoint
    resp = httpx.get(f"{base_url}{path}", headers=headers, timeout=10)
    print(f"\nGET {path} -> {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        balance = data.get("balance", 0) / 100
        pv = data.get("portfolio_value", 0) / 100
        print(f"[OK] Balance: ${balance:.2f}, Portfolio: ${pv:.2f}")
    elif resp.status_code == 401:
        print(f"[FAIL] 401 Unauthorized — key/PEM mismatch or wrong environment")
        print(f"  Response: {resp.text[:200]}")
    else:
        print(f"[FAIL] {resp.status_code}: {resp.text[:200]}")

    # Test public endpoint (should always work)
    resp2 = httpx.get(f"{base_url}/markets?limit=1", headers=headers, timeout=10)
    print(f"\nGET /markets?limit=1 -> {resp2.status_code}")
    if resp2.status_code == 200:
        markets = resp2.json().get("markets", [])
        print(f"[OK] Found {len(markets)} market(s)")
    else:
        print(f"[FAIL] {resp2.status_code}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_auth.py <KEY_ID> <PEM_PATH> [prod|demo]")
        print("Example: python scripts/test_auth.py abc-123 config/kalshi-key.pem prod")
        sys.exit(1)

    key_id = sys.argv[1]
    pem_path = sys.argv[2]
    env = sys.argv[3] if len(sys.argv) > 3 else "prod"
    test_auth(key_id, pem_path, env)

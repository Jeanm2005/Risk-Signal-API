"""
Mint an API key for the Risk Signal API.

Generates a random key, stores only its SHA-256 in api_keys,
and prints the raw key once. It cannot be recovered afterward.
"""
import hashlib
import os
import secrets
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def _dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    return ("host=localhost port=5432 dbname=risk_signal_db "
            "user=postgres password=" + os.environ.get("PGPASSWORD", "postgres"))

def main():
    owner = sys.argv[1] if len(sys.argv) > 1 else "default"
    raw = "rsk_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    conn = psycopg2.connect(_dsn())
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO api_keys (key_hash, owner) VALUES (%s, %s) RETURNING id",
                (key_hash, owner),
            )
            key_id = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"Created API key id={key_id} for owner '{owner}'.")
    print("\n  " + raw + "\n")
    print("Store it now -- only its SHA-256 hash is saved; it cannot be recovered.")
    print("Use it as the  X-API-Key  header when calling /score.")

if __name__ == "__main__":
    main()
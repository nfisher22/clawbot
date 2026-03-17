import os
import subprocess
import hvac
from dotenv import load_dotenv

VAULT_ADDR = "http://127.0.0.1:8200"
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
SECRET_PATH = "clawbot/secrets"

def get_secrets():
    try:
        client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
        if not client.is_authenticated():
            raise Exception("Vault authentication failed")
        secret = client.read(SECRET_PATH)
        if not secret:
            raise Exception("No secrets found at path: " + SECRET_PATH)
        data = secret["data"]
        # Inject into environment
        for key, value in data.items():
            os.environ[key] = str(value)
        return data
    except Exception as e:
        print(f"Vault unavailable ({e}), falling back to .env")
        load_dotenv("/opt/clawbot/app/.env")
        return {}

if __name__ == "__main__":
    secrets = get_secrets()
    print("Secrets loaded:", list(secrets.keys()))

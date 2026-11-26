"""Generate local secrets for the isolated PostgreSQL demonstration stack."""
import os
from pathlib import Path
import secrets


path = Path(__file__).resolve().parents[1] / ".env.postgres"
names = ("VYRNEXIS_POSTGRES_PASSWORD", "VYRNEXIS_REDIS_PASSWORD", "VYRNEXIS_POSTGRES_JWT_SECRET")
try:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except FileExistsError:
    print("Local PostgreSQL stack configuration already exists.")
else:
    with os.fdopen(fd, "w", encoding="utf-8") as config:
        config.writelines(f"{name}={secrets.token_urlsafe(48)}\n" for name in names)
    print("Generated local PostgreSQL stack configuration.")

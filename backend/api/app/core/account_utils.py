from __future__ import annotations

import re
import secrets
import string


def slugify_login_username(value: str, fallback: str = "tenant_admin") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or fallback


def generate_temporary_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    characters = [secrets.choice(string.ascii_letters), secrets.choice(string.digits)]
    characters.extend(secrets.choice(alphabet) for _ in range(max(12, length) - 2))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)

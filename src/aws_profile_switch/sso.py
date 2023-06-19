"""Check the AWS CLI's cached IAM Identity Center (SSO) token for a profile.

`aws sso login` stores the token in ~/.aws/sso/cache/<sha1>.json, where the
hash is taken over the sso-session name (profiles that use `sso_session`) or
over the start URL (legacy profiles with `sso_start_url`). The file holds
`expiresAt` for the access token and, for sso-session logins, a refresh token
that the CLI and SDKs use to renew the access token without a browser.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from .profiles import AwsConfig, Profile, home

VALID, REFRESHABLE, EXPIRED, MISSING = "valid", "refreshable", "expired", "missing"


@dataclass
class TokenStatus:
    state: str
    expires_at: Optional[datetime] = None

    @property
    def needs_login(self) -> bool:
        return self.state in (EXPIRED, MISSING)


def cache_dir(env: Mapping[str, str]) -> Path:
    return Path(env.get("AWSP_SSO_CACHE_DIR") or home(env) / ".aws" / "sso" / "cache")


def cache_key(profile: Profile) -> Optional[str]:
    """The text the AWS CLI hashes to name this profile's token cache file."""
    return profile.settings.get("sso_session") or profile.settings.get("sso_start_url")


def cache_file(profile: Profile, env: Mapping[str, str]) -> Optional[Path]:
    key = cache_key(profile)
    if not key:
        return None
    return cache_dir(env) / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def parse_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    for suffix in ("UTC", "Z"):
        if text.endswith(suffix):
            text = text[: -len(suffix)] + "+00:00"
            break
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def token_status(profile: Profile, env: Mapping[str, str], now: datetime) -> TokenStatus:
    path = cache_file(profile, env)
    if path is None or not path.is_file():
        return TokenStatus(MISSING)
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return TokenStatus(MISSING)
    if not isinstance(token, dict) or not token.get("accessToken"):
        return TokenStatus(MISSING)
    expires_at = parse_time(token.get("expiresAt"))
    if expires_at is None:
        return TokenStatus(MISSING)
    if expires_at > now:
        return TokenStatus(VALID, expires_at)
    registration = parse_time(token.get("registrationExpiresAt"))
    if token.get("refreshToken") and registration and registration > now:
        return TokenStatus(REFRESHABLE, expires_at)
    return TokenStatus(EXPIRED, expires_at)


def status_for(config: AwsConfig, name: str, env: Mapping[str, str], now: datetime):
    """(SSO base profile, token status) for a profile, or (None, None) if it does not use SSO."""
    base = config.sso_base(name)
    if base is None:
        return None, None
    return base, token_status(base, env, now)

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

CONFIG = """\
[default]
region = us-east-1

[profile dev-admin]
sso_session = acme
sso_account_id = 111111111111
sso_role_name = AdministratorAccess
region = eu-west-1

[profile prod-readonly]
sso_session = acme
sso_account_id = 123456789012
sso_role_name = ReadOnlyAccess

[profile prod-admin]
sso_session = acme
sso_account_id = 123456789012
sso_role_name = AdministratorAccess

[profile prod-audit]
role_arn = arn:aws:iam::123456789012:role/Audit
source_profile = prod-readonly

[profile legacy-sso]
sso_start_url = https://legacy.awsapps.com/start
sso_region = us-east-1
sso_account_id = 222222222222
sso_role_name = Dev

[profile sandbox]
credential_process = /usr/local/bin/fetch-creds sandbox
s3 =
    max_concurrent_requests = 20

[sso-session acme]
sso_start_url = https://acme.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access

[services local]
s3 =
    endpoint_url = http://localhost:4566
"""

CREDENTIALS = """\
[default]
aws_access_key_id = testing
aws_secret_access_key = testing

[ci-deployer]
aws_access_key_id = testing
aws_secret_access_key = testing
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A complete fake environment rooted in tmp_path.

    The AWS config, credentials, SSO token cache and awsp history all live in
    the temporary directory. HOME is redirected too, so even a code path that
    forgot to honour the override variables could not reach the real ~/.aws.
    """
    aws = tmp_path / "aws"
    aws.mkdir()
    (aws / "config").write_text(CONFIG)
    (aws / "credentials").write_text(CREDENTIALS)
    values = {
        "HOME": str(tmp_path / "home"),
        "AWS_CONFIG_FILE": str(aws / "config"),
        "AWS_SHARED_CREDENTIALS_FILE": str(aws / "credentials"),
        "AWSP_SSO_CACHE_DIR": str(aws / "sso" / "cache"),
        "AWSP_STATE_DIR": str(tmp_path / "state"),
        "SHELL": "/bin/zsh",
    }
    for var in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def write_token(env, key, *, expires_in=3600, refreshable=False, now=NOW):
    """Create a token cache file the way `aws sso login` names it."""
    cache = __import__("pathlib").Path(env["AWSP_SSO_CACHE_DIR"])
    cache.mkdir(parents=True, exist_ok=True)
    token = {
        "accessToken": "fake-token",
        "expiresAt": (now + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if refreshable:
        token["refreshToken"] = "fake-refresh"
        token["registrationExpiresAt"] = (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = cache / (hashlib.sha1(key.encode()).hexdigest() + ".json")
    path.write_text(json.dumps(token))
    return path

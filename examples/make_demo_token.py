"""Write a fake SSO token cache file so the example profiles look logged in.

    python examples/make_demo_token.py /tmp/awsp-demo/sso
    export AWSP_SSO_CACHE_DIR=/tmp/awsp-demo/sso

The file is named the way `aws sso login` names it (SHA-1 of the sso-session
name, "acme" in examples/config) and expires in eight hours. The token inside
is a placeholder and is useless against AWS. Never point this at ~/.aws.
"""

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    cache = Path(sys.argv[1])
    cache.mkdir(parents=True, exist_ok=True)
    expires = datetime.now(timezone.utc) + timedelta(hours=8)
    token = {
        "startUrl": "https://acme.awsapps.com/start",
        "region": "us-east-1",
        "accessToken": "not-a-real-token",
        "expiresAt": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = cache / (hashlib.sha1(b"acme").hexdigest() + ".json")
    path.write_text(json.dumps(token, indent=2))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

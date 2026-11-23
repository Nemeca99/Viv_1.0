"""One-time interactive user OAuth authorization for the archive uploader."""
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.google_drive_api_uploader import CLIENT_SECRET_PATH, SCOPES, TOKEN_PATH


def main() -> int:
    if not CLIENT_SECRET_PATH.is_file():
        raise SystemExit(f"Missing OAuth desktop client file: {CLIENT_SECRET_PATH}")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Wrote user OAuth token: {TOKEN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

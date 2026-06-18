#!/usr/bin/env python
"""
Setup script for Outlook/Hotmail Microsoft Graph API integration.

This script handles the OAuth flow for Microsoft Graph access by:
1. Creating a .secrets directory if it doesn't exist
2. Using client configuration from .secrets/secrets.json
3. Using Microsoft device code authentication
4. Polling until user authentication completes
5. Storing the access token in .secrets/token.json
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None):
        """Minimal .env loader used only if python-dotenv is unavailable."""
        path = Path(dotenv_path or ".env")
        if not path.exists():
            return False

        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

        return True

# Add project root to sys.path for imports to work correctly
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(
    0,
    str(PROJECT_ROOT),
)

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_TENANT = "consumers"
DEFAULT_SCOPES = ["Mail.Read", "User.Read", "offline_access"]


def load_client_config(secrets_path):
    """Load and validate Microsoft OAuth client configuration."""
    client_config = {}

    # Optional local config can override tenant/scopes while keeping secrets out of git.
    if secrets_path.exists():
        try:
            with open(secrets_path, "r", encoding="utf-8") as secrets_file:
                client_config = json.load(secrets_file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Client secrets file is not valid JSON: {exc}") from exc

    # .env fallback is useful for quick local setup when only the public client_id is needed.
    client_id = client_config.get("client_id") or os.getenv("HOTMAIL_GRAPH_CLIENT_ID")
    if not client_id:
        raise ValueError(
            f"Client secrets file not found or missing 'client_id' at {secrets_path}. "
            "Create a Microsoft Entra app registration for personal accounts and "
            "save its client_id in that file, or set HOTMAIL_GRAPH_CLIENT_ID in "
            "the project .env file."
        )

    tenant = client_config.get("tenant", DEFAULT_TENANT)
    scopes = client_config.get("scopes", DEFAULT_SCOPES)

    if not isinstance(scopes, list) or not all(
        isinstance(scope, str) for scope in scopes
    ):
        raise ValueError("'scopes' must be a list of strings")

    return {
        "client_id": client_id,
        "tenant": tenant,
        "scopes": scopes,
    }


def request_device_code(client_id, tenant, scopes):
    """Start Microsoft Graph device code authentication."""
    device_code_uri = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"

    # Device code flow avoids localhost redirect URI issues in WSL/headless shells.
    form_data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "scope": " ".join(scopes),
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        device_code_uri,
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Device code request failed ({exc.code}): {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Device code request failed: {exc.reason}") from exc


def poll_device_code_for_token(client_id, tenant, scopes, device_code_data):
    """Poll Microsoft until the device code has been authorized."""
    token_uri = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    expires_at = time.time() + int(device_code_data.get("expires_in", 900))
    interval = int(device_code_data.get("interval", 5))

    # Microsoft returns authorization_pending until the user enters the code.
    while time.time() < expires_at:
        time.sleep(interval)

        form_data = urllib.parse.urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code_data["device_code"],
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            token_uri,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                token_data = json.loads(response.read().decode("utf-8"))
                token_data.update(
                    {
                        "client_id": client_id,
                        "tenant": tenant,
                        "scopes": scopes,
                        "token_uri": token_uri,
                        "created_at": int(time.time()),
                    }
                )

                if "expires_in" in token_data:
                    token_data["expires_at"] = token_data["created_at"] + int(
                        token_data["expires_in"]
                    )

                return token_data
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                error_data = json.loads(error_body)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Token request failed ({exc.code}): {error_body}"
                ) from exc

            error = error_data.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                # Respect Microsoft backoff if polling too frequently.
                interval += 5
                continue

            description = error_data.get("error_description", error_body)
            raise RuntimeError(f"Token request failed: {description}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Token request failed: {exc.reason}") from exc

    raise RuntimeError("Device code expired before authentication completed")


def main():
    """Run Outlook/Hotmail authentication setup."""
    secrets_dir = Path(__file__).parent.absolute() / ".secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)

    secrets_path = secrets_dir / "secrets.json"
    try:
        client_config = load_client_config(secrets_path)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    try:
        print("Starting Outlook/Hotmail device code authentication flow...")
        device_code_data = request_device_code(
            client_id=client_config["client_id"],
            tenant=client_config["tenant"],
            scopes=client_config["scopes"],
        )

        message = device_code_data.get("message")
        verification_uri = device_code_data.get("verification_uri")
        user_code = device_code_data.get("user_code")

        # Microsoft usually returns a localized ready-to-print message.
        if message:
            print(message)
        else:
            print(f"Open this URL in your browser: {verification_uri}")
            print(f"Enter this code: {user_code}")

        token_data = poll_device_code_for_token(
            client_id=client_config["client_id"],
            tenant=client_config["tenant"],
            scopes=client_config["scopes"],
            device_code_data=device_code_data,
        )

        token_path = secrets_dir / "token.json"
        with open(token_path, "w", encoding="utf-8") as token_file:
            # Keep the full token response so refresh_token/expires_at remain available.
            json.dump(token_data, token_file)

        print("\nAuthentication successful!")
        print(f"Access token stored at {token_path}")
        return 0
    except Exception as exc:
        print(f"Authentication failed: {exc}")
        return 1


if __name__ == "__main__":
    exit(main())

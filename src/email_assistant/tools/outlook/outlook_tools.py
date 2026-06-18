"""
Microsoft Graph helpers for Outlook ingestion.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.absolute()
_SECRETS_DIR = _ROOT / ".secrets"
TOKEN_PATH = _SECRETS_DIR / "token.json"

GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/messages"
DEFAULT_TENANT = "consumers"


def _load_token_from_env():
    env_token = os.getenv("OUTLOOK_TOKEN")
    if not env_token:
        return None

    try:
        token_data = json.loads(env_token)
        print("Using OUTLOOK_TOKEN environment variable")
        return token_data
    except Exception as e:
        print(f"Could not parse OUTLOOK_TOKEN environment variable: {str(e)}")
        return None


def _load_token_from_file():
    if not TOKEN_PATH.exists():
        print(f"Token file not found at {TOKEN_PATH}")
        return None

    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            token_data = json.load(f)
        print(f"Using token from {TOKEN_PATH}")
        return token_data
    except Exception as e:
        print(f"Could not load token from {TOKEN_PATH}: {str(e)}")
        return None


def _token_is_expired(token_data):
    expires_at = token_data.get("expires_at")
    if expires_at is None:
        return False

    try:
        # Refresh a little early so a token does not expire mid-ingestion.
        return int(expires_at) <= int(time.time()) + 60
    except (TypeError, ValueError):
        return False


def _refresh_outlook_token(token_data):
    refresh_token = token_data.get("refresh_token")
    client_id = token_data.get("client_id")
    if not refresh_token or not client_id:
        print("Outlook token is expired but missing refresh_token or client_id")
        return None

    token_uri = token_data.get("token_uri")
    if not token_uri:
        tenant = token_data.get("tenant", DEFAULT_TENANT)
        token_uri = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    scopes = token_data.get("scopes")
    form = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if scopes:
        form["scope"] = " ".join(scopes)

    request = urllib.request.Request(
        token_uri,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            refreshed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"Failed to refresh Outlook token ({exc.code}): {error_body}")
        return None
    except urllib.error.URLError as exc:
        print(f"Failed to refresh Outlook token: {exc.reason}")
        return None

    updated_token = {**token_data, **refreshed}
    updated_token["client_id"] = client_id
    updated_token["token_uri"] = token_uri
    updated_token["tenant"] = token_data.get("tenant", DEFAULT_TENANT)
    updated_token["scopes"] = scopes or token_data.get("scope", "").split()
    updated_token["created_at"] = int(time.time())
    if "expires_in" in refreshed:
        updated_token["expires_at"] = updated_token["created_at"] + int(
            refreshed["expires_in"]
        )

    print("Refreshed Outlook access token")
    return updated_token


def _save_token(token_data):
    try:
        _SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
            json.dump(token_data, token_file)
        print(f"Saved refreshed token to {TOKEN_PATH}")
    except Exception as e:
        print(f"Could not save refreshed token to {TOKEN_PATH}: {str(e)}")


def load_outlook_credentials():
    """
    Load Outlook credentials from token.json or environment variables.

    This function attempts to load credentials from multiple sources in this order:
    1. Environment variables OUTLOOK_TOKEN
    2. Local file at token_path (.secrets/token.json)

    Returns:
        Token data dict or None if credentials can't be loaded.
    """

    token_data = _load_token_from_env()
    loaded_from_file = False

    if token_data is None:
        token_data = _load_token_from_file()
        loaded_from_file = token_data is not None

    if token_data is None:
        print("Could not find valid token data in any location")
        return None

    if _token_is_expired(token_data):
        refreshed_token = _refresh_outlook_token(token_data)
        if refreshed_token is None:
            return None
        token_data = refreshed_token
        if loaded_from_file:
            _save_token(token_data)

    if not token_data.get("access_token"):
        print("Outlook token data missing access_token")
        return None

    return token_data


def graph_request(method, url, token_data, params=None, body=None):
    """Call Microsoft Graph and return the decoded JSON response."""
    if params:
        query = urllib.parse.urlencode(params)
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"

    data = None
    headers = {
        "Authorization": f"Bearer {token_data['access_token']}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Microsoft Graph request failed ({exc.code}): {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Microsoft Graph request failed: {exc.reason}") from exc


def _email_address(address_obj):
    if not address_obj:
        return ""

    email_address = address_obj.get("emailAddress", address_obj)
    name = email_address.get("name")
    address = email_address.get("address")

    if name and address:
        return f"{name} <{address}>"
    return address or name or ""


def format_recipients(recipients):
    return ", ".join(
        formatted for formatted in (_email_address(r) for r in recipients or []) if formatted
    )


def extract_email_data(message):
    """Extract key information from a Microsoft Graph message."""
    body = message.get("body") or {}

    return {
        "from_email": _email_address(message.get("from")),
        "to_email": format_recipients(message.get("toRecipients")),
        "subject": message.get("subject") or "No Subject",
        "page_content": body.get("content") or "",
        "id": message["id"],
        "thread_id": message.get("conversationId") or message["id"],
        "send_time": message.get("receivedDateTime") or "Unknown Date",
    }


def _escape_odata_string(value):
    return value.replace("'", "''")


def _build_filter(args):
    if args.skip_filters:
        return None

    filters = []

    if args.hours_since > 0:
        after = datetime.now(timezone.utc) - timedelta(hours=args.hours_since)
        filters.append(f"receivedDateTime ge {after.isoformat().replace('+00:00', 'Z')}")

    if not args.include_read:
        filters.append("isRead eq false")

    return " and ".join(filters)


def _recipient_addresses(recipients):
    addresses = []
    for recipient in recipients or []:
        email_address = recipient.get("emailAddress", {}) if recipient else {}
        address = email_address.get("address")
        if address:
            addresses.append(address.lower())
    return addresses


def _message_matches_email(message, email_address):
    normalized_email = email_address.lower()
    from_address = (
        (message.get("from") or {})
        .get("emailAddress", {})
        .get("address", "")
        .lower()
    )
    to_addresses = _recipient_addresses(message.get("toRecipients"))
    return normalized_email == from_address or normalized_email in to_addresses


def fetch_outlook_messages(args, token_data):
    """Fetch messages from Microsoft Graph using Outlook/OData query parameters."""
    params = {
        "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,body,isRead",
        "$orderby": "receivedDateTime desc",
        "$top": "25",
    }

    filter_query = _build_filter(args)
    if filter_query:
        params["$filter"] = filter_query
        print(f"Outlook filter query: {filter_query}")
    else:
        print("Outlook filter query: <none>")

    messages = []
    next_url = GRAPH_MESSAGES_URL
    next_params = params

    while next_url:
        results = graph_request("GET", next_url, token_data, params=next_params)
        page_messages = results.get("value", [])
        messages.extend(page_messages)
        next_url = results.get("@odata.nextLink")
        next_params = None

    if not args.skip_filters:
        before_count = len(messages)
        messages = [
            message for message in messages if _message_matches_email(message, args.email)
        ]
        print(
            f"Client-side email filter kept {len(messages)}/{before_count} messages "
            f"for {args.email}"
        )

    return messages

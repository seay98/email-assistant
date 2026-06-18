#!/usr/bin/env python
"""
Manual test script for Outlook message fetching.

This script exercises the Microsoft Graph fetch path without connecting to
LangGraph or creating runs.
"""

import argparse
import re

try:
    from .outlook_tools import (
        _build_filter,
        extract_email_data,
        fetch_outlook_messages,
        load_outlook_credentials,
    )
except ImportError:
    from outlook_tools import (
        _build_filter,
        extract_email_data,
        fetch_outlook_messages,
        load_outlook_credentials,
    )


MOCK_MESSAGE = {
    "id": "mock-message-id-123",
    "conversationId": "mock-conversation-id-456",
    "subject": "Sample Outlook message",
    "from": {
        "emailAddress": {
            "name": "Ada Lovelace",
            "address": "ada@example.com",
        }
    },
    "toRecipients": [
        {
            "emailAddress": {
                "name": "Grace Hopper",
                "address": "grace@example.com",
            }
        },
        {
            "emailAddress": {
                "address": "team@example.com",
            }
        },
    ],
    "receivedDateTime": "2026-06-18T08:30:00Z",
    "body": {
        "contentType": "html",
        "content": "<p>Hello from a mocked Microsoft Graph message.</p>",
    },
    "isRead": False,
}


def _plain_preview(content, width=240):
    plain = re.sub(r"<[^>]+>", " ", content or "")
    plain = " ".join(plain.split())
    if len(plain) <= width:
        return plain
    return f"{plain[:width].rstrip()}..."


def print_email(email_data, show_body=False):
    print(f"From: {email_data['from_email']}")
    print(f"To: {email_data['to_email']}")
    print(f"Subject: {email_data['subject']}")
    print(f"Received: {email_data['send_time']}")
    print(f"ID: {email_data['id']}")
    print(f"Thread: {email_data['thread_id']}")
    if show_body:
        print("Body:")
        print(_plain_preview(email_data["page_content"]))


def run_mock(args):
    email_data = extract_email_data(MOCK_MESSAGE)
    print("Mock Outlook message normalized successfully")
    print_email(email_data, show_body=True)
    return 0


def run_print_filter(args):
    filter_query = _build_filter(args)
    print(filter_query if filter_query else "<none>")
    return 0


def run_real_fetch(args):
    token_data = load_outlook_credentials()
    if not token_data:
        print("Failed to load Outlook credentials")
        return 1

    messages = fetch_outlook_messages(args, token_data)
    print(f"Fetched {len(messages)} messages")

    for index, message in enumerate(messages[: args.limit], start=1):
        email_data = extract_email_data(message)
        print(f"\nMessage {index}/{min(len(messages), args.limit)}")
        print_email(email_data, show_body=args.show_body)

    if len(messages) > args.limit:
        print(f"\n{len(messages) - args.limit} additional messages not shown")

    return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test Outlook Microsoft Graph message fetching"
    )
    parser.add_argument(
        "--email",
        type=str,
        default="test@example.com",
        help="Email address used for client-side sender/recipient matching",
    )
    parser.add_argument(
        "--hours-since",
        type=int,
        default=2,
        help="Only retrieve emails newer than this many hours",
    )
    parser.add_argument(
        "--include-read",
        action="store_true",
        help="Include emails that have already been read",
    )
    parser.add_argument(
        "--skip-filters",
        action="store_true",
        help="Skip Outlook query filters",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of fetched messages to print",
    )
    parser.add_argument(
        "--show-body",
        action="store_true",
        help="Print a short plain-text body preview",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Test normalization with a built-in mock message",
    )
    parser.add_argument(
        "--print-filter",
        action="store_true",
        help="Print the server-side OData filter without calling Microsoft Graph",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.mock:
        return run_mock(args)
    if args.print_filter:
        return run_print_filter(args)
    return run_real_fetch(args)


if __name__ == "__main__":
    exit(main())

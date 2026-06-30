#!/usr/bin/env python
"""
Simple Outlook ingestion script for Microsoft Graph and LangGraph.
"""

import argparse
import asyncio
import hashlib
import uuid

from dotenv import load_dotenv
from langgraph_sdk import get_client

try:
    from .outlook_tools import (
        extract_email_data,
        fetch_outlook_messages,
        load_outlook_credentials,
    )
except ImportError:
    from outlook_tools import (
        extract_email_data,
        fetch_outlook_messages,
        load_outlook_credentials,
    )

load_dotenv()

async def _get_or_create_thread(client, thread_id):
    try:
        thread_info = await client.threads.get(thread_id)
        print(f"Found existing thread: {thread_id}")
        return thread_info, True
    except Exception:
        print(f"Creating new thread: {thread_id}")
        thread_info = await client.threads.create(thread_id=thread_id)
        return thread_info, False


def _thread_metadata(thread_info):
    if isinstance(thread_info, dict):
        return thread_info.get("metadata") or {}
    return getattr(thread_info, "metadata", {}) or {}


def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _run_id(run):
    return _field(run, "run_id") or _field(run, "id")


def _state_values(state):
    return _field(state, "values", {}) or {}


async def _delete_previous_runs(client, thread_id):
    try:
        runs = await client.runs.list(thread_id)
        for run_info in runs:
            run_id = run_info.get("id") if isinstance(run_info, dict) else run_info.id
            print(f"Deleting previous run {run_id} from thread {thread_id}")
            try:
                await client.runs.delete(thread_id, run_id)
            except Exception as e:
                print(f"Failed to delete run {run_id}: {str(e)}")
    except Exception as e:
        print(f"Error listing/deleting runs: {str(e)}")


async def ingest_email_to_langgraph(
    email_data,
    graph_name,
    url="http://127.0.0.1:2024",
    rerun=False,
):
    """Ingest an Outlook email to LangGraph."""
    client = get_client(url=url)

    raw_thread_id = email_data["thread_id"]
    thread_id = str(
        uuid.UUID(hex=hashlib.md5(raw_thread_id.encode("UTF-8")).hexdigest())
    )
    print(f"Outlook conversation ID: {raw_thread_id} -> LangGraph thread ID: {thread_id}")

    thread_info, thread_exists = await _get_or_create_thread(client, thread_id)
    metadata = _thread_metadata(thread_info)
    if not rerun and metadata.get("email_id") == email_data["id"]:
        print(f"Skipping already processed email {email_data['id']} in thread {thread_id}")
        return thread_id, None, False

    if thread_exists:
        await _delete_previous_runs(client, thread_id)

    await client.threads.update(thread_id, metadata={"email_id": email_data["id"]})

    print(f"Creating run for thread {thread_id} with graph {graph_name}")
    run = await client.runs.create(
        thread_id,
        graph_name,
        input={
            "email_input": {
                "author": email_data["from_email"],
                "to": email_data["to_email"],
                "subject": email_data["subject"],
                "email_thread": email_data["page_content"],
                "id": email_data["id"],
            }
        },
        multitask_strategy="rollback",
    )

    print(f"Run created successfully with thread ID: {thread_id}")
    return thread_id, run, True


async def wait_for_langgraph_run(thread_id, run, url="http://127.0.0.1:2024"):
    """Wait for a LangGraph run and print the final thread state summary."""
    run_id = _run_id(run)
    if not run_id:
        print("Cannot wait for run completion: run ID is missing")
        return None

    client = get_client(url=url)
    print(f"Waiting for run {run_id} on thread {thread_id} to finish...")
    await client.runs.join(thread_id, run_id)

    state = await client.threads.get_state(thread_id)
    values = _state_values(state)
    email_input = values.get("email_input") or {}
    classification = values.get("classification_decision")

    print("LangGraph run finished")
    print(f"State email subject: {email_input.get('subject', '<missing>')}")
    print(f"Classification decision: {classification or '<missing>'}")
    return state


async def fetch_and_process_emails(args):
    """Fetch emails from Outlook and process them through LangGraph."""
    token_data = load_outlook_credentials()
    if not token_data:
        print("Failed to load Outlook credentials")
        return 1

    processed_count = 0
    skipped_count = 0

    try:
        messages = fetch_outlook_messages(args, token_data)

        if not messages:
            print("No emails found matching the criteria")
            return 0

        print(f"Found {len(messages)} emails")

        for i, message in enumerate(messages):
            if args.early and processed_count > 0:
                print(f"Early stop after processing {processed_count} emails")
                break

            email_data = extract_email_data(message)

            print(f"\nProcessing email {i + 1}/{len(messages)}:")
            print(f"From: {email_data['from_email']}")
            print(f"Subject: {email_data['subject']}")

            thread_id, run, processed = await ingest_email_to_langgraph(
                email_data,
                args.graph_name,
                url=args.url,
                rerun=args.rerun,
            )

            if processed:
                processed_count += 1
                if args.wait:
                    await wait_for_langgraph_run(thread_id, run, url=args.url)
            else:
                skipped_count += 1

        print(
            f"\nProcessed {processed_count} emails successfully"
            f" ({skipped_count} skipped)"
        )
        return 0
    except Exception as e:
        print(f"Error processing emails: {str(e)}")
        return 1


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Simple Outlook ingestion for LangGraph with Microsoft Graph"
    )

    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Optional email address used for client-side sender/recipient matching",
    )
    parser.add_argument(
        "--hours-since",
        type=int,
        default=2,
        help="Only retrieve emails newer than this many hours; use 0 for no time filter",
    )
    parser.add_argument(
        "--no-time-filter",
        action="store_true",
        help="Disable the receivedDateTime filter without disabling other filters",
    )
    parser.add_argument(
        "--graph-name",
        type=str,
        default="email_assistant",
        help="Name of the LangGraph to use",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://127.0.0.1:2024",
        help="URL of the LangGraph deployment",
    )
    parser.add_argument(
        "--early",
        action="store_true",
        help="Early stop after processing one email",
    )
    parser.add_argument(
        "--include-read",
        action="store_true",
        help=(
            "Include emails that have already been read; use with "
            "--hours-since 0 or --no-time-filter to search older read mail"
        ),
    )
    parser.add_argument(
        "--skip-email-filter",
        action="store_true",
        help="Skip client-side sender/recipient matching",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Process the same emails again even if already processed",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for each LangGraph run to finish and print the final state summary",
    )
    parser.add_argument(
        "--skip-filters",
        action="store_true",
        help="Skip all Outlook query filters and client-side email filtering",
    )
    parser.add_argument(
        "--fetch-limit",
        type=int,
        default=25,
        help="Microsoft Graph page size for each fetch request",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit(asyncio.run(fetch_and_process_emails(args)))

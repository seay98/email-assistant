#!/usr/bin/env python
"""
Manual test script for Outlook-to-LangGraph ingestion.

This script uses a synthetic Outlook email, so it does not require Microsoft
Graph credentials. It verifies that run_ingest.py can create a LangGraph run
and that the final thread state contains the expected email input.
"""

import argparse
import asyncio

from langgraph_sdk import get_client

try:
    from .run_ingest import ingest_email_to_langgraph
except ImportError:
    from run_ingest import ingest_email_to_langgraph


DEFAULT_SUBJECT = "Synthetic Outlook ingest test"


def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _metadata(thread_info):
    return _field(thread_info, "metadata", {}) or {}


def _state_values(state):
    return _field(state, "values", {}) or {}


def _run_id(run):
    return _field(run, "run_id") or _field(run, "id")


def _synthetic_email(args):
    return {
        "from_email": "Alice Example <alice@example.com>",
        "to_email": "Seay Example <seay@example.com>",
        "subject": DEFAULT_SUBJECT,
        "page_content": (
            "Hi Seay, this is a synthetic Outlook ingest test. "
            "Please confirm whether the LangGraph email assistant can process it."
        ),
        "id": args.email_id,
        "thread_id": args.conversation_id,
    }


def _assert_equal(label, actual, expected, failures):
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_present(label, value, failures):
    if value is None:
        failures.append(f"{label}: missing")


async def run_test(args):
    email_data = _synthetic_email(args)

    thread_id, run, processed = await ingest_email_to_langgraph(
        email_data,
        args.graph_name,
        url=args.url,
        rerun=args.rerun,
    )

    run_id = _run_id(run)
    print(f"Thread ID: {thread_id}")
    print(f"Run ID: {run_id or '<missing>'}")
    print(f"Processed: {processed}")

    failures = []
    if not processed:
        failures.append("processed: expected True, got False")
    _assert_present("run id", run_id, failures)

    client = get_client(url=args.url)
    if run_id:
        print("Waiting for LangGraph run to finish...")
        await client.runs.join(thread_id, run_id)

    thread_info = await client.threads.get(thread_id)
    state = await client.threads.get_state(thread_id)

    metadata = _metadata(thread_info)
    values = _state_values(state)
    email_input = values.get("email_input")
    classification = values.get("classification_decision")

    print(f"Thread metadata: {metadata}")
    print(f"Classification decision: {classification or '<missing>'}")

    _assert_equal("thread metadata email_id", metadata.get("email_id"), args.email_id, failures)
    _assert_present("state values email_input", email_input, failures)
    if email_input is not None:
        _assert_equal(
            "state email_input subject",
            email_input.get("subject"),
            DEFAULT_SUBJECT,
            failures,
        )
    _assert_present("state values classification_decision", classification, failures)

    if failures:
        print("\nIngest test failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nIngest test passed")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test Outlook synthetic email ingestion into LangGraph"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://127.0.0.1:2024",
        help="URL of the LangGraph deployment",
    )
    parser.add_argument(
        "--graph-name",
        type=str,
        default="email_assistant",
        help="Name of the LangGraph to use",
    )
    parser.add_argument(
        "--conversation-id",
        type=str,
        default="synthetic-outlook-conversation-001",
        help="Synthetic Outlook conversation ID used to derive the LangGraph thread ID",
    )
    parser.add_argument(
        "--email-id",
        type=str,
        default="synthetic-outlook-email-001",
        help="Synthetic Outlook email ID stored in thread metadata",
    )
    parser.add_argument(
        "--rerun",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reprocess the synthetic email even if this thread already has the same email ID",
    )
    return parser.parse_args()


def main():
    return asyncio.run(run_test(parse_args()))


if __name__ == "__main__":
    exit(main())

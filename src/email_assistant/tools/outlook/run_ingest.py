import json
import os

from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# Setup paths
_ROOT = Path(__file__).parent.absolute()
_SECRETS_DIR = _ROOT / ".secrets"
TOKEN_PATH = _SECRETS_DIR / "token.json"

def load_outlook_credentials():
    """
    Load Outlook credentials from token.json or environment variables.
    
    This function attempts to load credentials from multiple sources in this order:
    1. Environment variables OUTLOOK_TOKEN
    2. Local file at token_path (.secrets/token.json)
    
    Returns:
        Outlook OAuth2 Credentials object or None if credentials can't be loaded
    """

    token_data = None

    # 1. Try environment variable
    env_token = os.getenv("OUTLOOK_TOKEN")
    if env_token:
        try:
            token_data = json.loads(env_token)
            print("Using OUTLOOK_TOKEN environment variable")
        except Exception as e:
            print(f"Could not parse OUTLOOK_TOKEN environment variable: {str(e)}")
    
    # 2. Try local file as fallback
    if token_data is None:
        if TOKEN_PATH.exists():
            try:
                with open(TOKEN_PATH, "r") as f:
                    token_data = json.load(f)
                print(f"Using token from {TOKEN_PATH}")
            except Exception as e:
                print(f"Could not load token from {TOKEN_PATH}: {str(e)}")
        else:
            print(f"Token file not found at {TOKEN_PATH}")

    # If we couldn't get token data from any source, return None
    if token_data is None:
        print("Could not find valid token data in any location")
        return None

async def fetch_and_process_emails(args):
    """Fetch emails from Outlook and process them through LangGraph."""

    # Load credentials
import anthropic
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

client = anthropic.Anthropic()

# List available models
try:
    models = client.models.list(limit=20)
    print("Available models:")
    for m in models.data:
        print(f"  {m.id}  (display: {m.display_name})")
except Exception as e:
    print("Model list error:", e)

# Check which API key is loaded (first/last 6 chars only)
import os
key = os.environ.get("ANTHROPIC_API_KEY", "")
if key:
    print(f"\nAPI key loaded: {key[:6]}...{key[-6:]}")
else:
    print("\nNo ANTHROPIC_API_KEY found in environment / .env")

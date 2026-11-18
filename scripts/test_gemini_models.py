"""List available models from Google Gemini API."""

import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("No GEMINI_API_KEY")
    exit(1)

client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=10000))

print("Listing Gemini models...")
try:
    models = list(client.models.list(config={"page_size": 50}))
    print(f"Total models returned: {len(models)}")
    for m in models:
        name = getattr(m, "name", str(m))
        disp = getattr(m, "display_name", "")
        # Filter for relevant text, vision, imagen, veo
        if any(k in name.lower() for k in ["flash", "pro", "image", "video", "veo"]):
            print(f"  - {name} ({disp})")
except Exception as e:
    print("Error listing models:", e)

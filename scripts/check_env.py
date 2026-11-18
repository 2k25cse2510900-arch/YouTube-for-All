import os
import sys

print("Python executable:", sys.executable)
print("Python version:", sys.version)

env_path = ".env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        keys = []
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                keys.append(line.split("=")[0].strip())
        print(".env keys present:", keys)
else:
    print(".env file does not exist.")

env_tts_keys = [k for k in os.environ if any(t in k.upper() for t in ['TTS', 'VOICE', 'ELEVEN', 'AZURE', 'GOOGLE', 'SPEECH', 'SARVAM', 'OPENAI', 'GEMINI'])]
print("Environment keys related to TTS/Voice/AI:", env_tts_keys)

# Check installed packages in current python
try:
    import pip
    import pkg_resources
    # or importlib.metadata
    import importlib.metadata
    installed = sorted([d.metadata['Name'] for d in importlib.metadata.distributions()])
    print(f"Installed packages ({len(installed)} total):")
    for pkg in installed:
        if any(term in pkg.lower() for term in ['tts', 'voice', 'sound', 'audio', 'torch', 'transformers', 'piper', 'edge', 'eleven', 'google', 'speech']):
            print(f"  - {pkg}")
except Exception as e:
    print("Could not list packages:", e)

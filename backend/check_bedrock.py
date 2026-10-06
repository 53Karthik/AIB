import os

from dotenv import load_dotenv

from .engine.engine import ROOT
from .narrative import Narrative
from .store import Store


def main():
    load_dotenv(ROOT / ".env", override=False)
    narrative = Narrative(Store())
    status = narrative.status()
    print(f'Credentials: {status["credentialSource"]}\nRegion: {status["region"]}\nModel: {status["model"]}')
    if not status["bedrockConfigured"]:
        print("No AWS credentials found. Configure a local AWS profile or server-side credentials.")
        return 1
    try:
        response = narrative.bedrock_text(system="Follow the instruction precisely.", user="Reply with the single word OK.", max_tokens=16, temperature=0)
        if not response:
            raise ValueError("Bedrock returned no text")
        print("Bedrock returned a response successfully.")
        return 0
    except Exception as error:
        reason = str(error)
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            if os.environ.get(name):
                reason = reason.replace(os.environ[name], "[redacted]")
        print(f"Bedrock check failed: {reason[:1000]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

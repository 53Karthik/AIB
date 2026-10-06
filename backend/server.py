import os

from dotenv import load_dotenv
import uvicorn

from .engine.engine import ROOT


def main():
    load_dotenv(ROOT / ".env", override=False)
    uvicorn.run("backend.api:create_app", factory=True, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "5174")))


if __name__ == "__main__":
    main()

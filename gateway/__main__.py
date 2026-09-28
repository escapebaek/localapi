"""Run with: python -m gateway"""

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from gateway.app import create_app  # noqa: E402  (needs .env loaded first)

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        # Access log records method/path/status only, never request bodies.
        access_log=os.environ.get("ACCESS_LOG", "true").lower() == "true",
    )

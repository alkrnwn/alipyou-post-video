"""
Entrypoint server standalone untuk Shopee Video VMOS Auto-Post.
Dapat dijalankan langsung dengan Python atau dikompilasi via PyInstaller menjadi backend.exe.
"""
import argparse
import multiprocessing
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import uvicorn
from app.main import create_app


def main():
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="Shopee Video VMOS Auto-Post Backend Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    parser.add_argument("--token", default="", help="Authentication token")
    parser.add_argument("--db", default="", help="Database file path")
    parser.add_argument("--dry-run", action="store_true", help="Enable dry-run mode")
    args = parser.parse_args()

    if args.token:
        os.environ["AUTOPOST_TOKEN"] = args.token
    if args.db:
        os.environ["AUTOPOST_DB"] = args.db
    if args.dry_run:
        os.environ["AUTOPOST_DRYRUN"] = "1"

    app = create_app(db_path=args.db or None)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()

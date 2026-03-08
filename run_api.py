#!/usr/bin/env python
"""
Convenience launcher for the Intelli-Credit FastAPI backend.

Usage:
    python run_api.py                  # default port 8000
    python run_api.py --port 9000
    python run_api.py --reload         # hot-reload for development
    python run_api.py --workers 4      # production multi-process
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Intelli-Credit API server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable hot-reload (dev mode)")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    parser.add_argument("--log-level", default="info", help="Log level (default: info)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn not found.  Install it with:  pip install 'uvicorn[standard]'")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Intelli-Credit API")
    print(f"  http://{args.host}:{args.port}")
    print(f"  Docs → http://localhost:{args.port}/docs")
    print(f"{'='*60}\n")

    uvicorn.run(
        "src.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,
        log_level=args.log_level,
        access_log=False,   # handled by our TimingMiddleware
    )


if __name__ == "__main__":
    main()

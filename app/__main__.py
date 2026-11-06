"""Run the local app with an optional port from the environment or .env."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
import uvicorn


def main(argv=None):
    load_dotenv(dotenv_path=Path.cwd() / '.env')
    parser = argparse.ArgumentParser(description='Run the read-only arbitrage monitor')
    parser.add_argument('--host', default='127.0.0.1', help='bind address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=os.getenv('PORT', '8000'), help='port (overrides PORT and .env)')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    uvicorn.run('app.main:app', host=args.host, port=args.port)


if __name__ == '__main__':
    main()

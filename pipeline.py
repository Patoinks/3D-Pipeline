"""CLI entry point. No third-party imports in the orchestrator."""
from pipeline.cli import main

if __name__ == '__main__':
    raise SystemExit(main())

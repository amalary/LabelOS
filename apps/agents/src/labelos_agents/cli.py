import argparse
import json

from labelos_agents.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="labelos-agents")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="Print agent service health.")

    args = parser.parse_args()
    if args.command == "health":
        settings = get_settings()
        print(
            json.dumps(
                {
                    "service": "agents",
                    "status": "ok",
                    "environment": settings.environment,
                    "version": settings.app_version,
                    "model_provider": settings.model_provider,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()

"""Command-line entry point for Odracir."""

from __future__ import annotations

import argparse

from odracir.agent import OdracirAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Odracir agent.")
    parser.add_argument("message", nargs="*", help="Message to send to the agent.")
    args = parser.parse_args()

    user_message = " ".join(args.message).strip()
    if not user_message:
        user_message = input("You: ").strip()

    agent = OdracirAgent()
    print(agent.run(user_message))


if __name__ == "__main__":
    main()

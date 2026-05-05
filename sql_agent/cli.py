from __future__ import annotations

import argparse
import sys

from sql_agent.service import SqlAgentService


class CliApplication:
    known_commands = {"ask", "add-instruction", "refresh-schema", "show-memory", "reset-memory"}

    def __init__(self, service: SqlAgentService | None = None):
        self.service = service or SqlAgentService()

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="LangChain SQL agent for LM Studio and SQL Server."
        )
        subparsers = parser.add_subparsers(dest="command")

        ask_parser = subparsers.add_parser("ask", help="Ask a question about the database.")
        ask_parser.add_argument("query_text", nargs="+", help="Text request for the SQL agent.")

        instruction_parser = subparsers.add_parser(
            "add-instruction",
            help="Save a persistent instruction in agent memory.",
        )
        instruction_parser.add_argument("instruction", nargs="+", help="Instruction text.")

        subparsers.add_parser("refresh-schema", help="Refresh the saved table schema snapshot.")
        subparsers.add_parser("show-memory", help="Show current memory contents.")
        subparsers.add_parser("reset-memory", help="Clear agent memory.")

        parser.add_argument(
            "free_text",
            nargs="*",
            help="If no command is provided, the text is treated as a question for the agent.",
        )
        return parser

    def run(self, argv: list[str] | None = None) -> None:
        parser = self.build_parser()
        argv = list(sys.argv[1:] if argv is None else argv)
        if argv and argv[0] not in self.known_commands and not argv[0].startswith("-"):
            argv = ["ask", *argv]

        args = parser.parse_args(argv)

        if args.command == "add-instruction":
            print(self.service.add_instruction(" ".join(args.instruction)))
            return

        if args.command == "refresh-schema":
            print(self.service.update_schema_memory())
            return

        if args.command == "show-memory":
            print(self.service.show_memory())
            return

        if args.command == "reset-memory":
            print(self.service.reset_memory())
            return

        if args.command == "ask":
            print(self.service.ask_database(" ".join(args.query_text)))
            return

        if args.free_text:
            print(self.service.ask_database(" ".join(args.free_text)))
            return

        parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    return CliApplication().build_parser()


def main() -> None:
    CliApplication().run()

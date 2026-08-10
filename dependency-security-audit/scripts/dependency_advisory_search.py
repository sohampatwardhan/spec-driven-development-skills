#!/usr/bin/env python3
"""Run informational package, advisory, and KEV searches without a project audit.

Commands:
``package --ecosystem NAME --name PACKAGE --version EXACT``, ``advisory --id ID``,
and ``kev --id CVE``. Each supports ``--format text|json``. Exit ``0`` means the search
completed, including an explicit no-match; ``2`` means required evidence was unavailable; and
``3`` means invalid invocation. Exit ``1`` is intentionally unused because search does not apply
delivery policy.
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable, Sequence

from dependency_audit.search import (
    SearchServices,
    default_services,
    format_json,
    format_text,
    sanitize_diagnostic,
    search_advisory,
    search_kev,
    search_package,
)


class InvalidInvocation(ValueError):
    """Represent argument errors without allowing argparse to terminate an embedding process."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """Raise a stable validation error so ``main`` can return exit 3."""
        raise InvalidInvocation(message)


def build_parser() -> argparse.ArgumentParser:
    """Build the documented command grammar shared by CLI tests and production use."""

    parser = _Parser(
        prog="dependency_advisory_search.py",
        description=(
            "Informational advisory lookup; this does not audit a project or make a delivery decision."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    package = commands.add_parser("package", help="search one exact package version")
    package.add_argument("--ecosystem", required=True)
    package.add_argument("--name", required=True)
    package.add_argument("--version", required=True, help="one exact resolved version")
    _add_format(package)
    advisory = commands.add_parser("advisory", help="look up an OSV, GHSA, or CVE identifier")
    advisory.add_argument("--id", required=True, dest="identifier")
    _add_format(advisory)
    kev = commands.add_parser("kev", help="check current CISA KEV membership for a CVE")
    kev.add_argument("--id", required=True, dest="identifier")
    _add_format(kev)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    services: SearchServices | None = None,
    credential_values: Iterable[str] = (),
) -> int:
    """Execute one search with stable non-enforcement exit semantics.

    Args:
        argv: Arguments after the executable name; omission reads ``sys.argv``.
        services: Optional injected clients. Omission constructs bounded production clients.
        credential_values: Exact sensitive values removed from all rendered output.

    Returns:
        ``0`` for completed searches, ``2`` for required-source unavailability, or ``3`` for
        invalid input. This function never returns policy-block exit ``1``.
    """

    try:
        arguments = build_parser().parse_args(argv)
    except InvalidInvocation as error:
        diagnostic = sanitize_diagnostic(error, credential_values)
        print(f"Invalid invocation: {diagnostic}", file=sys.stderr)
        return 3
    configured = services or default_services(credential_values=credential_values)
    if arguments.command == "package":
        result = search_package(
            arguments.ecosystem, arguments.name, arguments.version, configured,
        )
    elif arguments.command == "advisory":
        result = search_advisory(arguments.identifier, configured)
    else:
        result = search_kev(arguments.identifier, configured)
    rendered = (
        format_json(result, credential_values=credential_values)
        if arguments.format == "json"
        else format_text(result, credential_values=credential_values)
    )
    print(rendered, end="")
    return result.exit_code if result.exit_code in {0, 2, 3} else 3


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json"), default="text")


if __name__ == "__main__":
    raise SystemExit(main())

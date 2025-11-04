#!/usr/bin/env python3
"""Generate Homebox location label sheets using selectable templates."""

import argparse
import os
from typing import Optional, Sequence

from dotenv import load_dotenv

from homebox_api import HomeboxApiManager
from label_data import collect_label_contents
from label_generation import render
from label_templates import get_template


def _parse_template_options(option_pairs: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pair in option_pairs:
        if "=" not in pair:
            raise SystemExit(
                f"Invalid --template-option '{pair}'. Expected format NAME=VALUE."
            )
        key, value = pair.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if not key:
            raise SystemExit("Template option name cannot be empty.")
        parsed[key] = value
    return parsed


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for generating the Homebox label PDF."""

    parser = argparse.ArgumentParser(
        description="Homebox locations -> Avery 2x4 PDF (5163/8163)"
    )
    parser.add_argument("-o", "--output")
    parser.add_argument(
        "-s", "--skip",
        type=int,
        default=0,
        help="Number of labels to skip at start of first sheet",
    )
    parser.add_argument(
        "-n", "--name-pattern",
        default="box.*",
        help=(
            "Case-insensitive regex filter applied to location display names "
            "(default: box.*)"
        ),
    )
    parser.add_argument(
        "--base",
        default=os.getenv("HOMEBOX_API_URL"),
        help=(
            "Homebox base URL (defaults to HOMEBOX_API_URL from the "
            "environment/.env)."
        ),
    )
    parser.add_argument(
        "--username",
        default=os.getenv("HOMEBOX_USERNAME"),
        help=(
            "Homebox username (defaults to HOMEBOX_USERNAME from the "
            "environment/.env)."
        ),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("HOMEBOX_PASSWORD"),
        help=(
            "Homebox password (defaults to HOMEBOX_PASSWORD from the "
            "environment/.env)."
        ),
    )
    parser.add_argument(
        "-t", "--template",
        default="5163",
        help="Label template identifier (default: 5163).",
    )
    parser.add_argument(
        "-d", "--draw-outline",
        action="store_true",
        help="Draw outline around every label",
    )
    parser.add_argument(
        "--template-option",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "Provide template customization option (repeatable). For example: "
            "--template-option orientation=vertical"
        ),
    )

    args = parser.parse_args(argv)

    template_name = args.template
    template_options = _parse_template_options(args.template_option)

    api_manager = HomeboxApiManager(
        base_url=args.base,
        username=args.username,
        password=args.password,
    )

    template = get_template(template_name)

    labels = collect_label_contents(
        api_manager,
        args.base,
        args.name_pattern,
    )
    message = render(
        args.output,
        template,
        labels,
        args.skip,
    )

    print(message)
    return 0


if __name__ == "__main__":
    load_dotenv()
    main()

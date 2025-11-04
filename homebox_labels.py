#!/usr/bin/env python3
"""Generate Homebox location label sheets using selectable templates."""

import argparse
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

from homebox_api import HomeboxApiManager
from label_generation import render
from label_types import LabelContent
from label_templates import get_template


def _filter_locations_by_name(
    locations: Sequence[Dict],
    pattern: Optional[str],
) -> List[Dict]:
    """Apply the name regex filter declared by the user."""

    if not pattern:
        return list(locations)

    try:
        name_re = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise SystemExit(
            f"Invalid --name-pattern regex '{pattern}': {exc}") from exc

    filtered = []
    for loc in locations:
        name = location_display_text(loc.get("name", ""))
        if name_re.search(name):
            filtered.append(loc)
    return filtered


def build_location_paths(tree: Sequence[Dict]) -> Dict[str, List[str]]:
    """Map location ids to their breadcrumb path within the tree."""

    paths: Dict[str, List[str]] = {}

    def walk(node: Dict, ancestors: List[str]) -> None:
        if not isinstance(node, dict):
            return
        node_type = (node.get("type") or node.get("nodeType") or "").lower()
        if node_type and node_type != "location":
            return
        name = (node.get("name") or "").strip() or "Unnamed"
        current_path = ancestors + [name]
        loc_id = node.get("id")
        if loc_id:
            paths[loc_id] = current_path
        for child in node.get("children") or []:
            walk(child, current_path)

    for root in tree or []:
        walk(root, [])
    return paths


def location_display_text(name: str) -> str:
    """Normalize user-provided location names."""

    return (
        name.strip()
        if isinstance(name, str) and name.strip()
        else "Unnamed"
    )


def split_name_content(name: str) -> Tuple[str, str]:
    """Split a location name into a short title and the remainder."""

    text = location_display_text(name)
    if " " not in text:
        return text, ""
    head, tail = text.split(" ", 1)
    return head, tail.strip()


def build_ui_url(base_ui: str, loc_id: str) -> str:
    """Construct the dashboard URL for a location."""

    if loc_id:
        return f"{base_ui}/location/{loc_id}"
    return f"{base_ui}/locations"


def collect_label_contents(
    api_manager: HomeboxApiManager,
    base_ui: str,
    name_pattern: Optional[str],
    default_template_options: Optional[Dict[str, str]] = None,
) -> List[LabelContent]:
    """Fetch locations and transform them into label-ready payloads."""

    locations = api_manager.list_locations()
    filtered_locations = _filter_locations_by_name(locations, name_pattern)

    return _build_label_contents(
        filtered_locations,
        api_manager,
        base_ui,
        default_template_options=default_template_options,
    )


def collect_label_contents_by_ids(
    api_manager: HomeboxApiManager,
    base_ui: str,
    location_ids: Sequence[str],
    *,
    default_template_options: Optional[Dict[str, str]] = None,
    template_overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[LabelContent]:
    """Return label payloads for the specified location ids."""

    if not location_ids:
        return []

    locations = api_manager.list_locations()
    by_id = {
        loc.get("id"): loc
        for loc in locations
        if isinstance(loc.get("id"), str)
    }
    ordered_locations = [
        by_id[loc_id]
        for loc_id in location_ids
        if loc_id in by_id
    ]
    return _build_label_contents(
        ordered_locations,
        api_manager,
        base_ui,
        default_template_options=default_template_options,
        template_overrides=template_overrides,
    )


def _build_label_contents(
    locations: Sequence[Dict],
    api_manager: HomeboxApiManager,
    base_ui: str,
    *,
    default_template_options: Optional[Dict[str, str]] = None,
    template_overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[LabelContent]:
    valid_locations: List[Dict] = []
    loc_ids: List[str] = []
    for loc in locations:
        loc_id = loc.get("id")
        if isinstance(loc_id, str):
            valid_locations.append(loc)
            loc_ids.append(loc_id)

    if not loc_ids:
        return []

    tree = api_manager.get_location_tree()
    path_map = build_location_paths(tree)
    detail_map = api_manager.get_location_details(loc_ids)
    labels_map = api_manager.get_location_item_labels(loc_ids)

    base_ui_clean = (base_ui or "").rstrip("/")
    overrides = template_overrides or {}
    defaults = default_template_options or {}
    return [
        _to_label_content(
            loc,
            detail_map,
            labels_map,
            path_map,
            base_ui_clean,
            overrides,
            defaults,
        )
        for loc in valid_locations
    ]


def _parse_template_options(option_pairs: Sequence[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
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


def _to_label_content(
    location: Dict,
    detail_map: Dict[str, Dict],
    labels_map: Dict[str, List[str]],
    path_map: Dict[str, List[str]],
    base_ui: str,
    template_overrides: Dict[str, Dict[str, str]],
    default_template_options: Dict[str, str],
) -> LabelContent:
    """Convert a single location payload into the printable label structure."""

    loc_id = location.get("id") or ""
    detail_payload = detail_map.get(loc_id, {})
    description = (
        detail_payload.get("description")
        or location.get("description")
        or ""
    ).strip()
    label_names = labels_map.get(loc_id, [])
    labels_text = ", ".join(label_names)

    full_path = path_map.get(loc_id, [])
    trimmed_path = full_path[:-1] if len(full_path) > 1 else []
    path_text = "->".join(trimmed_path)

    title, content = split_name_content(location.get("name") or "")
    options = template_overrides.get(loc_id)
    if options is None and default_template_options:
        options = default_template_options.copy()

    return LabelContent(
        title=title,
        content=content,
        url=build_ui_url(base_ui, loc_id),
        location_id=loc_id,
        path_text=path_text,
        labels_text=labels_text,
        description_text=description,
        template_options=options,
    )


def run_web_app(
    api_manager: HomeboxApiManager,
    base_ui: str,
    template_name: str,
    template_options: Dict[str, str],
    skip: int,
    draw_outline: bool,
    host: str,
    port: int,
) -> None:
    """Launch a lightweight Flask app for interactive label selection."""

    from tempfile import NamedTemporaryFile

    from flask import (
        Flask,
        after_this_request,
        redirect,
        render_template,
        request,
        send_file,
        url_for,
    )

    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "homebox-labels-ui")

    base_ui = base_ui or ""

    option_specs = get_template(template_name).available_options()
    selection_overrides: Dict[str, Dict[str, str]] = {}

    def _truncate(text: str, limit: int = 120) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _friendly_path(path_text: str) -> str:
        path_text = (path_text or "").strip()
        if not path_text:
            return ""
        return path_text.replace("->", " / ")

    @app.route("/", methods=["GET"])
    def index() -> str:
        try:
            contents = collect_label_contents(
                api_manager,
                base_ui,
                None,
                default_template_options=template_options,
            )
        except Exception as exc:  # pragma: no cover - best effort message
            return f"Failed to load locations: {exc}", 500

        rows = []
        for item in contents:
            if not item.location_id:
                continue
            display_name = " ".join(filter(None, [item.title, item.content])).strip()
            display_name = display_name or "Unnamed"
            override = selection_overrides.get(item.location_id)
            if override is not None:
                current_options = override.copy()
            else:
                current_options = (template_options or {}).copy()
            rows.append(
                {
                    "id": item.location_id,
                    "display_name": display_name,
                    "path": _friendly_path(item.path_text),
                    "labels": _truncate(item.labels_text, 80),
                    "description": _truncate(item.description_text, 160),
                    "selected_options": current_options,
                }
            )

        rows.sort(
            key=lambda row: (
                row["path"].lower(),
                row["display_name"].lower(),
            )
        )

        error_key = request.args.get("error")
        error_message = None
        if error_key == "no-selection":
            error_message = "Select at least one location before generating labels."
        elif error_key == "generation":
            error_message = (
                request.args.get("message")
                or "Unable to generate labels for the selected locations."
            )

        return render_template(
            "index.html",
            locations=rows,
            error=error_message,
            template_options=option_specs,
            selected_options=template_options,
        )

    @app.route("/generate", methods=["POST"])
    def generate() -> str:
        nonlocal template_options
        selected_ids = request.form.getlist("location_id")
        if not selected_ids:
            return redirect(url_for("index", error="no-selection"))

        option_values = template_options.copy()
        per_label_options: Dict[str, Dict[str, str]] = {}
        for loc_id in selected_ids:
            overrides: Dict[str, str] = {}
            for option in option_specs:
                field = f"option_{option.name}_{loc_id}"
                submitted = request.form.get(field)
                if submitted:
                    overrides[option.name] = submitted
            if overrides:
                per_label_options[loc_id] = overrides

        try:
            labels = collect_label_contents_by_ids(
                api_manager,
                base_ui,
                selected_ids,
                default_template_options=option_values,
                template_overrides=per_label_options,
            )
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("index", error="generation", message=str(exc)))

        if not labels:
            return redirect(
                url_for(
                    "index",
                    error="generation",
                    message="No matching labels were generated.",
                )
            )

        template = get_template(template_name, option_values)
        template_options = option_values
        selection_overrides.update(per_label_options)
        tmp_file = NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_file.close()

        try:
            render(tmp_file.name, template, labels, skip, draw_outline)
        except Exception as exc:  # pragma: no cover
            os.remove(tmp_file.name)
            return redirect(url_for("index", error="generation", message=str(exc)))

        download_name = "homebox_labels.pdf"

        @after_this_request
        def cleanup(response):
            try:
                os.remove(tmp_file.name)
            except OSError:
                pass
            return response

        return send_file(
            tmp_file.name,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=download_name,
        )

    app.run(host=host, port=port, debug=False, use_reloader=False)


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
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start a local web UI for selecting locations before generating labels.",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="Host/IP for the web UI (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=5000,
        help="Port for the web UI (default: 5000).",
    )

    args = parser.parse_args(argv)

    template_name = args.template
    template_options = _parse_template_options(args.template_option)

    api_manager = HomeboxApiManager(
        base_url=args.base,
        username=args.username,
        password=args.password,
    )

    if args.web:
        run_web_app(
            api_manager=api_manager,
            base_ui=args.base or "",
            template_name=template_name,
            template_options=template_options,
            skip=args.skip,
            draw_outline=args.draw_outline,
            host=args.web_host,
            port=args.web_port,
        )
        return 0

    template = get_template(template_name, template_options)

    labels = collect_label_contents(
        api_manager,
        args.base,
        args.name_pattern,
        default_template_options=template_options,
    )
    message = render(
        args.output,
        template,
        labels,
        args.skip,
        args.draw_outline,
    )

    print(message)
    return 0


if __name__ == "__main__":

    load_dotenv()

    main()

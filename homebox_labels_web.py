"""Web UI support for Homebox label generation."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List

from dotenv import load_dotenv
from flask import (
    Flask,
    after_this_request,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.datastructures import ImmutableMultiDict
from werkzeug.wrappers import Response

from homebox_api import HomeboxApiManager
from label_data import (
    collect_locations_label_contents,
    collect_label_contents_by_ids,
    collect_asset_label_contents,
    collect_asset_label_contents_by_ids,
)
from label_generation import render
from label_templates import get_template, list_templates
from label_types import Location, Asset


__all__ = ["run_web_app"]


def run_web_app(
    api_manager: HomeboxApiManager,
    host: str,
    port: int,
) -> None:
    """Launch a lightweight Flask app for interactive label selection."""

    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "homebox-labels-ui")

    base_ui = api_manager.base_url or ""

    template_choices = list(list_templates())
    if not template_choices:
        raise RuntimeError("No label templates are registered.")

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

    def _parse_selected_ids(form: ImmutableMultiDict) -> List[str]:
        ids = form.getlist("location_id")
        return [loc_id for loc_id in ids if loc_id]

    def _parse_template_options(
        form: ImmutableMultiDict,
        location_ids: List[str],
        option_names: List[str],
    ) -> dict[str, dict[str, str]]:
        """Parse template options from form data.

        Returns a dict mapping location_id -> {option_name: option_value}
        """
        options_by_location: dict[str, dict[str, str]] = {}

        for loc_id in location_ids:
            location_options: dict[str, str] = {}
            for option_name in option_names:
                field_name = f"option_{option_name}_{loc_id}"
                value = form.get(field_name)
                if value:
                    location_options[option_name] = value
            if location_options:
                options_by_location[loc_id] = location_options

        return options_by_location

    @app.route("/", methods=["GET"])
    def index() -> Response | str:
        return redirect(url_for("locations_index"))

    @app.route("/locations", methods=["GET"])
    def locations_index() -> Response | str:
        try:
            locations = api_manager.list_locations()
        except Exception as exc:  # pragma: no cover - best effort message
            return Response(f"Failed to load locations: {exc}", status=500)

        rows = []
        for loc in locations:
            if not loc.id:
                continue
            display_name = loc.name or "Unnamed"
            rows.append(
                {
                    "id": loc.id,
                    "display_name": display_name,
                    "path": "",  # Path will be built on choose page
                    "labels": "",
                    "description": _truncate(loc.description, 160),
                }
            )

        rows.sort(key=lambda row: row["display_name"].lower())

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
            template_choices=template_choices,
            page_type="locations",
        )

    @app.route("/locations/choose", methods=["POST"])
    def locations_choose() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("locations_index", error="no-selection"))

        selected_template = request.form.get("template_name") or template_choices[0]

        # Validate template name exists
        if selected_template.lower() not in [t.lower() for t in template_choices]:
            return redirect(
                url_for("locations_index", error="generation",
                        message=f"Unknown template '{selected_template}'")
            )

        # Load template options for the selected template
        option_specs = []
        has_page_size = False
        try:
            current_template = get_template(selected_template)
            option_specs = current_template.available_options()
            has_page_size = current_template.page_size is not None
        except SystemExit as exc:
            return redirect(
                url_for("locations_index", error="generation", message=str(exc))
            )

        skip_labels = int(request.form.get("skip", "0") or "0")

        try:
            label_contents = collect_label_contents_by_ids(
                api_manager,
                base_ui,
                selected_ids,
            )
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("locations_index", error="generation", message=str(exc)))

        rows = []
        for label in label_contents:
            display_name = (
                " ".join(filter(None, [label.id, label.name])).strip() or "Unnamed"
            )
            rows.append(
                {
                    "id": label.location_id,
                    "display_name": display_name,
                    "path": _friendly_path(label.path_text),
                    "labels": _truncate(label.labels_text, 80),
                    "description": _truncate(label.description_text, 160),
                    "selected_options": label.template_options or {},
                }
            )

        return render_template(
            "choose.html",
            locations=rows,
            template_choices=template_choices,
            selected_template=selected_template,
            option_specs=option_specs,
            has_page_size=has_page_size,
            skip_labels=skip_labels,
            page_type="locations",
        )

    @app.route("/locations/generate", methods=["POST"])
    def locations_generate() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("locations_index", error="no-selection"))

        selected_template = request.form.get("template_name")
        if not selected_template:
            return redirect(url_for("locations_index", error="generation", message="Template selection is required."))

        try:
            template = get_template(selected_template)
        except SystemExit as exc:
            return redirect(
                url_for("locations_index", error="generation", message=str(exc))
            )

        option_specs = template.available_options()
        option_names = [opt.name for opt in option_specs]

        try:
            labels = collect_label_contents_by_ids(
                api_manager,
                base_ui,
                selected_ids,
            )
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("locations_index", error="generation", message=str(exc)))

        if not labels:
            return redirect(
                url_for(
                    "locations_index",
                    error="generation",
                    message="No matching labels were generated.",
                )
            )

        # Parse template options from form and apply to labels
        options_by_location = _parse_template_options(
            request.form,
            selected_ids,
            option_names,
        )

        # Update labels with their template options
        updated_labels = []
        for label in labels:
            location_options = options_by_location.get(label.location_id, {})
            if location_options:
                updated_label = replace(
                    label,
                    template_options=location_options,
                )
            else:
                updated_label = label
            updated_labels.append(updated_label)

        tmp_file = NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_file.close()

        skip_labels = int(request.form.get("skip", "0") or "0")

        try:
            render(tmp_file.name, template, updated_labels, skip_labels)
        except Exception as exc:  # pragma: no cover
            os.remove(tmp_file.name)
            return redirect(url_for("locations_index", error="generation", message=str(exc)))

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

    # Asset routes
    @app.route("/assets", methods=["GET"])
    def assets_index() -> Response | str:
        try:
            items = api_manager.list_items()
        except Exception as exc:  # pragma: no cover - best effort message
            return Response(f"Failed to load assets: {exc}", status=500)

        rows = []
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            display_name = (item.get("name") or "").strip() or "Unnamed"

            # Get location name for path
            location = item.get("location", {})
            location_name = (location.get("name") or "").strip(
            ) if isinstance(location, dict) else ""

            # Get labels from the item
            labels = item.get("labels", [])
            label_names = [
                (label.get("name") or "").strip()
                for label in labels
                if isinstance(label, dict)
            ]
            labels_text = ", ".join(sorted(filter(None, label_names), key=str.casefold))

            rows.append(
                {
                    "id": item_id,
                    "display_name": display_name,
                    "path": location_name,
                    "labels": _truncate(labels_text, 80),
                    "description": _truncate((item.get("description") or "").strip(), 160),
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
            error_message = "Select at least one asset before generating labels."
        elif error_key == "generation":
            error_message = (
                request.args.get("message")
                or "Unable to generate labels for the selected assets."
            )

        return render_template(
            "index.html",
            locations=rows,
            error=error_message,
            template_choices=template_choices,
            page_type="assets",
        )

    @app.route("/assets/choose", methods=["POST"])
    def assets_choose() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("assets_index", error="no-selection"))

        selected_template = request.form.get("template_name") or template_choices[0]

        # Validate template name exists
        if selected_template.lower() not in [t.lower() for t in template_choices]:
            return redirect(
                url_for("assets_index", error="generation",
                        message=f"Unknown template '{selected_template}'")
            )

        # Load template options for the selected template
        option_specs = []
        has_page_size = False
        try:
            current_template = get_template(selected_template)
            option_specs = current_template.available_options()
            has_page_size = current_template.page_size is not None
        except SystemExit as exc:
            return redirect(
                url_for("assets_index", error="generation", message=str(exc))
            )

        skip_labels = int(request.form.get("skip", "0") or "0")

        try:
            label_contents = collect_asset_label_contents_by_ids(
                api_manager,
                base_ui,
                selected_ids,
            )
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("assets_index", error="generation", message=str(exc)))

        rows = []
        for label in label_contents:
            display_name = (
                " ".join(filter(None, [label.id, label.name])).strip() or "Unnamed"
            )
            rows.append(
                {
                    "id": label.location_id,
                    "display_name": display_name,
                    "path": _friendly_path(label.path_text),
                    "labels": _truncate(label.labels_text, 80),
                    "description": _truncate(label.description_text, 160),
                    "selected_options": label.template_options or {},
                }
            )

        return render_template(
            "choose.html",
            locations=rows,
            template_choices=template_choices,
            selected_template=selected_template,
            option_specs=option_specs,
            has_page_size=has_page_size,
            skip_labels=skip_labels,
            page_type="assets",
        )

    @app.route("/assets/generate", methods=["POST"])
    def assets_generate() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("assets_index", error="no-selection"))

        selected_template = request.form.get("template_name")
        if not selected_template:
            return redirect(url_for("assets_index", error="generation", message="Template selection is required."))

        try:
            template = get_template(selected_template)
        except SystemExit as exc:
            return redirect(
                url_for("assets_index", error="generation", message=str(exc))
            )

        option_specs = template.available_options()
        option_names = [opt.name for opt in option_specs]

        try:
            labels = collect_asset_label_contents_by_ids(
                api_manager,
                base_ui,
                selected_ids,
            )
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("assets_index", error="generation", message=str(exc)))

        if not labels:
            return redirect(
                url_for(
                    "assets_index",
                    error="generation",
                    message="No matching labels were generated.",
                )
            )

        # Parse template options from form and apply to labels
        options_by_location = _parse_template_options(
            request.form,
            selected_ids,
            option_names,
        )

        # Update labels with their template options
        updated_labels = []
        for label in labels:
            location_options = options_by_location.get(label.location_id, {})
            if location_options:
                updated_label = replace(
                    label,
                    template_options=location_options,
                )
            else:
                updated_label = label
            updated_labels.append(updated_label)

        tmp_file = NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_file.close()

        skip_labels = int(request.form.get("skip", "0") or "0")

        try:
            render(tmp_file.name, template, updated_labels, skip_labels)
        except Exception as exc:  # pragma: no cover
            os.remove(tmp_file.name)
            return redirect(url_for("assets_index", error="generation", message=str(exc)))

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


def main(argv=None):
    """CLI entry point for the web UI."""
    parser = argparse.ArgumentParser(
        description="Homebox label generator web UI"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host/IP for the web UI (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for the web UI (default: 5000).",
    )

    args = parser.parse_args(argv)

    api_manager = HomeboxApiManager(
        base_url=os.getenv("HOMEBOX_API_URL", ""),
        username=os.getenv("HOMEBOX_USERNAME", ""),
        password=os.getenv("HOMEBOX_PASSWORD", ""),
    )

    run_web_app(
        api_manager=api_manager,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    load_dotenv()
    main()

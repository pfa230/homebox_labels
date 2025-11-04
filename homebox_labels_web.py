"""Web UI support for Homebox label generation."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List

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
from label_generation import render
from label_templates import get_template, list_templates

from homebox_labels import (
    collect_label_contents,
    collect_label_contents_by_ids,
)


__all__ = ["run_web_app"]


def run_web_app(
    api_manager: HomeboxApiManager,
    base_ui: str,
    skip: int,
    host: str,
    port: int,
) -> None:
    """Launch a lightweight Flask app for interactive label selection."""

    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "homebox-labels-ui")

    base_ui = base_ui or ""

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

    @app.route("/", methods=["GET"])
    def index() -> Response | str:
        try:
            contents = collect_label_contents(api_manager, base_ui, None)
        except Exception as exc:  # pragma: no cover - best effort message
            return Response(f"Failed to load locations: {exc}", status=500)

        rows = []
        for item in contents:
            if not item.location_id:
                continue
            display_name = " ".join(filter(None, [item.title, item.content])).strip()
            display_name = display_name or "Unnamed"
            rows.append(
                {
                    "id": item.location_id,
                    "display_name": display_name,
                    "path": _friendly_path(item.path_text),
                    "labels": _truncate(item.labels_text, 80),
                    "description": _truncate(item.description_text, 160),
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
            template_choices=template_choices,
        )

    @app.route("/choose", methods=["POST"])
    def choose() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("index", error="no-selection"))

        selected_template = request.form.get("template_name")
        if not selected_template:
            raise RuntimeError("Template selection is required.")

        current_template = get_template(selected_template)
        option_specs = current_template.available_options()

        try:
            contents = collect_label_contents_by_ids(
                api_manager,
                base_ui,
                selected_ids,
            )
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("index", error="generation", message=str(exc)))

        rows = []
        for item in contents:
            display_name = (
                " ".join(filter(None, [item.title, item.content])).strip() or "Unnamed"
            )
            rows.append(
                {
                    "id": item.location_id,
                    "display_name": display_name,
                    "path": _friendly_path(item.path_text),
                    "labels": _truncate(item.labels_text, 80),
                    "description": _truncate(item.description_text, 160),
                    "selected_options": item.template_options or {},
                }
            )

        return render_template(
            "choose.html",
            locations=rows,
            template_choices=template_choices,
            selected_template=selected_template,
            option_specs=option_specs,
        )

    @app.route("/generate", methods=["POST"])
    def generate() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("index", error="no-selection"))

        selected_template = request.form.get("template_name")
        if not selected_template:
            raise RuntimeError("Template selection is required.")

        get_template(selected_template)  # Validate template early.

        try:
            labels = collect_label_contents_by_ids(
                api_manager,
                base_ui,
                selected_ids,
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

        template = get_template(selected_template)

        tmp_file = NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_file.close()

        try:
            render(tmp_file.name, template, labels, skip)
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

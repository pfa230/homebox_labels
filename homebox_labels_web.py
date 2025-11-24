"""Web UI support for Homebox label generation."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
import zipfile
from typing import Any, List

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
from label_templates.label_data import (
    collect_locations_label_contents,
    collect_asset_label_contents,
    collect_label_contents_by_ids,
)
from domain_data import collect_assets
from label_templates.label_generation import render
from label_templates import get_template, list_templates


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

    sortable_fields = ("id", "name", "parent", "location")

    def _parse_sort_params(
        default_field: str = "id",
        default_direction: str = "desc",
    ) -> tuple[str, str]:
        sort_field = request.args.get("sort", default_field)
        if sort_field not in sortable_fields:
            sort_field = default_field

        sort_direction = request.args.get("direction", default_direction).lower()
        if sort_direction not in {"asc", "desc"}:
            sort_direction = default_direction

        return sort_field, sort_direction

    def _sort_rows(rows: list[dict[str, str]], sort_field: str, sort_direction: str) -> None:
        def _key(row: dict[str, str]) -> tuple[str, str, str, str]:
            base_id = (row.get("display_id") or row.get("id") or "").lower()
            name = (row.get("display_name") or "").lower()
            parent = (row.get("parent") or "").lower()
            location = (row.get("location") or "").lower()

            if sort_field == "id":
                return (base_id, name, parent, location)
            if sort_field == "name":
                return (name, parent, location, base_id)
            if sort_field == "location":
                return (location, name, parent, base_id)
            return (parent, name, location, base_id)

        rows.sort(key=_key, reverse=sort_direction == "desc")

    def _build_sort_links(
        endpoint: str,
        sort_field: str,
        sort_direction: str,
        **extra_params: str,
    ) -> dict[str, str]:
        links: dict[str, str] = {}
        for field in sortable_fields:
            next_direction = "desc" if (field == sort_field and sort_direction == "asc") else "asc"
            params: dict[str, Any] = {
                "sort": field,
                "direction": next_direction,
                **{k: v for k, v in extra_params.items() if v},
            }
            links[field] = url_for(endpoint, **params)
        return links

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
            locations = collect_locations_label_contents(api_manager, name_pattern=None)
        except Exception as exc:  # pragma: no cover - best effort message
            return Response(f"Failed to load locations: {exc}", status=500)

        default_with_id = "1"
        show_only_with_id = (
            (request.args.get("with_id", default_with_id) or "").lower()
            in {"1", "true", "yes", "on"}
        )

        rows = []
        for loc in locations:
            if not loc.id:
                continue
            if show_only_with_id and not (loc.display_id or "").strip():
                continue
            display_name = loc.name or "Unnamed"
            rows.append(
                {
                    "id": loc.id,
                    "display_id": (loc.display_id or "").strip(),
                    "display_name": display_name,
                    "parent": (loc.parent or "").strip(),
                    "labels": ", ".join(loc.labels).strip(),
                    "description": _truncate(loc.description, 160),
                }
            )

        sort_field, sort_direction = _parse_sort_params()
        _sort_rows(rows, sort_field, sort_direction)
        sort_links = _build_sort_links(
            "locations_index",
            sort_field,
            sort_direction,
            with_id="1" if show_only_with_id else "",
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
            "locations.html",
            locations=rows,
            error=error_message,
            template_choices=template_choices,
            sort_field=sort_field,
            sort_direction=sort_direction,
            sort_links=sort_links,
            show_only_with_id=show_only_with_id,
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
                api_manager=api_manager,
                base_ui=base_ui,
                location_ids=selected_ids,
            )
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("locations_index", error="generation", message=str(exc)))

        rows = []
        for label in label_contents:
            display_name = (
                " ".join(filter(None, [label.display_id, label.name])).strip() or "Unnamed"
            )
            rows.append(
                {
                    "id": label.id,
                    "display_name": display_name,
                    "path": "",
                    "labels": _truncate(", ".join(label.labels).strip(), 80),
                    "description": _truncate(label.description, 160),
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
            return redirect(
                url_for(
                    "locations_index",
                    error="generation",
                    message="Template selection is required.",
                )
            )

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
                api_manager=api_manager,
                base_ui=base_ui,
                location_ids=selected_ids,
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
            location_options = options_by_location.get(label.id, {})
            if location_options:
                updated_label = replace(
                    label,
                    template_options=location_options,
                )
            else:
                updated_label = label
            updated_labels.append(updated_label)

        skip_labels = int(request.form.get("skip", "0") or "0")

        # Branch on template output type: PDF vs PNG bundle
        if template.page_size:
            tmp_file = NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp_file.close()
            try:
                render(tmp_file.name, template, updated_labels, skip_labels)
            except Exception as exc:  # pragma: no cover
                os.remove(tmp_file.name)
                return redirect(url_for("locations_index", error="generation", message=str(exc)))

            download_name = "homebox_labels.pdf"

            @after_this_request
            def cleanup_pdf(response):
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
        else:
            # PNG outputs: render to a temp dir, zip them, and return the zip
            tmp_dir = TemporaryDirectory()
            prefix = str(Path(tmp_dir.name) / "homebox_labels")
            try:
                render(prefix, template, updated_labels, skip_labels)
            except Exception as exc:  # pragma: no cover
                tmp_dir.cleanup()
                return redirect(url_for("locations_index", error="generation", message=str(exc)))

            png_files = sorted(Path(tmp_dir.name).glob("homebox_labels_*.png"))
            if not png_files:
                tmp_dir.cleanup()
                return redirect(
                    url_for(
                        "locations_index",
                        error="generation",
                        message="No PNG files were generated.",
                    )
                )

            zip_tmp = NamedTemporaryFile(delete=False, suffix=".zip")
            zip_tmp.close()
            with zipfile.ZipFile(zip_tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for f in png_files:
                    zf.write(f, arcname=f.name)

            @after_this_request
            def cleanup_zip(response):
                try:
                    os.remove(zip_tmp.name)
                except OSError:
                    pass
                try:
                    tmp_dir.cleanup()
                except Exception:
                    pass
                return response

            return send_file(
                zip_tmp.name,
                mimetype="application/zip",
                as_attachment=True,
                download_name="homebox_labels_png.zip",
            )

    # Asset routes
    @app.route("/assets", methods=["GET"])
    def assets_index() -> Response | str:
        try:
            assets = collect_assets(api_manager, name_pattern=None)
        except Exception as exc:  # pragma: no cover - best effort message
            return Response(f"Failed to load assets: {exc}", status=500)

        rows = [
            {
                "id": asset.id,
                "display_id": asset.display_id,
                "display_name": asset.name or "Unnamed",
                "parent_asset": asset.parent_asset,
                "location": asset.location,
                "labels": _truncate(", ".join(asset.labels).strip(), 80),
                "description": _truncate(asset.description, 160),
            }
            for asset in assets
            if asset.id
        ]

        sort_field, sort_direction = _parse_sort_params(default_field="id")
        _sort_rows(rows, sort_field, sort_direction)
        sort_links = _build_sort_links("assets_index", sort_field, sort_direction)

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
            "assets.html",
            assets=rows,
            error=error_message,
            template_choices=template_choices,
            sort_field=sort_field,
            sort_direction=sort_direction,
            sort_links=sort_links,
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
            label_contents = collect_asset_label_contents(api_manager, name_pattern=None)
            label_contents = [al for al in label_contents if al.id in selected_ids]
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("assets_index", error="generation", message=str(exc)))

        rows = []
        for label in label_contents:
            display_name = (
                " ".join(filter(None, [label.display_id, label.name])).strip() or "Unnamed"
            )
            rows.append(
                {
                    "id": label.id,
                    "display_name": display_name,
                    "path": (label.parent or "").strip(),
                    "labels": _truncate(", ".join(label.labels).strip(), 80),
                    "description": _truncate(label.description, 160),
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
            return redirect(
                url_for(
                    "assets_index",
                    error="generation",
                    message="Template selection is required.",
                )
            )

        try:
            template = get_template(selected_template)
        except SystemExit as exc:
            return redirect(
                url_for("assets_index", error="generation", message=str(exc))
            )

        option_specs = template.available_options()
        option_names = [opt.name for opt in option_specs]

        try:
            labels = collect_asset_label_contents(api_manager, name_pattern=None)
            labels = [al for al in labels if al.id in selected_ids]
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
            location_options = options_by_location.get(label.id, {})
            if location_options:
                updated_label = replace(
                    label,
                    template_options=location_options,
                )
            else:
                updated_label = label
            updated_labels.append(updated_label)

        skip_labels = int(request.form.get("skip", "0") or "0")

        if template.page_size:
            tmp_file = NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp_file.close()
            try:
                render(tmp_file.name, template, updated_labels, skip_labels)
            except Exception as exc:  # pragma: no cover
                os.remove(tmp_file.name)
                return redirect(url_for("assets_index", error="generation", message=str(exc)))

            @after_this_request
            def cleanup_pdf(response):
                try:
                    os.remove(tmp_file.name)
                except OSError:
                    pass
                return response

            return send_file(
                tmp_file.name,
                mimetype="application/pdf",
                as_attachment=True,
                download_name="homebox_labels.pdf",
            )
        else:
            tmp_dir = TemporaryDirectory()
            prefix = str(Path(tmp_dir.name) / "homebox_labels")
            try:
                render(prefix, template, updated_labels, skip_labels)
            except Exception as exc:  # pragma: no cover
                tmp_dir.cleanup()
                return redirect(url_for("assets_index", error="generation", message=str(exc)))

            png_files = sorted(Path(tmp_dir.name).glob("homebox_labels_*.png"))
            if not png_files:
                tmp_dir.cleanup()
                return redirect(
                    url_for(
                        "assets_index",
                        error="generation",
                        message="No PNG files were generated.",
                    )
                )

            zip_tmp = NamedTemporaryFile(delete=False, suffix=".zip")
            zip_tmp.close()
            with zipfile.ZipFile(zip_tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for f in png_files:
                    zf.write(f, arcname=f.name)

            @after_this_request
            def cleanup_zip(response):
                try:
                    os.remove(zip_tmp.name)
                except OSError:
                    pass
                try:
                    tmp_dir.cleanup()
                except Exception:
                    pass
                return response

            return send_file(
                zip_tmp.name,
                mimetype="application/zip",
                as_attachment=True,
                download_name="homebox_labels_png.zip",
            )

    # Enable reloader so code changes auto-restart the dev server.
    use_reloader_env = os.getenv("USE_RELOADER")
    use_reloader = (
        str(use_reloader_env).lower() in {"1", "true", "yes", "on"}
        if use_reloader_env is not None
        else True
    )
    app.run(host=host, port=port, debug=False, use_reloader=use_reloader)


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

"""Web UI support for Homebox label generation."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
import zipfile
from typing import Any

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
from domain_data import collect_locations, collect_assets
from label_templates.label_data import (
    locations_to_label_contents,
    assets_to_label_contents,
    build_ui_url,
    build_asset_ui_url,
)
from label_templates.label_generation import render
from label_templates.label_types import LabelContent
from label_templates import get_template, list_templates


__all__ = ["run_web_app", "create_app", "create_app_from_env"]


def create_app(api_manager: HomeboxApiManager) -> Flask:
    """Create the Flask app wired to the provided API manager."""
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config["SECRET_KEY"] = os.getenv(
        "FLASK_SECRET_KEY", "homebox-labels-ui")

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

        sort_direction = request.args.get(
            "direction", default_direction).lower()
        if sort_direction not in {"asc", "desc"}:
            sort_direction = default_direction

        return sort_field, sort_direction

    def _sort_rows(rows: list[dict[str, str | int]], sort_field: str, sort_direction: str) -> None:
        def _key(row: dict[str, str | int]) -> tuple[str, str, str, str]:
            base_id = str(row.get("display_id") or row.get("id") or "").lower()
            name = str(row.get("display_name") or "").lower()
            parent = str(row.get("parent") or "").lower()
            location = str(row.get("location") or "").lower()

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
            next_direction = "desc" if (
                field == sort_field and sort_direction == "asc") else "asc"
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

    def _parse_selected_ids(form: ImmutableMultiDict[str, str]) -> list[str]:
        ids = form.getlist("location_id")
        return [loc_id for loc_id in ids if loc_id]

    def _dedupe_base_ids(selected_ids: list[str]) -> list[str]:
        """Collapse copy IDs back to base IDs while preserving order."""
        base_ids: list[str] = []
        seen: set[str] = set()
        for loc_id in selected_ids:
            base_id = loc_id.split("__copy", 1)[0]
            if not base_id or base_id in seen:
                continue
            seen.add(base_id)
            base_ids.append(base_id)
        return base_ids

    def _parse_template_options(
        form: ImmutableMultiDict[str, str],
        location_ids: list[str],
        option_names: list[str],
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
    def index() -> Response | str:  # pyright: ignore[reportUnusedFunction]
        return redirect(url_for("locations_index"))

    @app.route("/locations", methods=["GET"])
    # pyright: ignore[reportUnusedFunction]
    def locations_index() -> Response | str:
        try:
            locations = collect_locations(api_manager, name_pattern=None)
        except Exception as exc:  # pragma: no cover - best effort message
            return Response(f"Failed to load locations: {exc}", status=500)

        default_with_id = "1"
        show_only_with_id = (
            (request.args.get("with_id", default_with_id) or "").lower()
            in {"1", "true", "yes", "on"}
        )

        rows: list[dict[str, str | int]] = []
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
                    "asset_count": loc.asset_count,
                    "assets_link": url_for("assets_index", location=loc.id),
                    "homebox_location_link": build_ui_url(api_manager.base_url, loc.id),
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
    # pyright: ignore[reportUnusedFunction]
    def locations_choose() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("locations_index", error="no-selection"))
        base_ids = _dedupe_base_ids(selected_ids)

        selected_template = request.form.get(
            "template_name") or template_choices[0]

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
        copies = int(request.form.get("copies", "1") or "1")

        try:
            locs = collect_locations(api_manager, name_pattern=None)
            loc_by_id = {loc.id: loc for loc in locs}
            ordered = [loc_by_id[loc_id]
                       for loc_id in base_ids if loc_id in loc_by_id]
            label_contents = locations_to_label_contents(ordered, base_ui)
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("locations_index", error="generation", message=str(exc)))

        rows: list[dict[str, str | dict[str, str]]] = []
        for label in label_contents:
            for copy_idx in range(copies):
                copy_id = f"{label.id}__copy{copy_idx}" if copies > 1 else label.id
                display_name = (
                    " ".join(
                        filter(None, [label.display_id, label.name])).strip() or "Unnamed"
                )
                rows.append(
                    {
                        "id": copy_id,
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
            copies=copies,
            page_type="locations",
        )

    @app.route("/locations/generate", methods=["POST"])
    # pyright: ignore[reportUnusedFunction]
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
            locs = collect_locations(api_manager, name_pattern=None)
            loc_map = {loc.id: loc for loc in locs}
            labels: list[LabelContent] = []
            for loc_id in selected_ids:
                base_id = loc_id.split("__copy", 1)[0]
                loc = loc_map.get(base_id)
                if not loc:
                    continue
                lc = locations_to_label_contents([loc], base_ui)[0]
                if loc_id != loc.id:
                    lc = replace(lc, id=loc_id)
                labels.append(lc)
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
        updated_labels: list[LabelContent] = []
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
            # pyright: ignore[reportUnusedFunction]
            def cleanup_pdf(response: Response):
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
            # pyright: ignore[reportUnusedFunction]
            def cleanup_zip(response: Response):
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
    # pyright: ignore[reportUnusedFunction]
    def assets_index() -> Response | str:
        try:
            location_filter = (request.args.get("location") or "").strip()
            assets = collect_assets(
                api_manager,
                name_pattern=None,
                location_id=location_filter or None,
            )
        except Exception as exc:  # pragma: no cover - best effort message
            return Response(f"Failed to load assets: {exc}", status=500)
        if location_filter:
            # normalize filter to stored link value for sort links
            pass

        rows: list[dict[str, str | int]] = [
            {
                "id": asset.id,
                "display_id": asset.display_id,
                "display_name": asset.name or "Unnamed",
                "parent_asset": asset.parent_asset,
                "location": asset.location,
                "location_id": asset.location_id,
                "homebox_asset_link": build_asset_ui_url(api_manager.base_url, asset.id),
                "labels": _truncate(", ".join(asset.labels).strip(), 80),
                "description": _truncate(asset.description, 160),
            }
            for asset in assets
            if asset.id
        ]

        sort_field, sort_direction = _parse_sort_params(default_field="id")
        _sort_rows(rows, sort_field, sort_direction)
        sort_links = _build_sort_links(
            "assets_index",
            sort_field,
            sort_direction,
            location=location_filter or "",
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
            "assets.html",
            assets=rows,
            error=error_message,
            template_choices=template_choices,
            sort_field=sort_field,
            sort_direction=sort_direction,
            sort_links=sort_links,
        )

    @app.route("/assets/choose", methods=["POST"])
    # pyright: ignore[reportUnusedFunction]
    def assets_choose() -> Response | str:
        selected_ids = _parse_selected_ids(request.form)
        if not selected_ids:
            return redirect(url_for("assets_index", error="no-selection"))
        base_ids = _dedupe_base_ids(selected_ids)

        selected_template = request.form.get(
            "template_name") or template_choices[0]

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
        copies = int(request.form.get("copies", "1") or "1")

        try:
            assets = collect_assets(api_manager, name_pattern=None)
            assets = [a for a in assets if a.id in base_ids]
            label_contents = assets_to_label_contents(
                assets, api_manager.base_url)
        except Exception as exc:  # pragma: no cover
            return redirect(url_for("assets_index", error="generation", message=str(exc)))

        rows: list[dict[str, str | dict[str, str]]] = []
        for label in label_contents:
            for copy_idx in range(copies):
                copy_id = f"{label.id}__copy{copy_idx}" if copies > 1 else label.id
                display_name = (
                    " ".join(
                        filter(None, [label.display_id, label.name])).strip() or "Unnamed"
                )
                rows.append(
                    {
                        "id": copy_id,
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
            copies=copies,
            page_type="assets",
        )

    @app.route("/assets/generate", methods=["POST"])
    # pyright: ignore[reportUnusedFunction]
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
            assets = collect_assets(api_manager, name_pattern=None)
            asset_map = {a.id: a for a in assets}
            labels: list[LabelContent] = []
            for asset_id in selected_ids:
                base_id = asset_id.split("__copy", 1)[0]
                asset = asset_map.get(base_id)
                if not asset:
                    continue
                lc = assets_to_label_contents([asset], api_manager.base_url)[0]
                if asset_id != asset.id:
                    lc = replace(lc, id=asset_id)
                labels.append(lc)
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
        updated_labels: list[LabelContent] = []
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
            # pyright: ignore[reportUnusedFunction]
            def cleanup_pdf(response: Response):
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
            # pyright: ignore[reportUnusedFunction]
            def cleanup_zip(response: Response):
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

    return app


def create_app_from_env() -> Flask:
    """Create the Flask app using HOMEBOX_* environment variables."""
    load_dotenv()
    api_manager = HomeboxApiManager(
        base_url=os.getenv("HOMEBOX_API_URL", ""),
        username=os.getenv("HOMEBOX_USERNAME", ""),
        password=os.getenv("HOMEBOX_PASSWORD", ""),
    )
    return create_app(api_manager)


def run_web_app(
    api_manager: HomeboxApiManager,
    host: str,
    port: int,
) -> None:
    """Launch a lightweight Flask app for interactive label selection."""
    app = create_app(api_manager)

    # Enable reloader so code changes auto-restart the dev server.
    use_reloader_env = os.getenv("USE_RELOADER")
    use_reloader = (
        str(use_reloader_env).lower() in {"1", "true", "yes", "on"}
        if use_reloader_env is not None
        else True
    )
    app.run(host=host, port=port, debug=False, use_reloader=use_reloader)


def main(argv: list[str] | None = None) -> int:
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
        default=4000,
        help="Port for the web UI (default: 4000).",
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

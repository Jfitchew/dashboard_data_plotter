from __future__ import annotations

import base64
import html
import io
import os
import re
from typing import Any


def export_report_pdf(
    report: dict[str, Any],
    report_assets_root: str,
    out_path: str,
    include_meta: bool = True,
) -> list[str]:
    """Render a report JSON payload directly to PDF using ReportLab.

    Returns a list of non-fatal warnings (for example missing assets).
    Raises ImportError if reportlab is unavailable.
    """

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        HRFlowable,
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    warnings: list[str] = []

    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=str(report.get("title", "Report")),
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="DDPBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DDPComment",
            parent=styles["BodyText"],
            fontName="Helvetica",
            textColor=colors.HexColor("#1f4aa8"),
            fontSize=9,
            leading=12,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DDPMeta",
            parent=styles["BodyText"],
            fontName="Helvetica",
            textColor=colors.HexColor("#555555"),
            fontSize=9,
            leading=12,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DDPSetting",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            leftIndent=8,
            spaceAfter=2,
        )
    )

    title = _safe_text(report.get("title", "Report"))
    created_at = _safe_text(report.get("created_at", ""))
    updated_at = _safe_text(report.get("updated_at", ""))
    data_sources = report.get("data_sources", [])
    snapshots = report.get("snapshots", [])

    story: list[Any] = []
    story.append(Paragraph(_para_text(title), styles["Title"]))
    if include_meta:
        story.append(
            Paragraph(
                _para_text(f"Created: {created_at} | Updated: {updated_at}"),
                styles["DDPMeta"],
            )
        )
    story.append(Spacer(1, 8))

    if include_meta and isinstance(data_sources, list) and data_sources:
        story.append(Paragraph("Data Sources", styles["Heading2"]))
        for item in data_sources:
            if not isinstance(item, dict):
                continue
            display = _safe_text(item.get("display", ""))
            source_id = _safe_text(item.get("source_id", "")).replace("PASTE", "Originally")
            story.append(
                Paragraph(
                    _para_text(f"- {display} ({source_id})"),
                    styles["DDPBody"],
                )
            )
        story.append(Spacer(1, 8))

    story.append(Paragraph("Analysis", styles["Heading2"]))
    story.append(Spacer(1, 4))

    if not isinstance(snapshots, list) or not snapshots:
        story.append(Paragraph("No report content yet.", styles["DDPBody"]))
    else:
        hidden_keys = {
            "close_loop",
            "plot_type",
            "use_plotly",
            "radar_background",
            "show_outliers",
            "outlier_warnings",
            "use_original_binned",
            "show_flag",
        }
        # Balanced layout: slightly larger plots with less dominant text.
        max_img_width = doc.width * 0.68
        max_img_height = 3.4 * inch

        for idx, snap in enumerate(snapshots, start=1):
            if not isinstance(snap, dict):
                continue
            item_kind = _report_item_kind(snap)
            display_title = _snapshot_display_title(snap, include_meta)
            snap_time = _safe_text(snap.get("created_at", ""))
            snap_date = snap_time.split("T", 1)[0] if snap_time else ""
            comments = str(snap.get("comments", ""))
            assets = snap.get("assets", {})
            if not isinstance(assets, dict):
                assets = {}

            if idx > 1:
                story.append(Spacer(1, 6))
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
                story.append(Spacer(1, 8))

            if item_kind == "text":
                text_title = _safe_text(snap.get("title", "")).strip()
                text_body = str(snap.get("content", ""))
                content_format = str(snap.get("content_format", "text")).strip().lower()
                if text_title:
                    story.append(Paragraph(_para_text(text_title), styles["Heading3"]))
                elif include_meta:
                    story.append(Paragraph("Text block", styles["Heading3"]))
                if include_meta and snap_date:
                    story.append(Paragraph(_para_text(f"Added: {snap_date}"), styles["DDPMeta"]))
                if text_body.strip():
                    if content_format == "html":
                        html_text, html_warnings = _html_block_to_pdf_text(text_body)
                        warnings.extend(html_warnings)
                        if html_text.strip():
                            story.extend(_comment_flowables(html_text, styles))
                        else:
                            story.append(
                                Paragraph(
                                    _para_text("Rich HTML block content is not directly supported in PDF; use HTML export for full fidelity."),
                                    styles["DDPBody"],
                                )
                            )
                        html_imgs = _html_block_image_sources(text_body)
                        for img_src in html_imgs:
                            rendered = False
                            if img_src.lower().startswith("data:image/"):
                                img_bytes = _decode_data_uri_image(img_src)
                                if img_bytes is not None:
                                    try:
                                        iw, ih = ImageReader(img_bytes).getSize()
                                        scale = min(max_img_width / float(iw), max_img_height / float(ih), 1.0)
                                        img_bytes.seek(0)
                                        story_img = Image(img_bytes, width=iw * scale, height=ih * scale)
                                        story.append(Spacer(1, 4))
                                        story.append(story_img)
                                        story.append(Spacer(1, 6))
                                        rendered = True
                                    except Exception as exc:
                                        warnings.append(f"Failed to render rich-text embedded image: {exc}")
                            elif not img_src.lower().startswith(("http://", "https://", "file://")):
                                rel_path = img_src.replace("\\", "/").lstrip("./")
                                img_path = os.path.join(report_assets_root, rel_path)
                                if os.path.isfile(img_path):
                                    try:
                                        iw, ih = ImageReader(img_path).getSize()
                                        scale = min(max_img_width / float(iw), max_img_height / float(ih), 1.0)
                                        story_img = Image(img_path, width=iw * scale, height=ih * scale)
                                        story.append(Spacer(1, 4))
                                        story.append(story_img)
                                        story.append(Spacer(1, 6))
                                        rendered = True
                                    except Exception as exc:
                                        warnings.append(f"Failed to render rich-text image asset {rel_path}: {exc}")
                                else:
                                    warnings.append(f"Missing rich-text image asset: {rel_path}")
                            if not rendered and img_src.lower().startswith(("http://", "https://")):
                                warnings.append(
                                    "A rich HTML text block contains remote image URLs; PDF export does not fetch remote images (HTML export preserves them)."
                                )
                    else:
                        story.extend(_comment_flowables(text_body, styles))
                else:
                    story.append(Paragraph(_para_text("Empty text block."), styles["DDPBody"]))
                continue

            if display_title:
                story.append(Paragraph(_para_text(display_title), styles["Heading3"]))
            if include_meta and snap_date:
                story.append(Paragraph(_para_text(f"Captured: {snap_date}"), styles["DDPMeta"]))

            image_rel = assets.get("image")
            html_rel = assets.get("html")
            if image_rel:
                img_path = os.path.join(report_assets_root, str(image_rel))
                if os.path.isfile(img_path):
                    try:
                        iw, ih = ImageReader(img_path).getSize()
                        scale = min(max_img_width / float(iw), max_img_height / float(ih), 1.0)
                        story_img = Image(img_path, width=iw * scale, height=ih * scale)
                        story.append(Spacer(1, 4))
                        story.append(story_img)
                        story.append(Spacer(1, 6))
                    except Exception as exc:
                        warnings.append(f"Failed to render image asset {image_rel}: {exc}")
                        story.append(
                            Paragraph(
                                _para_text(f"Image snapshot could not be rendered: {image_rel}"),
                                styles["DDPBody"],
                            )
                        )
                else:
                    warnings.append(f"Missing image asset: {image_rel}")
                    story.append(Paragraph(_para_text("Image snapshot missing."), styles["DDPBody"]))
            elif html_rel:
                story.append(
                    Paragraph(
                        _para_text("Interactive plot available in HTML export."),
                        styles["DDPBody"],
                    )
                )

            if comments.strip():
                story.append(Spacer(1, 2))
                story.extend(_comment_flowables(comments, styles))

            if include_meta:
                settings = snap.get("plot_settings", {})
                if isinstance(settings, dict):
                    visible_items = [
                        (k, v) for k, v in settings.items() if k not in hidden_keys
                    ]
                    if visible_items:
                        story.append(Spacer(1, 4))
                        story.append(Paragraph("Plot settings", styles["DDPBody"]))
                        for key, value in visible_items:
                            story.append(
                                Paragraph(
                                    _para_text(f"- {key}: {value}"),
                                    styles["DDPSetting"],
                                )
                            )

    doc.build(story)
    return warnings


def _safe_text(value: Any) -> str:
    return str(value) if value is not None else ""


def _para_text(text: str) -> str:
    return html.escape(text)


def _snapshot_display_title(snap: dict[str, Any], include_meta: bool) -> str:
    if _report_item_kind(snap) == "text":
        raw_title = str(snap.get("title", "")).strip()
        return raw_title or ("Text block" if include_meta else "")
    raw_title = str(snap.get("title", "")).strip()
    raw_user_title = str(snap.get("user_title", "")).strip()
    raw_plot_title = str(snap.get("plot_title", "")).strip()
    effective_user_title = raw_user_title
    if raw_plot_title and effective_user_title == raw_plot_title:
        effective_user_title = ""
    if include_meta:
        return raw_title or "Snapshot"
    return effective_user_title


def _comment_flowables(text: str, styles: Any) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    out: list[Any] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            out.append(Spacer(1, 3))
            continue
        if line.startswith("- "):
            out.append(
                Paragraph(
                    "&#8226; " + _comment_inline_markup(line[2:].strip()),
                    styles["DDPComment"],
                )
            )
            continue
        out.append(Paragraph(_comment_inline_markup(line), styles["DDPComment"]))
    return out


def _comment_inline_markup(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)
    return escaped


def _report_item_kind(item: dict[str, Any]) -> str:
    kind = str(item.get("kind", "snapshot")).strip().lower()
    return kind if kind in {"snapshot", "text"} else "snapshot"


def _html_block_to_pdf_text(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if re.search(r"(?is)<table\b", text):
        warnings.append("A rich HTML text block contains a table; PDF export renders text fallback only.")

    cleaned = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
    cleaned = re.sub(r"(?is)<style\b[^>]*>.*?</style>", "", cleaned)
    cleaned = re.sub(r"(?is)<img\b[^>]*>", "", cleaned)
    cleaned = re.sub(r"(?is)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p\s*>", "\n\n", cleaned)
    cleaned = re.sub(r"(?is)</div\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</li\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<li\b[^>]*>", "- ", cleaned)
    cleaned = re.sub(r"(?is)</h[1-6]\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", "", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), warnings


def _html_block_image_sources(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?is)<img\b[^>]*\bsrc=(['\"])([^'\"]+)\1", text):
        src = (match.group(2) or "").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        out.append(src)
    return out


def _decode_data_uri_image(src: str) -> io.BytesIO | None:
    match = re.match(r"^data:image/[a-zA-Z0-9.+-]+;base64,(.+)$", src, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    try:
        blob = base64.b64decode(match.group(1).strip(), validate=False)
    except Exception:
        return None
    return io.BytesIO(blob)

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.services.report_models import ReportContext


class ReportMarkdownRenderer:
    def __init__(self, template_dir: Path | None = None) -> None:
        self.template_dir = template_dir or Path(__file__).resolve().parent.parent / "templates"
        self.environment = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )

    def render(self, context: ReportContext, template_name: str = "report.md.j2") -> str:
        template = self.environment.get_template(template_name)
        return template.render(report=context).strip() + "\n"

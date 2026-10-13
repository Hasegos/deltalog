from fastapi.templating import Jinja2Templates

from core.constants.source import SOURCES
from core.constants.taxonomy import TOPICS

templates = Jinja2Templates(directory="templates")
templates.env.globals["footer_tools"] = [(s["slug"], s["name"]) for s in SOURCES]
templates.env.globals["footer_topics"] = TOPICS
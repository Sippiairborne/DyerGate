from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from app.auth import require_admin
from app.config import settings

router = APIRouter(dependencies=[Depends(require_admin)])
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/dashboard/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/dashboard/clients", response_class=HTMLResponse)
def clients_ui(request: Request):
    return FileResponse("app/templates/clients.html")


@router.get("/dashboard/packages", response_class=HTMLResponse)
def packages_ui(request: Request):
    return FileResponse("app/templates/packages.html")


@router.get("/dashboard/audit", response_class=HTMLResponse)
def audit_ui(request: Request):
    return FileResponse("app/templates/audit.html")


@router.get("/dashboard/finetune", response_class=HTMLResponse)
def finetune_ui(request: Request):
    return FileResponse("app/templates/finetune.html")


@router.get("/dashboard/eval", response_class=HTMLResponse)
def eval_ui(request: Request):
    return FileResponse("app/templates/eval.html")


@router.get("/dashboard/workflows", response_class=HTMLResponse)
def workflows_ui(request: Request):
    return FileResponse("app/templates/workflows.html")


@router.get("/dashboard/voice", response_class=HTMLResponse)
def voice_ui(request: Request):
    return FileResponse("app/templates/voice.html")


@router.get("/dashboard/images", response_class=HTMLResponse)
def images_ui(request: Request):
    return FileResponse("app/templates/images.html")


@router.get("/dashboard/rag", response_class=HTMLResponse)
def rag_ui(request: Request):
    return FileResponse("app/templates/rag.html")


@router.get("/dashboard/marketplace", response_class=HTMLResponse)
def marketplace_ui(request: Request):
    return FileResponse("app/templates/marketplace.html")


@router.get("/dashboard/integrations", response_class=HTMLResponse)
def integrations_ui(request: Request):
    return FileResponse("app/templates/integrations.html")


@router.get("/dashboard/forecast", response_class=HTMLResponse)
def forecast_ui(request: Request):
    return FileResponse("app/templates/forecast.html")


@router.get("/dashboard/settings", response_class=HTMLResponse)
def settings_ui(request: Request):
    return FileResponse("app/templates/settings.html")

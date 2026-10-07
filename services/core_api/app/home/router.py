from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter()

# Path to the frontend directory relative to this file
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../frontend"))

@router.get("/", summary="Serve the home page")
async def get_home():
    """Serves the main landing page of the platform."""
    home_page = os.path.join(FRONTEND_DIR, "home", "index.html")
    if os.path.exists(home_page):
        return FileResponse(home_page)
    return {"detail": "Home page not found."}

@router.get("/login", summary="Serve the login page")
async def get_login():
    """Serves the login page."""
    login_page = os.path.join(FRONTEND_DIR, "login", "index.html")
    if os.path.exists(login_page):
        return FileResponse(login_page)
    return {"detail": "Login page not found."}

"""Dependencias de FastAPI para proteger rutas con la sesión por cookie."""

from fastapi import HTTPException, Request

from core.config import settings
from core.security import read_session_token


def get_optional_user(request: Request) -> str | None:
    """Usar en rutas HTML: devuelve el usuario autenticado o None.

    La propia ruta decide qué hacer si es None (normalmente redirigir a
    /login) en vez de recibir un error genérico.
    """
    token = request.cookies.get(settings.session_cookie_name)
    return read_session_token(token)


def get_current_user_api(request: Request) -> str:
    """Usar en rutas de API/JSON: exige sesión, o responde 401."""
    usuario = get_optional_user(request)
    if not usuario:
        raise HTTPException(status_code=401, detail="No autenticado")
    return usuario

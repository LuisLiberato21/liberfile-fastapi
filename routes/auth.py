from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from email.mime.text import MIMEText
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import bcrypt
import random
import time
import string
import smtplib

from core.config import settings
from core.db import usuarios_collection
from core.deps import get_optional_user
from core.security import create_session_token

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Roles que un usuario puede elegir al auto-registrarse desde /register-user.
# "Super administrador" y "Administrador" sólo los puede asignar alguien que
# ya inició sesión; de lo contrario cualquier visitante podría crearse una
# cuenta de administrador sin que nadie se lo impida (así estaba el código
# original: el <select> del formulario dejaba elegir cualquier rol y el
# backend lo guardaba tal cual).
ROLES_AUTOASIGNABLES = {"Auxiliar"}


# Modelos de datos
class Usuario(BaseModel):
    cedula: str
    usuario: str
    nombres: str
    apellidos: str
    correo: EmailStr
    direccion: str
    telefono: str
    contraseña: str
    rol: str


# Ruta para mostrar el formulario de registro
@router.get("/register-user", response_class=HTMLResponse)
async def mostrar_registro_usuario(request: Request):
    current_user = get_optional_user(request)
    return templates.TemplateResponse(
        "register_user.html",
        {"request": request, "current_user": current_user, "es_admin": bool(current_user)},
    )


# Registrar usuario
@router.post("/register")
async def registrar_usuario(
    request: Request,
    cedula: str = Form(...),
    usuario: str = Form(...),
    nombres: str = Form(...),
    apellidos: str = Form(...),
    correo_electronico: str = Form(...),
    direccion: str = Form(None),
    telefono: str = Form(None),
    contraseña: str = Form(...),
    rol: str = Form(...),
):
    # Si quien registra NO tiene una sesión iniciada, se trata de un
    # auto-registro público: no se le permite asignarse un rol con
    # privilegios (Administrador / Super administrador).
    current_user = get_optional_user(request)
    if not current_user and rol not in ROLES_AUTOASIGNABLES:
        return JSONResponse(
            content={"detail": "Debes iniciar sesión como administrador para crear usuarios con ese rol."},
            status_code=403,
        )

    # Verificar si el usuario ya existe
    usuario_existente = await usuarios_collection.find_one({"_id": cedula})
    if usuario_existente:
        return JSONResponse(content={"detail": "La cédula ya está registrada"}, status_code=400)

    usuario_existente = await usuarios_collection.find_one({"usuario": usuario})
    if usuario_existente:
        return JSONResponse(content={"detail": "El nombre de usuario ya existe"}, status_code=400)

    correo_existente = await usuarios_collection.find_one({"correo_electronico": correo_electronico})
    if correo_existente:
        return JSONResponse(content={"detail": "El correo electrónico ya está en uso"}, status_code=400)

    # Si el usuario no existe, continúa con el registro
    hashed_password = bcrypt.hashpw(contraseña.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    nuevo_usuario = {
        "_id": cedula,
        "usuario": usuario,
        "nombres": nombres,
        "apellidos": apellidos,
        "correo_electronico": correo_electronico,
        "direccion": direccion,
        "telefono": telefono,
        "contraseña": hashed_password,
        "rol": rol,
    }
    await usuarios_collection.insert_one(nuevo_usuario)

    return JSONResponse(content={"mensaje": "Usuario registrado exitosamente."}, status_code=200)


# Iniciar sesión
@router.post("/login")
async def login(usuario: str = Form(...), contraseña: str = Form(...)):
    usuario_db = await usuarios_collection.find_one({"usuario": usuario})
    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if not bcrypt.checkpw(contraseña.encode("utf-8"), usuario_db["contraseña"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    respuesta = JSONResponse(
        content={
            "mensaje": "Inicio de sesión exitoso, bienvenido",
            "nombres": usuario_db["nombres"],
            "apellidos": usuario_db["apellidos"],
        }
    )
    token = create_session_token(usuario_db["usuario"])
    respuesta.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_max_age_seconds,
    )
    return respuesta


# Página de modificar contraseña
@router.get("/modify-password")
async def modify_password_page(request: Request):
    return templates.TemplateResponse("modify_password.html", {"request": request})


# Modificar contraseña
@router.post("/modify-password")
async def modify_password(
    usuario: str = Form(...),
    contraseña_actual: str = Form(...),
    nueva_contraseña: str = Form(...),
):
    usuario_db = await usuarios_collection.find_one({"usuario": usuario})

    if not usuario_db or not bcrypt.checkpw(
        contraseña_actual.encode("utf-8"), usuario_db["contraseña"].encode("utf-8")
    ):
        return JSONResponse(content={"detail": "Usuario o contraseña actual incorrectos"}, status_code=400)

    nueva_contraseña_hash = bcrypt.hashpw(nueva_contraseña.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    await usuarios_collection.update_one({"usuario": usuario}, {"$set": {"contraseña": nueva_contraseña_hash}})

    return JSONResponse(content={"mensaje": "Contraseña modificada con éxito"}, status_code=200)


# Restablecer contraseña
@router.post("/reset-password")
async def send_reset_email(usuario: str = Form(...), email: str = Form(...)):
    usuario_db = await usuarios_collection.find_one({"usuario": usuario, "correo_electronico": email})
    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario o correo no encontrados")

    codigo_verificacion = generar_codigo_verificacion()
    tiempo_expiracion = time.time() + 600  # Expira en 10 minutos
    await usuarios_collection.update_one(
        {"usuario": usuario},
        {"$set": {"codigo_verificacion": codigo_verificacion, "codigo_expiracion": tiempo_expiracion}},
    )

    enviar_email(email, "Recuperación de contraseña", f"Tu código de verificación es: {codigo_verificacion}")

    return {"mensaje": "Correo de restablecimiento enviado"}


# Página de restablecimiento de contraseña
@router.get("/reset-password")
async def reset_password_page(request: Request):
    return templates.TemplateResponse("reset_password.html", {"request": request})


def generar_codigo_verificacion(length: int = 6) -> str:
    caracteres = string.ascii_letters + string.digits
    return "".join(random.choice(caracteres) for _ in range(length))


def enviar_email(destinatario: str, asunto: str, cuerpo: str) -> None:
    """Envía el correo de recuperación, o lo imprime en consola si no hay
    credenciales SMTP configuradas (modo desarrollo/pruebas)."""
    if not settings.mail_username or not settings.mail_password:
        print(f"[DEV] Correo simulado a {destinatario} — {asunto}: {cuerpo}")
        return

    msg = MIMEText(cuerpo)
    msg["Subject"] = asunto
    msg["From"] = settings.mail_from or settings.mail_username
    msg["To"] = destinatario

    try:
        with smtplib.SMTP_SSL(settings.mail_server, settings.mail_port) as server:
            server.login(settings.mail_username, settings.mail_password)
            server.sendmail(msg["From"], destinatario, msg.as_string())
            print("Correo enviado exitosamente")
    except Exception as e:
        print(f"Error enviando correo: {e}")


@router.post("/verify-code")
async def verificar_codigo(usuario: str = Form(...), codigo: str = Form(...), nueva_contraseña: str = Form(...)):
    usuario_db = await usuarios_collection.find_one({"usuario": usuario})

    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if usuario_db.get("codigo_verificacion") != codigo:
        raise HTTPException(status_code=400, detail="Código incorrecto")

    if time.time() > usuario_db.get("codigo_expiracion", 0):
        raise HTTPException(status_code=400, detail="El código ha expirado")

    hashed_password = bcrypt.hashpw(nueva_contraseña.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    await usuarios_collection.update_one(
        {"usuario": usuario},
        {
            "$set": {"contraseña": hashed_password},
            "$unset": {"codigo_verificacion": "", "codigo_expiracion": ""},
        },
    )

    return JSONResponse(content={"mensaje": "Contraseña actualizada exitosamente"}, status_code=200)

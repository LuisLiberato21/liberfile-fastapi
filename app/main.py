import io
import mimetypes
import os

import gridfs
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from core.config import settings
from core.db import fs, sync_db, usuarios_collection
from core.deps import get_current_user_api, get_optional_user
from routes.auth import router as auth_router

app = FastAPI()

# Configuración de archivos estáticos y plantillas
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(auth_router)


# Modelo para actualizar usuario
class UsuarioUpdate(BaseModel):
    nombres: str
    apellidos: str
    correo_electronico: str
    rol: str


def _require_login(request: Request, current_user: str | None):
    """Para rutas HTML: si no hay sesión, redirige a /login."""
    if not current_user:
        return RedirectResponse(url="/login")
    return None


# Ruta para servir HTML (página de bienvenida pública)
@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# Ruta para mostrar el formulario de login
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: str | None = Depends(get_optional_user)):
    if current_user:
        return RedirectResponse(url="/file-manager")
    return templates.TemplateResponse("login.html", {"request": request})


# NOTA: el inicio de sesión real (POST /login, contra la base de datos y con
# bcrypt) vive en routes/auth.py. Aquí ya no se define un segundo /login:
# la versión original tenía una ruta duplicada que aceptaba el usuario y
# contraseña fijos "admin"/"password" sin tocar la base de datos. Como
# FastAPI usa la primera coincidencia de ruta, ese código nunca se
# ejecutaba, pero seguía siendo una puerta trasera latente en el
# repositorio: se eliminó por completo.


# Ruta para cerrar sesión
@app.get("/logout")
async def logout():
    respuesta = RedirectResponse(url="/")
    respuesta.delete_cookie(settings.session_cookie_name)
    return respuesta


# Ruta para mostrar verify_code.html
@app.get("/verify_code", response_class=HTMLResponse)
async def verify_code_page(request: Request):
    return templates.TemplateResponse("verify_code.html", {"request": request})


# ---- Rutas protegidas: requieren haber iniciado sesión ----

@app.get("/file-manager", response_class=HTMLResponse)
async def file_manager(request: Request, current_user: str | None = Depends(get_optional_user)):
    redirect = _require_login(request, current_user)
    if redirect:
        return redirect
    return templates.TemplateResponse("file_manager.html", {"request": request, "current_user": current_user})


@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, current_user: str | None = Depends(get_optional_user)):
    redirect = _require_login(request, current_user)
    if redirect:
        return redirect
    return templates.TemplateResponse("users.html", {"request": request, "current_user": current_user})


@app.get("/share-files", response_class=HTMLResponse)
async def share_files_page(request: Request, current_user: str | None = Depends(get_optional_user)):
    redirect = _require_login(request, current_user)
    if redirect:
        return redirect
    return templates.TemplateResponse("share_files.html", {"request": request, "current_user": current_user})


@app.get("/admin-user", response_class=HTMLResponse)
async def admin_user_page(request: Request, current_user: str | None = Depends(get_optional_user)):
    redirect = _require_login(request, current_user)
    if redirect:
        return redirect
    return templates.TemplateResponse("admin_user.html", {"request": request, "current_user": current_user})


# ---- Archivos (GridFS) ----

VALID_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}


@app.post("/upload-file/")
async def upload_file(file: UploadFile = File(...), current_user: str = Depends(get_current_user_api)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in VALID_EXTENSIONS:
        return JSONResponse(status_code=400, content={"message": "Tipo de archivo no válido."})

    file_id = fs.put(
        file.file,
        filename=file.filename,
        content_type=mimetypes.guess_type(file.filename)[0],
        metadata={"uploaded_by": current_user},
    )
    return {"file_id": str(file_id), "filename": file.filename}


@app.get("/api/files")
async def list_files(mine: bool = False, current_user: str = Depends(get_current_user_api)):
    # Se consulta directamente la colección de metadatos de GridFS
    # ("fs.files") en vez de fs.find(): es la misma información, en un
    # formato más simple de convertir a JSON para el listado.
    query = {"metadata.uploaded_by": current_user} if mine else {}
    archivos = []
    for doc in sync_db["fs.files"].find(query).sort("uploadDate", -1):
        archivos.append(
            {
                "file_id": str(doc["_id"]),
                "filename": doc.get("filename"),
                "content_type": doc.get("contentType"),
                "length": doc.get("length"),
                "upload_date": doc["uploadDate"].isoformat() if doc.get("uploadDate") else None,
                "uploaded_by": (doc.get("metadata") or {}).get("uploaded_by"),
            }
        )
    return JSONResponse(content=archivos)


@app.get("/download-file/{file_id}")
async def download_file(file_id: str, current_user: str = Depends(get_current_user_api)):
    try:
        grid_out = fs.get(ObjectId(file_id))
    except (InvalidId, gridfs.NoFile):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    return StreamingResponse(
        io.BytesIO(grid_out.read()),
        media_type=grid_out.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{grid_out.filename}"'},
    )


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str, current_user: str = Depends(get_current_user_api)):
    try:
        fs.delete(ObjectId(file_id))
    except InvalidId:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return {"mensaje": "Archivo eliminado correctamente"}


# ---- Usuarios (API usada por users.html) ----

@app.get("/api/usuarios")
async def obtener_usuarios(current_user: str = Depends(get_current_user_api)):
    usuarios = []
    async for usuario in usuarios_collection.find(
        {}, {"_id": 1, "nombres": 1, "apellidos": 1, "correo_electronico": 1, "rol": 1}
    ):
        usuario["_id"] = str(usuario["_id"])
        usuarios.append(usuario)

    return JSONResponse(content=usuarios)


@app.delete("/api/usuarios/{usuario_id}")
async def eliminar_usuario(usuario_id: str, current_user: str = Depends(get_current_user_api)):
    resultado = await usuarios_collection.delete_one({"_id": usuario_id})

    if resultado.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return {"mensaje": "Usuario eliminado correctamente"}


@app.put("/api/usuarios/{usuario_id}")
async def modificar_usuario(
    usuario_id: str, usuario: UsuarioUpdate, current_user: str = Depends(get_current_user_api)
):
    resultado = await usuarios_collection.update_one(
        {"_id": usuario_id},
        {"$set": usuario.dict()},
    )

    if resultado.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return {"mensaje": "Usuario actualizado correctamente"}

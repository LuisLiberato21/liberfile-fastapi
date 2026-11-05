import io
import mimetypes
import os
from datetime import datetime

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
from core.db import compartidos_collection, fs, sync_db, usuarios_collection
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


# Modelo para compartir un archivo (ver POST /api/share)
class CompartirArchivo(BaseModel):
    file_id: str
    destinatario: str
    permiso: str  # "lectura" o "edicion"


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


def _ids_compartidos_conmigo(current_user: str) -> list[ObjectId]:
    """IDs (como ObjectId) de archivos que otros le compartieron a current_user."""
    ids = []
    for doc in compartidos_collection.find({"destinatario": current_user}, {"file_id": 1}):
        try:
            ids.append(ObjectId(doc["file_id"]))
        except InvalidId:
            continue
    return ids


@app.get("/api/files")
async def list_files(mine: bool = False, current_user: str = Depends(get_current_user_api)):
    # Se consulta directamente la colección de metadatos de GridFS
    # ("fs.files") en vez de fs.find(): es la misma información, en un
    # formato más simple de convertir a JSON para el listado.
    #
    # "mine=true" (pestaña "Propios") sigue siendo sólo lo que subiste tú.
    # Sin ese parámetro (pestaña "Todos") YA NO significa "todos los
    # archivos de todos los usuarios": por privacidad, sólo se ven los
    # propios más los que otros te hayan compartido explícitamente desde
    # /share-files (ver POST /api/share). Antes cualquier usuario veía y
    # podía descargar el archivo de cualquier otro.
    if mine:
        query = {"metadata.uploaded_by": current_user}
    else:
        query = {
            "$or": [
                {"metadata.uploaded_by": current_user},
                {"_id": {"$in": _ids_compartidos_conmigo(current_user)}},
            ]
        }
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

    # Sólo el dueño, o alguien a quien se le haya compartido el archivo,
    # puede descargarlo. Se responde 404 (no 403) para no revelar que el
    # archivo existe a quien no tiene acceso a él.
    propietario = (grid_out.metadata or {}).get("uploaded_by")
    if propietario != current_user:
        compartido = compartidos_collection.find_one(
            {"file_id": file_id, "destinatario": current_user}
        )
        if not compartido:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")

    return StreamingResponse(
        io.BytesIO(grid_out.read()),
        media_type=grid_out.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{grid_out.filename}"'},
    )


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str, current_user: str = Depends(get_current_user_api)):
    try:
        file_oid = ObjectId(file_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    archivo = sync_db["fs.files"].find_one({"_id": file_oid})
    if not archivo:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    # Sólo el propietario puede eliminar el archivo (antes cualquier
    # usuario autenticado podía borrar el archivo de cualquier otro).
    propietario = (archivo.get("metadata") or {}).get("uploaded_by")
    if propietario != current_user:
        raise HTTPException(status_code=403, detail="Sólo el propietario puede eliminar este archivo")

    fs.delete(file_oid)
    # Limpia también los permisos de "compartido" que apuntaban a este
    # archivo, para no dejar registros huérfanos en archivos_compartidos.
    compartidos_collection.delete_many({"file_id": file_id})
    return {"mensaje": "Archivo eliminado correctamente"}


# ---- Compartir archivos (usado por share_files.html) ----
#
# La pantalla de "Compartir Archivos" existía sólo como maqueta visual: el
# listado de archivos y de usuarios estaba escrito a mano en el HTML
# ("Archivo1.txt", "Usuario 1"...) y el botón de compartir sólo mostraba un
# alert(), sin tocar el servidor. Lo que sigue es la lógica real: un
# registro por cada (archivo, destinatario) con el permiso otorgado.


@app.post("/api/share")
async def compartir_archivo(datos: CompartirArchivo, current_user: str = Depends(get_current_user_api)):
    if datos.permiso not in ("lectura", "edicion"):
        raise HTTPException(status_code=400, detail="El permiso debe ser 'lectura' o 'edicion'")

    try:
        archivo = sync_db["fs.files"].find_one({"_id": ObjectId(datos.file_id)})
    except InvalidId:
        archivo = None
    if not archivo:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    # Sólo quien subió el archivo puede compartirlo.
    propietario = (archivo.get("metadata") or {}).get("uploaded_by")
    if propietario != current_user:
        raise HTTPException(status_code=403, detail="Sólo el propietario puede compartir este archivo")

    if datos.destinatario == current_user:
        raise HTTPException(status_code=400, detail="No puedes compartir un archivo contigo mismo")

    destinatario_existe = await usuarios_collection.find_one({"usuario": datos.destinatario})
    if not destinatario_existe:
        raise HTTPException(status_code=404, detail="El usuario destinatario no existe")

    compartidos_collection.update_one(
        {"file_id": datos.file_id, "destinatario": datos.destinatario},
        {
            "$set": {
                "file_id": datos.file_id,
                "filename": archivo.get("filename"),
                "propietario": current_user,
                "destinatario": datos.destinatario,
                "permiso": datos.permiso,
                "fecha": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    return {
        "mensaje": f"Archivo '{archivo.get('filename')}' compartido con {datos.destinatario} "
        f"({'solo lectura' if datos.permiso == 'lectura' else 'edición'})."
    }


@app.get("/api/shared-with-me")
async def archivos_compartidos_conmigo(current_user: str = Depends(get_current_user_api)):
    compartidos = []
    for doc in compartidos_collection.find({"destinatario": current_user}).sort("fecha", -1):
        compartidos.append(
            {
                "file_id": doc["file_id"],
                "filename": doc.get("filename"),
                "propietario": doc.get("propietario"),
                "permiso": doc.get("permiso"),
                "fecha": doc["fecha"].isoformat() if doc.get("fecha") else None,
            }
        )
    return JSONResponse(content=compartidos)


# ---- Usuarios (API usada por users.html) ----

@app.get("/api/usuarios")
async def obtener_usuarios(current_user: str = Depends(get_current_user_api)):
    usuarios = []
    async for usuario in usuarios_collection.find(
        {}, {"_id": 1, "usuario": 1, "nombres": 1, "apellidos": 1, "correo_electronico": 1, "rol": 1}
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

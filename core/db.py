"""Conexión única y compartida a MongoDB.

La versión original creaba un AsyncIOMotorClient distinto en app/main.py y
otro más en routes/auth.py (y un MongoClient síncrono adicional para
GridFS). Cada cliente abre su propio pool de conexiones, así que tener
varios sin necesidad sólo desperdicia conexiones. Aquí se crea una sola vez
y el resto de módulos lo importan.
"""

import gridfs
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from core.config import settings

# Cliente asíncrono (Motor), usado por las rutas normales de la app.
motor_client = AsyncIOMotorClient(settings.mongo_uri)
db = motor_client[settings.mongo_db_name]
usuarios_collection = db.get_collection("usuarios")

# GridFS requiere un cliente síncrono de pymongo.
sync_client = MongoClient(settings.mongo_uri)
sync_db = sync_client[settings.mongo_db_name]
fs = gridfs.GridFS(sync_db)

# Permisos de "compartir archivo" (quién puede ver el archivo de quién, y con
# qué permiso). Vive en el cliente síncrono porque siempre se consulta junto
# con fs.files, igual que usuarios_collection vive en el async porque se usa
# junto al resto de rutas de usuarios.
compartidos_collection = sync_db.get_collection("archivos_compartidos")

# Liberfile

Gestor de archivos con autenticación, construido con **FastAPI + MongoDB
(GridFS)**. Este README documenta el estado del proyecto después de
corregirlo y dejarlo funcional, y da el paso a paso para correrlo localmente
o desplegarlo en internet.

## ⚠️ Acción urgente antes de hacer nada más

El código original (el que estaba en este repositorio) tenía **la
contraseña de un clúster de MongoDB Atlas y la contraseña de aplicación de
un correo de Gmail escritas directamente en texto plano** dentro de
`app/main.py` y `routes/auth.py`, y ese código ya fue subido a GitHub en
commits anteriores. Aunque aquí ya se quitaron del código fuente, **siguen
expuestas en el historial de git** y en cualquier copia que se haya hecho
del proyecto. Antes de desplegar nada:

1. Entra a MongoDB Atlas y **rota (cambia) la contraseña** del usuario
   `admin` del clúster `liberfile`, o mejor aún, crea un usuario nuevo y
   borra el viejo.
2. Entra a la cuenta de Gmail `liberfile@gmail.com` y **revoca esa
   contraseña de aplicación** desde "Contraseñas de aplicaciones", y genera
   una nueva si la vas a seguir usando.

Esto no es opcional: mientras no rotes esas credenciales, cualquiera que
haya visto el repositorio (o lo vea en el futuro, revisando el historial)
puede entrar directamente a la base de datos real.

## Qué se corrigió

| Problema encontrado | Antes | Ahora |
|---|---|---|
| Credenciales de Mongo y Gmail hardcodeadas en el código | Visibles en texto plano en 2 archivos | Se leen de variables de entorno (`.env`, nunca se sube a git) |
| Sin control de sesión | Cualquiera con la URL entraba a `/file-manager`, `/users`, `/share-files`, `/admin-user`, `/api/usuarios`, subía/descargaba archivos, sin haber iniciado sesión | Esas rutas ahora exigen una cookie de sesión firmada; sin sesión válida, redirigen a `/login` (páginas) o responden `401` (API) |
| Registro público podía crear un "Super administrador" | El formulario de registro dejaba elegir cualquier rol sin autenticarse | El registro público sólo permite el rol "Auxiliar"; roles con privilegios sólo los puede asignar un administrador ya autenticado |
| Descarga de archivos rota | `/download-file/{id}` sólo devolvía el nombre del archivo en JSON, nunca el contenido | Ahora transmite el archivo real (bytes) con el nombre y tipo correctos |
| Ruta de login duplicada | Existía un segundo `/login` muerto que aceptaba el usuario/clave fijos `admin`/`password` (nunca se ejecutaba porque Starlette ya hacía match con el real, pero quedaba como puerta trasera latente) | Se eliminó por completo |
| Gestor de archivos sin funcionalidad real | Los botones de subir/listar archivos sólo mostraban `alert()` | Ahora sube, lista, descarga y elimina archivos de verdad contra GridFS |
| Tres clientes de MongoDB distintos abiertos a la vez | `app/main.py` y `routes/auth.py` cada uno creaba su propia conexión | Una sola conexión compartida en `core/db.py` |
| `core/`, `routes/` sin `__init__.py` | Funcionaba por casualidad según desde dónde se ejecutara | Se agregaron, para que los imports sean confiables en cualquier entorno |

Todo este flujo (registro, bloqueo de auto-registro como admin, login,
rutas protegidas, subir/descargar/eliminar archivo, recuperación de
contraseña por código) se probó de punta a punta antes de entregarte el
proyecto.

## Estructura

```
liberfile/
├── app/main.py          # Rutas principales (páginas, archivos, usuarios)
├── routes/auth.py        # Registro, login, recuperación de contraseña
├── core/
│   ├── config.py          # Configuración (variables de entorno)
│   ├── db.py              # Conexión compartida a MongoDB + GridFS
│   ├── security.py        # Cookies de sesión firmadas
│   └── deps.py             # Dependencias de FastAPI para proteger rutas
├── templates/            # HTML (Jinja2)
├── static/               # CSS, logo
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 1. Correr el proyecto en tu computador (recomendado para probar/testear)

Necesitas tener instalado **Docker Desktop** (incluye Docker Compose).

1. Copia el archivo de configuración de ejemplo:
   ```bash
   cp .env.example .env
   ```
2. Abre `.env` y genera una clave secreta propia para `SECRET_KEY`:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Pega el resultado como valor de `SECRET_KEY` en `.env`. Deja
   `MONGO_URI=mongodb://mongo:27017` tal cual (apunta al Mongo que levanta
   Docker Compose). Puedes dejar las variables de correo vacías: mientras
   estén vacías, el código de recuperación de contraseña se imprime en la
   consola del servidor en vez de enviarse por correo real (muy útil para
   pruebas).
3. Levanta todo con un solo comando, desde la carpeta del proyecto:
   ```bash
   docker compose up --build
   ```
4. Abre tu navegador en **http://localhost:8000**.
5. Para apagarlo: `Ctrl+C` y luego `docker compose down` (agrega `-v` si
   además quieres borrar los datos de Mongo).

Con esto ya tienes el sistema corriendo para hacer tus pruebas de software
(funcionales, de seguridad, etc.) del ACA.

### Alternativa sin Docker (Python local)

Si prefieres no usar Docker, necesitas un MongoDB accesible (local o
Atlas) y Python 3.11+:

```bash
python3 -m venv venv
source venv/bin/activate      # En Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # y edítalo con tu propia cadena de Mongo y tu SECRET_KEY
uvicorn app.main:app --reload --port 8000
```

---

## 2. Desplegarlo en internet (para que tenga una URL pública)

La combinación más simple y gratuita para un proyecto como este es
**Render** (para la app) + **MongoDB Atlas** (para la base de datos nueva,
con credenciales rotadas).

### 2.1 Crear la base de datos (MongoDB Atlas)

1. Entra a [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas) y
   crea un clúster gratuito (M0).
2. En "Database Access", crea un usuario nuevo con una contraseña fuerte
   (no reutilices la contraseña vieja que quedó expuesta).
3. En "Network Access", agrega `0.0.0.0/0` (permitir desde cualquier IP) —
   suficiente para un proyecto académico.
4. En "Connect" → "Drivers", copia la cadena de conexión
   (`mongodb+srv://usuario:clave@.../`). Esa es tu `MONGO_URI` real.

### 2.2 Subir el proyecto a GitHub

```bash
git add -A
git commit -m "Corregir seguridad y funcionalidad del proyecto, dejarlo desplegable"
git push origin main
```

(Si el repo remoto no es el tuyo o no tienes permiso de escritura, crea uno
nuevo en tu cuenta de GitHub y cambia el remoto: `git remote set-url origin <tu-url>`.)

### 2.3 Desplegar en Render

1. Entra a [render.com](https://render.com) y crea una cuenta (puedes
   entrar con tu cuenta de GitHub).
2. "New +" → "Web Service" → selecciona tu repositorio `liberfile`.
3. Configura:
   - **Runtime**: Docker (Render detecta el `Dockerfile` automáticamente).
   - **Instance type**: Free.
4. En la pestaña "Environment", agrega las variables (sin comillas):
   - `MONGO_URI` → la cadena `mongodb+srv://...` de Atlas
   - `MONGO_DB_NAME` → `liberfile_db`
   - `SECRET_KEY` → la clave generada en el paso 1.2
   - (opcional) `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_SERVER`, `MAIL_PORT` si quieres correo real
5. Clic en "Create Web Service". Render construye la imagen y la despliega;
   al terminar te da una URL pública tipo
   `https://liberfile.onrender.com`.

Esa URL pública es la que puedes usar para las capturas de pantalla y las
pruebas de tu informe, y para el enlace del repositorio en la entrega.

> Nota: en el plan gratuito de Render, el servicio "se duerme" tras varios
> minutos sin tráfico y tarda unos segundos en responder a la primera
> petición después de estar inactivo — es normal, no es un error.

---

## 3. Usuarios de prueba

El sistema no trae usuarios precargados. Crea el primero desde
`/register-user` (al no haber sesión, sólo se puede crear con rol
"Auxiliar"). Para tener un usuario con rol de administrador, créalo así:

1. Regístrate normalmente (rol Auxiliar) desde `/register-user`.
2. Conéctate a la base de datos (Mongo Compass, o `mongosh` con tu
   `MONGO_URI`) y, en la colección `usuarios`, cambia manualmente el campo
   `rol` de ese usuario a `"Super administrador"`.
3. Inicia sesión con ese usuario: ahora sí verás las opciones de
   administrador al crear nuevos usuarios desde `/users`.

Esto es intencional: así el rol de administrador nunca se puede obtener
por auto-registro público (ese era justamente uno de los fallos de
seguridad corregidos).

## 4. Pendientes conocidos (para mencionar en tu informe si aplica)

- `share_files.html` y `admin_user.html` son pantallas de interfaz que
  todavía no están conectadas a ninguna lógica de backend (quedaron así en
  la versión original). Quedan protegidas por sesión, pero su contenido es
  estático.
- No hay organización real en carpetas ("Todos"/"Propios" filtra por quién
  subió el archivo, pero no hay carpetas anidadas).
- Las contraseñas de los usuarios se guardan con `bcrypt` (correcto), pero
  no hay límite de intentos de login ni de envío de códigos de
  recuperación (protección contra fuerza bruta) — es un buen candidato
  para una de las pruebas de seguridad de tu ACA.

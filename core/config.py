from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración centralizada de la aplicación.

    Todos los valores se leen de variables de entorno (o de un archivo .env
    en desarrollo). Nunca se deben dejar credenciales reales escritas aquí:
    eso fue justamente uno de los problemas de seguridad encontrados en la
    versión original del proyecto (usuario y contraseña de MongoDB Atlas y
    de Gmail quedaban expuestos directamente en el código fuente).
    """

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "liberfile_db"

    secret_key: str = "inseguro-cambiar-en-produccion"
    session_cookie_name: str = "liberfile_session"
    session_max_age_seconds: int = 60 * 60 * 8  # 8 horas

    mail_username: str | None = None
    mail_password: str | None = None
    mail_from: str | None = None
    mail_server: str = "smtp.gmail.com"
    mail_port: int = 465

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()

# Alias para mantener compatibilidad con el código existente que importaba
# MONGO_DETAILS directamente desde este módulo.
MONGO_DETAILS = settings.mongo_uri

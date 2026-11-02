"""Manejo de sesiones mediante cookies firmadas.

La versión original del proyecto no tenía ningún mecanismo de sesión:
cualquier persona que conociera las URLs (/file-manager, /users,
/share-files, /admin-user, /api/usuarios, etc.) podía usarlas sin haber
iniciado sesión. Este módulo agrega un mecanismo simple pero real de
autenticación basado en cookies firmadas (itsdangerous), sin necesidad de
una tabla de sesiones ni dependencias nuevas.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from core.config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="liberfile-session")


def create_session_token(usuario: str) -> str:
    """Crea un token firmado que representa la sesión de un usuario."""
    return _serializer.dumps({"usuario": usuario})


def read_session_token(token: str | None) -> str | None:
    """Valida un token de sesión y devuelve el nombre de usuario, o None."""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("usuario")

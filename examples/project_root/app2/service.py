from app1.models import User
from plugins.auth.backend import AuthBackend


def make_user() -> User:
    """Create a user, exercising the cross-package imports above."""
    AuthBackend()
    return User()

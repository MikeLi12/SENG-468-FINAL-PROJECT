import jwt
from datetime import datetime, timedelta, timezone


class JWTManager:
    def __init__(self):
        self.secret_key = open("/run/secrets/jwt-key", "r").read().strip()
        self.algorithm = "HS256"
        self.exp_hours = 24

        if not self.secret_key:
            raise ValueError("JWT secret key is not set")

    def create_token(self, user_id, username):
        now = datetime.now(timezone.utc)

        payload = {
            "sub": str(user_id),
            "user_id": str(user_id),
            "username": username,
            "iat": now,
            "exp": now + timedelta(hours=self.exp_hours),
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def validate_token(self, token):
        try:
            return jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
            )
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

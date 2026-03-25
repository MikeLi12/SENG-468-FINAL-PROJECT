import os
import jwt
from datetime import datetime, timedelta, timezone


class JWTManager:
    def __init__(self):
        self.secret_key = open("/run/secrets/jwt-key").read().rstrip()
        self.algorithm = "HS256"
        self.exp_hours = 24

        if not self.secret_key:
            raise ValueError("JWT_SECRET_KEY is not set")

    def create_token(self, username):
        now = datetime.now(timezone.utc)
        payload = {
            "sub": username,
            "iat": now,
            "exp": now + timedelta(hours=self.exp_hours),
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def validate_token(self, token):
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload

        except jwt.ExpiredSignatureError:
            return None

        except jwt.InvalidTokenError:
            return None

    def get_username_from_token(self, token):
        payload = self.validate_token(token)
        if payload is None:
            return None
        return payload.get("sub")

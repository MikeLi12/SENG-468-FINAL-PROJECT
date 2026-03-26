from werkzeug.security import generate_password_hash, check_password_hash


class LoginManager:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()

    def get_user(self, username):
        self.cur.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,),
        )
        return self.cur.fetchone()

    def validate_login(self, username, password):
        user = self.get_user(username)

        if user is None:
            return None

        user_id, db_username, db_password_hash = user

        if not check_password_hash(db_password_hash, password):
            return None

        return {
            "user_id": user_id,
            "username": db_username,
        }

    def register_user(self, username, password):
        existing_user = self.get_user(username)
        if existing_user is not None:
            return None

        password_hash = generate_password_hash(password)

        self.cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, password_hash),
        )
        self.conn.commit()

        return self.get_user(username)

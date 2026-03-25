from db.conn import PostgresConnection
from werkzeug.security import generate_password_hash, check_password_hash

class LoginManager:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()

    def get_user(self, usr):
        print("fetching user instance...")
        self.cur.execute("SELECT username, password_hash FROM users WHERE username = %s",
            (usr, )
        )
        return self.cur.fetchone()

    def username_is_unique(self, usr):
        print("validating username uniqueness...")
        result = self.get_user(usr)
        return result is None
        
    def validate_login(self, usr, pswd):
        print("validating user login...")
        result = self.get_user(usr)
        if result is None:
            print("user not found")
            return False

        print("user found, comparing passwords")
        db_username, db_password_hash = result
        print("db_username:", db_username)
        print("typed password:", pswd)
        print("stored hash:", db_password_hash)

        valid = check_password_hash(db_password_hash, pswd)

        if not valid:
            print("password does not match")
            return False
        
        print("passwords match")
        return valid


    def register_user(self, usr, pswd):
        print("registering user...")
        
        if self.username_is_unique(usr):
            pswd_hash = generate_password_hash(pswd)
            self.cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                (usr, pswd_hash)
            )
            self.conn.commit()
            return self.validate_login(usr, pswd)

        return False
    

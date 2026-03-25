import psycopg
import time

class PostgresConnection:
    def __init__(self):
        self.host = "db"
        self.dbname = "userauth"
        self.user = "userauth"
        self.password = open("/run/secrets/userauth-pass").read().strip()

    def connect(self, retries=5, delay=5):
        conn = None
        for i in range(retries):
            try:
                print("attempting connection...")
                conn = psycopg.connect(
                    host=self.host,
                    dbname=self.dbname, 
                    user=self.user, 
                    password=self.password
                )
                print("connected successfully")
                return conn

            except Exception as e:
                print("could not connect to db:")
                print(e)
                time.sleep(delay)
        return None


import psycopg
import time
import sys

DB_HOST = "db"
DB_NAME = "userauth"
DB_USER = "userauth"
DB_PASSWORD = open("/run/secrets/userauth-pass").read().strip()

def connect():
    conn = None
    for i in range(5):
        try:
            print("attempting connection...")
            conn = psycopg.connect(
                    host=DB_HOST,
                    dbname=DB_NAME, 
                    user=DB_USER, 
                    password=DB_PASSWORD)
            time.sleep(5)
        except Exception as e:
            print("could not connect to db:")
            print(e)
    return conn

def table_exists(cur):
    cur.execute("""
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = 'users'
    )
    """)
    return cur.fetchone()[0]

def create_table(cur):
    cur.execute("""
    CREATE TABLE users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(100) UNIQUE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )
    """)

def init():  
    conn = connect()
    cur = conn.cursor()
    if table_exists(cur):
        print("user table found, skipping table creation")
    else:
        print("no user table found, initializing ...")
        create_table(cur)
        conn.commit()
        print("table created")
    

if __name__ == "__main__":
    init()

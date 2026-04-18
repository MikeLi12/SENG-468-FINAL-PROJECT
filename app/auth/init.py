import psycopg
import time
import sys
from db.conn import PostgresConnection

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
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    )
    """)

def init():  
    db = PostgresConnection()
    conn = db.connect(retries=5, delay=5)
    cur = conn.cursor()
    if table_exists(cur):
        print("user table found, skipping table creation")
    else:
        print("no user table found, initializing ...")
        create_table(cur)
        conn.commit()
        print("table created")
    
    conn.close()
    print("connection closed")
    

if __name__ == "__main__":
    init()

import psycopg
from werkzeug.security import generate_password_hash
from db.conn import PostgresConnection
from loginman import LoginManager
from flask import Flask, render_template, request, jsonify, redirect, url_for
                
app = Flask(__name__)

@app.route("/")
def homepage():
    return redirect(url_for("register"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    
    result = check_request_data(request)
    if result is None:
        return "Bad request", 400

    conn, username, password = result
    try:
        login = LoginManager(conn)
        valid = login.validate_login(username, password)

        if not valid:
            return "Invalid login", 409
        return redirect(url_for("dashboard", user=username)), 201
    finally:
        print("connection closed")
        conn.close()
    

@app.route("/register", methods=["GET","POST"])
def register(): 
    if request.method == "GET":
        return render_template("register.html")

    result = check_request_data(request)
    if result is None:
        return "Bad request", 400

    conn, username, password = result
    try:
        manager = LoginManager(conn)
        success = manager.register_user(username, password)

        if not success:
            return "User already exists", 409
        return redirect(url_for("dashboard", user=username)), 201

    finally:
        conn.close()


@app.route("/dashboard/<user>")
def dashboard(user):
    return render_template("dashboard.html", user=user) 

def check_request_data(req):

    username = req.form.get("username")
    password = req.form.get("password")

    if not username or not password:
        return None

    conn = PostgresConnection().connect()
    if conn is None:
        return None

    return conn, username, password


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

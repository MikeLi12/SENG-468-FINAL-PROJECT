import psycopg
from werkzeug.security import generate_password_hash
from db.conn import PostgresConnection
from db.loginman import LoginManager
from auth.jwtman import JWTManager
from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response
                
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
            return "Invalid login", 401

        jwt_man = JWTManager()
        token = jwt_man.create_token(username)

        response = make_response(redirect(url_for("dashboard", user=username)))
        response.set_cookie(
            "token",
            token,
            httponly=True,
            max_age= 60 * 60 * 24,
            samesite="Lax",
        )
        return response

    finally:
        conn.close()
        print("connection closed")
    

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

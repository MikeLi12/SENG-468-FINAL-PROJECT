from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    make_response,
)

from db.conn import PostgresConnection
from auth.loginman import LoginManager
from auth.jwtman import JWTManager

app = Flask(__name__)


def get_request_credentials(req):
    username = (req.form.get("username") or "").strip()
    password = (req.form.get("password") or "").strip()

    if not username or not password:
        return None

    conn = PostgresConnection().connect()
    if conn is None:
        return None

    return conn, username, password


def get_current_user():
    token = request.cookies.get("token")
    if not token:
        return None

    payload = JWTManager().validate_token(token)
    if payload is None:
        return None

    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
    }


@app.route("/")
def homepage():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        token = request.cookies.get("token")

        if token:
            jwt_manager = JWTManager()
            payload = jwt_manager.validate_token(token)

            if payload is not None:
                username = payload.get("username")
                return redirect(url_for("dashboard", usr=username))

        return render_template("login.html")

    result = get_request_credentials(request)
    if result is None:
        return "Bad request", 400

    conn, username, password = result

    try:
        login_manager = LoginManager(conn)
        user = login_manager.validate_login(username, password)

        if user is None:
            return "Invalid login", 401

        token = JWTManager().create_token(
            user_id=user["user_id"],
            username=user["username"],
        )

        response = make_response(
            redirect(url_for("dashboard", usr=user["username"]))
        )
        response.set_cookie(
            "token",
            token,
            httponly=True,
            max_age=60 * 60 * 24,
            samesite="Lax",
        )
        return response

    finally:
        conn.close()

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    result = get_request_credentials(request)
    if result is None:
        return "Bad request", 400

    conn, username, password = result

    try:
        login_manager = LoginManager(conn)
        user_row = login_manager.register_user(username, password)

        if user_row is None:
            return "User already exists", 409

        user_id, db_username, _ = user_row

        token = JWTManager().create_token(
            user_id=user_id,
            username=db_username,
        )

        response = make_response(
            redirect(url_for("dashboard", usr=db_username))
        )
        response.set_cookie(
            "token",
            token,
            httponly=True,
            max_age=60 * 60 * 24,
            samesite="Lax",
        )
        return response

    finally:
        conn.close()


@app.route("/logout")
def logout():
    response = make_response(redirect(url_for("login")))
    response.delete_cookie("token")
    return response


@app.route("/dashboard/<usr>")
def dashboard(usr):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    if current_user["username"] != usr:
        return "Unauthorized", 403

    return render_template("dashboard.html", usr=usr)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
def get_current_user():
    token = request.cookies.get("token")
    if not token:
        return None

    jwt_manager = JWTManager()
    payload = jwt_manager.validate_token(token)

    if payload is None:
        return None

    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
    }

@app.route("/my-files")
def my_files():
    user = get_current_user()
    if user is None:
        return redirect(url_for("login"))

    return f"user id is {user['user_id']}"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

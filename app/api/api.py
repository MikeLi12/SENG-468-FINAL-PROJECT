from flask import Flask, render_template, request, jsonify
import psycopg

app = Flask(__name__)

@app.route("/")
def homepage():
    return render_template('welcome.html')

@app.route("/login")
def login():
    return

@app.route("/register")
def register():
    return

@app.route("/dashboard")
def dashboard():
    return

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session
)

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)

from google.oauth2 import id_token
from google.auth.transport import requests

import os


# --------------------------------------------------
# FLASK CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "development-secret"
)

app.config["GOOGLE_CLIENT_ID"] = os.environ.get(
    "GOOGLE_CLIENT_ID"
)
# --------------------------------------------------
# DATABASE CONFIGURATION
# --------------------------------------------------

database_url = os.environ.get("DATABASE_URL")

if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = (
    database_url
    or "sqlite:///goinn.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --------------------------------------------------
# LOGIN MANAGER
# --------------------------------------------------

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"


# --------------------------------------------------
# USER MODEL
# --------------------------------------------------

class User(UserMixin, db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    google_id = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    name = db.Column(
        db.String(120),
        nullable=False
    )

    email = db.Column(
        db.String(160),
        unique=True,
        nullable=False
    )

    contact = db.Column(
        db.String(30),
        nullable=True
    )

    role = db.Column(
        db.String(30),
        default="user",
        nullable=False
    )


# --------------------------------------------------
# LOAD USER
# --------------------------------------------------

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def home():

    return render_template(
        "home.html"
    )


# --------------------------------------------------
# LOGIN PAGE
# --------------------------------------------------

@app.route("/login")
def login():

    return render_template(
        "login.html"
    )


# --------------------------------------------------
# GOOGLE LOGIN
# --------------------------------------------------

@app.route(
    "/google-login",
    methods=["POST"]
)
def google_login():

    credential = request.form.get(
        "credential"
    )

    if not credential:

        return "Google credential missing", 400

    try:

        google_user = id_token.verify_oauth2_token(
            credential,
            requests.Request(),
            os.environ["GOOGLE_CLIENT_ID"]
        )

        google_id = google_user["sub"]

        email = google_user.get(
            "email"
        )

        name = google_user.get(
            "name"
        )

        if not email:

            return "Google account email not available", 400


        # ------------------------------------------
        # CHECK EXISTING USER
        # ------------------------------------------

        user = User.query.filter_by(
            google_id=google_id
        ).first()


        # ------------------------------------------
        # CREATE NEW USER
        # ------------------------------------------

        if not user:

            user = User(
                google_id=google_id,
                name=name or "Goinn User",
                email=email,
                role="user"
            )

            db.session.add(user)

            db.session.commit()


        # ------------------------------------------
        # LOGIN
        # ------------------------------------------

        login_user(user)

        return redirect(
            url_for("user_dashboard")
        )


    except ValueError:

        return "Invalid Google login token", 400


# --------------------------------------------------
# USER DASHBOARD
# --------------------------------------------------

@app.route("/user")
@login_required
def user_dashboard():

    return render_template(
        "user_dashboard.html",
        user=current_user
    )


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(
        url_for("home")
    )


# --------------------------------------------------
# CREATE DATABASE TABLES
# --------------------------------------------------

with app.app_context():

    db.create_all()


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    app.run()

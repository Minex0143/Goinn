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


# ==================================================
# FLASK CONFIGURATION
# ==================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "development-secret"
)

app.config["GOOGLE_CLIENT_ID"] = os.environ.get(
    "GOOGLE_CLIENT_ID"
)


# ==================================================
# DATABASE CONFIGURATION
# ==================================================

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


# ==================================================
# LOGIN MANAGER
# ==================================================

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"


# ==================================================
# USER MODEL
# ==================================================

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


# ==================================================
# LOAD LOGGED-IN USER
# ==================================================

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# ==================================================
# HOME
# ==================================================

@app.route("/")
def home():

    return render_template(
        "home.html"
    )


# ==================================================
# LOGIN
# ==================================================

@app.route("/login")
def login():

    # If already logged in, don't show login page
    if current_user.is_authenticated:

        return redirect(
            url_for("user_dashboard")
        )

    return render_template(
        "login.html"
    )


# ==================================================
# GOOGLE LOGIN
# ==================================================

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

        # ------------------------------------------
        # VERIFY GOOGLE TOKEN
        # ------------------------------------------

        google_user = id_token.verify_oauth2_token(
            credential,
            requests.Request(),
            app.config["GOOGLE_CLIENT_ID"]
        )

        google_id = google_user.get("sub")

        email = google_user.get("email")

        name = google_user.get("name")


        # ------------------------------------------
        # BASIC VALIDATION
        # ------------------------------------------

        if not google_id:

            return "Google ID missing", 400

        if not email:

            return "Google account email not available", 400


        # ------------------------------------------
        # CHECK EXISTING USER
        # ------------------------------------------

        user = User.query.filter_by(
            google_id=google_id
        ).first()


        # ------------------------------------------
        # EXISTING USER
        # ------------------------------------------

        if user:

            # If contact number already exists,
            # login directly.
            if user.contact:

                login_user(user)

                return redirect(
                    url_for("user_dashboard")
                )

            # Existing account but profile
            # is incomplete.
            session["profile_google_id"] = google_id
            session["profile_email"] = email
            session["profile_name"] = name or "Goinn User"

            return redirect(
                url_for("complete_profile")
            )


        # ------------------------------------------
        # CHECK EMAIL
        # ------------------------------------------

        # This protects against an email already
        # existing with a different Google ID.
        existing_email_user = User.query.filter_by(
            email=email
        ).first()

        if existing_email_user:

            return (
                "An account already exists with this email. "
                "Please contact Goinn support.",
                409
            )


        # ------------------------------------------
        # NEW USER
        # ------------------------------------------

        session["profile_google_id"] = google_id
        session["profile_email"] = email
        session["profile_name"] = name or "Goinn User"


        return redirect(
            url_for("complete_profile")
        )


    except ValueError:

        return "Invalid Google login token", 400

    except Exception as error:

        print("Google login error:", error)

        return "Unable to complete Google login", 500


# ==================================================
# COMPLETE PROFILE
# ==================================================

@app.route(
    "/complete-profile",
    methods=["GET", "POST"]
)
def complete_profile():

    # ------------------------------------------
    # MAKE SURE GOOGLE LOGIN HAPPENED
    # ------------------------------------------

    google_id = session.get(
        "profile_google_id"
    )

    email = session.get(
        "profile_email"
    )

    google_name = session.get(
        "profile_name"
    )


    if not google_id or not email:

        return redirect(
            url_for("login")
        )


    # ------------------------------------------
    # GET
    # ------------------------------------------

    if request.method == "GET":

        return render_template(
            "complete_profile.html",
            name=google_name,
            email=email
        )


    # ------------------------------------------
    # POST
    # ------------------------------------------

    name = request.form.get(
        "name",
        ""
    ).strip()

    contact = request.form.get(
        "contact",
        ""
    ).strip()


    # ------------------------------------------
    # VALIDATION
    # ------------------------------------------

    if not name:

        return render_template(
            "complete_profile.html",
            name=name,
            email=email,
            error="Name is required."
        )


    if not contact:

        return render_template(
            "complete_profile.html",
            name=name,
            email=email,
            error="Contact number is required."
        )


    # Remove spaces and common symbols
    clean_contact = (
        contact
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )


    if not clean_contact.isdigit():

        return render_template(
            "complete_profile.html",
            name=name,
            email=email,
            error="Please enter a valid contact number."
        )


    if len(clean_contact) < 10:

        return render_template(
            "complete_profile.html",
            name=name,
            email=email,
            error="Contact number must contain at least 10 digits."
        )


    # ------------------------------------------
    # CHECK AGAIN BEFORE CREATE
    # ------------------------------------------

    existing_user = User.query.filter_by(
        google_id=google_id
    ).first()


    if existing_user:

        existing_user.name = name
        existing_user.contact = clean_contact

        db.session.commit()

        user = existing_user

    else:

        user = User(
            google_id=google_id,
            name=name,
            email=email,
            contact=clean_contact,
            role="user"
        )

        db.session.add(user)

        db.session.commit()


    # ------------------------------------------
    # CLEAR TEMPORARY SESSION DATA
    # ------------------------------------------

    session.pop(
        "profile_google_id",
        None
    )

    session.pop(
        "profile_email",
        None
    )

    session.pop(
        "profile_name",
        None
    )


    # ------------------------------------------
    # LOGIN USER
    # ------------------------------------------

    login_user(user)


    return redirect(
        url_for("user_dashboard")
    )


# ==================================================
# USER DASHBOARD
# ==================================================

@app.route("/user")
@login_required
def user_dashboard():

    return render_template(
        "user_dashboard.html",
        user=current_user
    )


# ==================================================
# LOGOUT
# ==================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(
        url_for("home")
    )


# ==================================================
# DATABASE INITIALIZATION
# ==================================================

with app.app_context():

    db.create_all()


# ==================================================
# START APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run()

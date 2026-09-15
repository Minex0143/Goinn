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
# PROPERTY MODEL
# ==================================================

class Property(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # Owner who created this property
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    # Property information
    property_name = db.Column(
        db.String(200),
        nullable=False
    )

    property_address = db.Column(
        db.Text,
        nullable=False
    )

    location = db.Column(
        db.String(120),
        nullable=False
    )

    # Images will initially be stored as
    # comma-separated URLs
    images = db.Column(
        db.Text,
        nullable=True
    )

    # Guest pricing
    price_1_guest = db.Column(
        db.Float,
        nullable=False
    )

    price_2_guest = db.Column(
        db.Float,
        nullable=True
    )

    price_3_guest = db.Column(
        db.Float,
        nullable=True
    )

    price_4_guest = db.Column(
        db.Float,
        nullable=True
    )

    price_5_guest = db.Column(
        db.Float,
        nullable=True
    )

    max_guests = db.Column(
        db.Integer,
        nullable=False
    )

    # Property status
    status = db.Column(
        db.String(30),
        default="pending",
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
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
# BECOME PROPERTY OWNER
# ==================================================

@app.route("/become-owner")
@login_required
def become_owner():

    current_user.role = "owner"

    db.session.commit()

    return redirect(
        url_for("owner_dashboard")
    )

# ==================================================
# OWNER DASHBOARD
# ==================================================

@app.route("/owner")
@login_required
def owner_dashboard():

    if current_user.role != "owner":

        return "Access denied", 403

    properties = Property.query.filter_by(
        owner_id=current_user.id
    ).all()

    return render_template(
        "owner_dashboard.html",
        user=current_user,
        properties=properties
    )

# ==================================================
# ADD PROPERTY
# ==================================================

@app.route(
    "/owner/add-property",
    methods=["GET", "POST"]
)
@login_required
def add_property():

    if current_user.role != "owner":

        return "Access denied", 403


    if request.method == "POST":

        property_name = request.form.get(
            "property_name",
            ""
        ).strip()

        property_address = request.form.get(
            "property_address",
            ""
        ).strip()

        location = request.form.get(
            "location",
            ""
        ).strip()

        images = request.form.get(
            "images",
            ""
        ).strip()

        price_1_guest = request.form.get(
            "price_1_guest"
        )

        price_2_guest = request.form.get(
            "price_2_guest"
        )

        price_3_guest = request.form.get(
            "price_3_guest"
        )

        price_4_guest = request.form.get(
            "price_4_guest"
        )

        price_5_guest = request.form.get(
            "price_5_guest"
        )

        max_guests = request.form.get(
            "max_guests"
        )


        # ------------------------------------------
        # VALIDATION
        # ------------------------------------------

        if not property_name:

            return "Property name is required", 400

        if not property_address:

            return "Property address is required", 400

        if not location:

            return "Location is required", 400

        if not price_1_guest:

            return "Price for 1 guest is required", 400

        if not max_guests:

            return "Maximum guests is required", 400


        # ------------------------------------------
        # CREATE PROPERTY
        # ------------------------------------------

        property_obj = Property(

            owner_id=current_user.id,

            property_name=property_name,

            property_address=property_address,

            location=location,

            images=images,

            price_1_guest=float(
                price_1_guest
            ),

            price_2_guest=float(
                price_2_guest
            ) if price_2_guest else None,

            price_3_guest=float(
                price_3_guest
            ) if price_3_guest else None,

            price_4_guest=float(
                price_4_guest
            ) if price_4_guest else None,

            price_5_guest=float(
                price_5_guest
            ) if price_5_guest else None,

            max_guests=int(
                max_guests
            ),

            status="pending"
        )


        db.session.add(
            property_obj
        )

        db.session.commit()


        return redirect(
            url_for("owner_dashboard")
        )


    return render_template(
        "add_property.html"
    )

# ==================================================
# ADMIN DASHBOARD
# ==================================================

@app.route("/admin")
@login_required
def admin_dashboard():

    # Only admin users can access this page
    if current_user.role != "admin":
        return "Access denied", 403

    properties = Property.query.order_by(
        Property.created_at.desc()
    ).all()

    return render_template(
        "admin_dashboard.html",
        properties=properties
    )


# ==================================================
# APPROVE PROPERTY
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/approve",
    methods=["POST"]
)
@login_required
def approve_property(property_id):

    if current_user.role != "admin":
        return "Access denied", 403

    property_obj = db.session.get(
        Property,
        property_id
    )

    if not property_obj:
        return "Property not found", 404

    property_obj.status = "approved"

    db.session.commit()

    return redirect(
        url_for("admin_dashboard")
    )


# ==================================================
# REJECT PROPERTY
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/reject",
    methods=["POST"]
)
@login_required
def reject_property(property_id):

    if current_user.role != "admin":
        return "Access denied", 403

    property_obj = db.session.get(
        Property,
        property_id
    )

    if not property_obj:
        return "Property not found", 404

    property_obj.status = "rejected"

    db.session.commit()

    return redirect(
        url_for("admin_dashboard")
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

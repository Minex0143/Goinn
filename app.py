from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
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
import json


# ============================================================
# FLASK CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "goinn-development-secret-key"
)

# ------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///goinn.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# LOGIN MANAGER
# ============================================================

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"


# ============================================================
# GOOGLE CONFIGURATION
# ============================================================

GOOGLE_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID"
)

ADMIN_EMAIL = os.environ.get(
    "ADMIN_EMAIL",
    ""
).lower().strip()


# ============================================================
# USER MODEL
# ============================================================

class User(
    UserMixin,
    db.Model
):

    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    google_id = db.Column(
        db.String(255),
        unique=True,
        nullable=True
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    contact = db.Column(
        db.String(50),
        nullable=True
    )

    is_owner = db.Column(
        db.Boolean,
        default=False
    )

    properties = db.relationship(
        "Property",
        backref="owner",
        lazy=True
    )


# ============================================================
# PROPERTY MODEL
# ============================================================

class Property(db.Model):

    __tablename__ = "properties"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    property_name = db.Column(
        db.String(255),
        nullable=False
    )

    property_address = db.Column(
        db.Text,
        nullable=False
    )

    location = db.Column(
        db.String(255),
        nullable=False
    )

    max_guests = db.Column(
        db.Integer,
        nullable=True
    )

    pricing_method = db.Column(
        db.String(50),
        nullable=True
    )

    pricing_data = db.Column(
        db.Text,
        nullable=True
    )

    status = db.Column(
        db.String(30),
        default="pending",
        nullable=False
    )


# ============================================================
# BOOKING MODEL
# ============================================================

class Booking(db.Model):

    __tablename__ = "bookings"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    property_id = db.Column(
        db.Integer,
        db.ForeignKey("properties.id"),
        nullable=False
    )

    customer_name = db.Column(
        db.String(200),
        nullable=False
    )

    customer_contact = db.Column(
        db.String(50),
        nullable=False
    )

    guests = db.Column(
        db.Integer,
        nullable=False
    )

    check_in = db.Column(
        db.Date,
        nullable=False
    )

    check_out = db.Column(
        db.Date,
        nullable=False
    )

    total_price = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    property = db.relationship(
        "Property",
        backref="bookings"
    )


# ============================================================
# LOGIN LOADER
# ============================================================

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    properties = Property.query.filter_by(
        status="approved"
    ).all()

    return render_template(
        "index.html",
        properties=properties
    )


# ============================================================
# LOGIN PAGE
# ============================================================

@app.route("/login")
def login():

    if current_user.is_authenticated:

        return redirect(
            url_for("user_dashboard")
        )

    return render_template(
        "login.html",
        google_client_id=GOOGLE_CLIENT_ID
    )


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route(
    "/google-login",
    methods=["POST"]
)
def google_login():

    try:

        credential = request.form.get(
            "credential"
        )

        if not credential:

            return "Google credential missing", 400

        idinfo = id_token.verify_oauth2_token(
            credential,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )

        google_id = idinfo.get(
            "sub"
        )

        email = idinfo.get(
            "email"
        )

        name = idinfo.get(
            "name"
        )

        if not google_id or not email:

            return "Invalid Google account", 400

        email = email.lower().strip()

        user = User.query.filter_by(
            email=email
        ).first()

        if not user:

            user = User(
                google_id=google_id,
                name=name or email.split("@")[0],
                email=email
            )

            db.session.add(user)

            db.session.commit()

        else:

            user.google_id = google_id

            if name:

                user.name = name

            db.session.commit()

        login_user(user)

        return redirect(
            url_for("user_dashboard")
        )

    except Exception as e:

        print(
            "GOOGLE LOGIN ERROR:",
            e
        )

        return (
            "Google login failed: "
            + str(e),
            500
        )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(
        url_for("login")
    )


# ============================================================
# USER DASHBOARD
# ============================================================

@app.route("/user")
@login_required
def user_dashboard():

    return render_template(
        "user_dashboard.html",
        user=current_user
    )


# ============================================================
# COMPLETE PROFILE
# ============================================================

@app.route(
    "/complete-profile",
    methods=["GET", "POST"]
)
@login_required
def complete_profile():

    if request.method == "POST":

        contact = request.form.get(
            "contact",
            ""
        ).strip()

        if not contact:

            flash(
                "Please enter your contact number."
            )

            return redirect(
                url_for("complete_profile")
            )

        current_user.contact = contact

        db.session.commit()

        return redirect(
            url_for("user_dashboard")
        )

    return render_template(
        "complete_profile.html",
        user=current_user
    )


# ============================================================
# BECOME OWNER
# ============================================================

@app.route(
    "/become-owner",
    methods=["GET", "POST"]
)
@login_required
def become_owner():

    if request.method == "POST":

        current_user.is_owner = True

        db.session.commit()

        return redirect(
            url_for("owner_dashboard")
        )

    return render_template(
        "become_owner.html",
        user=current_user
    )


# ============================================================
# OWNER DASHBOARD
# ============================================================

@app.route("/owner")
@login_required
def owner_dashboard():

    if not current_user.is_owner:

        return redirect(
            url_for("become_owner")
        )

    properties = Property.query.filter_by(
        owner_id=current_user.id
    ).order_by(
        Property.id.desc()
    ).all()

    return render_template(
        "owner_dashboard.html",
        user=current_user,
        properties=properties
    )


# ============================================================
# ADD PROPERTY
# ============================================================

@app.route(
    "/owner/add-property",
    methods=["GET", "POST"]
)
@login_required
def add_property():

    if not current_user.is_owner:

        return redirect(
            url_for("become_owner")
        )

    if request.method == "POST":

        try:

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

            if not property_name:

                flash(
                    "Property name is required."
                )

                return redirect(
                    url_for("add_property")
                )

            if not property_address:

                flash(
                    "Property address is required."
                )

                return redirect(
                    url_for("add_property")
                )

            if not location:

                flash(
                    "Location is required."
                )

                return redirect(
                    url_for("add_property")
                )

            new_property = Property(

                owner_id=current_user.id,

                property_name=property_name,

                property_address=property_address,

                location=location,

                max_guests=None,

                pricing_method=None,

                pricing_data=None,

                status="pending"

            )

            db.session.add(
                new_property
            )

            db.session.commit()

            flash(
                "Property created successfully. Waiting for admin approval."
            )

            return redirect(
                url_for("owner_dashboard")
            )

        except Exception as e:

            db.session.rollback()

            print(
                "ADD PROPERTY ERROR:",
                e
            )

            return (
                "Unable to create property: "
                + str(e),
                500
            )

    return render_template(
        "add_property.html"
    )


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin():

    if not current_user.is_authenticated:

        return False

    return (
        current_user.email.lower().strip()
        == ADMIN_EMAIL
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@login_required
def admin_dashboard():

    if not is_admin():

        return "Unauthorized", 403

    properties = Property.query.order_by(
        Property.id.desc()
    ).all()

    bookings = Booking.query.order_by(
        Booking.id.desc()
    ).all()

    # Parse pricing JSON here.
    # This avoids using a custom Jinja fromjson filter.

    for property in properties:

        property.parsed_pricing = []

        if property.pricing_data:

            try:

                property.parsed_pricing = json.loads(
                    property.pricing_data
                )

            except Exception as e:

                print(
                    "PRICING JSON ERROR:",
                    e
                )

                property.parsed_pricing = []

    return render_template(
        "admin_dashboard.html",
        properties=properties,
        bookings=bookings
    )


# ============================================================
# SET PRICE + APPROVE
# ============================================================

@app.route(
    "/admin/property/<int:property_id>/set-price",
    methods=["POST"]
)
@login_required
def set_property_price(property_id):

    if not is_admin():

        return "Unauthorized", 403

    property = db.session.get(
        Property,
        property_id
    )

    if not property:

        return "Property not found", 404

    try:

        max_guests = request.form.get(
            "max_guests",
            type=int
        )

        pricing_method = request.form.get(
            "pricing_method"
        )

        if not max_guests or max_guests < 1:

            return (
                "Invalid maximum guests.",
                400
            )

        if max_guests > 100:

            return (
                "Maximum guests cannot exceed 100.",
                400
            )

        if pricing_method not in (
            "individual",
            "group"
        ):

            return (
                "Invalid pricing method.",
                400
            )

        pricing_data = []

        # ----------------------------------------------------
        # INDIVIDUAL PRICING
        # ----------------------------------------------------

        if pricing_method == "individual":

            for guest in range(
                1,
                max_guests + 1
            ):

                price = request.form.get(
                    f"price_{guest}",
                    type=float
                )

                if price is None:

                    return (
                        f"Price missing for {guest} guest(s).",
                        400
                    )

                if price < 0:

                    return (
                        "Price cannot be negative.",
                        400
                    )

                pricing_data.append({

                    "guests": guest,

                    "price": price

                })

        # ----------------------------------------------------
        # GROUP PRICING
        # ----------------------------------------------------

        else:

            group_number = 1

            expected_start = 1

            while True:

                min_guests = request.form.get(
                    f"group_{group_number}_min",
                    type=int
                )

                max_group_guests = request.form.get(
                    f"group_{group_number}_max",
                    type=int
                )

                price = request.form.get(
                    f"group_{group_number}_price",
                    type=float
                )

                # No more groups
                if (
                    min_guests is None
                    and
                    max_group_guests is None
                    and
                    price is None
                ):

                    break

                if (
                    min_guests is None
                    or
                    max_group_guests is None
                    or
                    price is None
                ):

                    return (
                        "Incomplete guest group.",
                        400
                    )

                if min_guests != expected_start:

                    return (
                        "Guest groups must have no gaps.",
                        400
                    )

                if max_group_guests < min_guests:

                    return (
                        "Group maximum cannot be less than minimum.",
                        400
                    )

                if min_guests < 1:

                    return (
                        "Guest range cannot start below 1.",
                        400
                    )

                if max_group_guests > max_guests:

                    return (
                        "Guest range exceeds maximum guests.",
                        400
                    )

                if price < 0:

                    return (
                        "Price cannot be negative.",
                        400
                    )

                pricing_data.append({

                    "min_guests": min_guests,

                    "max_guests": max_group_guests,

                    "price": price

                })

                expected_start = (
                    max_group_guests + 1
                )

                group_number += 1

            if not pricing_data:

                return (
                    "At least one guest group is required.",
                    400
                )

            if expected_start != max_guests + 1:

                return (
                    "Guest groups must cover every guest count.",
                    400
                )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        property.max_guests = max_guests

        property.pricing_method = (
            pricing_method
        )

        property.pricing_data = json.dumps(
            pricing_data
        )

        # Approve after pricing is saved

        property.status = "approved"

        db.session.commit()

        flash(
            "Pricing saved and property approved."
        )

        return redirect(
            url_for("admin_dashboard")
        )

    except Exception as e:

        db.session.rollback()

        print(
            "SET PRICE ERROR:",
            e
        )

        return (
            "Unable to save pricing: "
            + str(e),
            500
        )


# ============================================================
# REJECT PROPERTY
# ============================================================

@app.route(
    "/admin/property/<int:property_id>/reject",
    methods=["POST"]
)
@login_required
def reject_property(property_id):

    if not is_admin():

        return "Unauthorized", 403

    property = db.session.get(
        Property,
        property_id
    )

    if not property:

        return "Property not found", 404

    property.status = "rejected"

    db.session.commit()

    flash(
        "Property rejected."
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

with app.app_context():

    db.create_all()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )

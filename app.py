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

from datetime import datetime
import os
import urllib.parse
import json


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

    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    # ----------------------------------------------
    # PROPERTY INFORMATION
    # ----------------------------------------------

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

    images = db.Column(
        db.Text,
        nullable=True
    )

    # ----------------------------------------------
    # GUEST INFORMATION
    # ----------------------------------------------

    max_guests = db.Column(
        db.Integer,
        nullable=False
    )

    # ----------------------------------------------
    # NEW ADMIN PRICING SYSTEM
    # ----------------------------------------------

    pricing_method = db.Column(
        db.String(30),
        nullable=True
    )

    pricing_data = db.Column(
        db.Text,
        nullable=True
    )

    # ----------------------------------------------
    # OLD PRICING COLUMNS
    #
    # Kept for compatibility with the existing
    # database. They are no longer entered by owner.
    # ----------------------------------------------

    price_1_guest = db.Column(
        db.Float,
        nullable=True
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

    # ----------------------------------------------
    # STATUS
    # ----------------------------------------------

    status = db.Column(
        db.String(30),
        default="pending",
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # ----------------------------------------------
    # OWNER RELATIONSHIP
    # ----------------------------------------------

    owner = db.relationship(
        "User",
        foreign_keys=[owner_id]
    )


# ==================================================
# BOOKING MODEL
# ==================================================

class Booking(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    property_id = db.Column(
        db.Integer,
        db.ForeignKey("property.id"),
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

    guests = db.Column(
        db.Integer,
        nullable=False
    )

    nights = db.Column(
        db.Integer,
        nullable=False
    )

    price_per_day = db.Column(
        db.Float,
        nullable=False
    )

    total_price = db.Column(
        db.Float,
        nullable=False
    )

    customer_name = db.Column(
        db.String(120),
        nullable=False
    )

    customer_contact = db.Column(
        db.String(30),
        nullable=False
    )

    customer_email = db.Column(
        db.String(160),
        nullable=False
    )

    status = db.Column(
        db.String(30),
        default="inquiry",
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    user = db.relationship(
        "User",
        foreign_keys=[user_id]
    )

    property = db.relationship(
        "Property",
        foreign_keys=[property_id]
    )


# ==================================================
# DATABASE MIGRATION
# ==================================================
#
# Render uses PostgreSQL.
#
# db.create_all() does NOT add new columns to an
# existing table, so we add the new pricing columns
# if they don't already exist.
#
# ==================================================

def update_database_schema():

    try:

        database_url = app.config[
            "SQLALCHEMY_DATABASE_URI"
        ]

        # ------------------------------------------
        # PostgreSQL
        # ------------------------------------------

        if database_url.startswith(
            "postgresql"
        ):

            from sqlalchemy import inspect, text

            inspector = inspect(db.engine)

            columns = [
                column["name"]
                for column in inspector.get_columns(
                    "property"
                )
            ]

            with db.engine.begin() as connection:

                if "pricing_method" not in columns:

                    connection.execute(
                        text(
                            """
                            ALTER TABLE property
                            ADD COLUMN pricing_method
                            VARCHAR(30)
                            """
                        )
                    )

                if "pricing_data" not in columns:

                    connection.execute(
                        text(
                            """
                            ALTER TABLE property
                            ADD COLUMN pricing_data
                            TEXT
                            """
                        )
                    )

                # Old price columns were NOT NULL.
                # Make them nullable because pricing is
                # now entered by Admin.

                for column_name in [
                    "price_1_guest",
                    "price_2_guest",
                    "price_3_guest",
                    "price_4_guest",
                    "price_5_guest"
                ]:

                    if column_name in columns:

                        connection.execute(
                            text(
                                f"""
                                ALTER TABLE property
                                ALTER COLUMN
                                {column_name}
                                DROP NOT NULL
                                """
                            )
                        )

    except Exception as error:

        print(
            "Database schema update warning:",
            error
        )


# ==================================================
# LOAD USER
# ==================================================

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# ==================================================
# PRICE CALCULATION
# ==================================================

def get_property_price(
    property_obj,
    guests
):

    # ----------------------------------------------
    # Check new pricing system
    # ----------------------------------------------

    if property_obj.pricing_method:

        try:

            pricing = json.loads(
                property_obj.pricing_data
                or "[]"
            )

        except Exception:

            return None


        # ------------------------------------------
        # INDIVIDUAL PRICING
        # ------------------------------------------

        if property_obj.pricing_method == "individual":

            for item in pricing:

                if int(item["guests"]) == guests:

                    return float(
                        item["price"]
                    )


        # ------------------------------------------
        # GROUP PRICING
        # ------------------------------------------

        elif property_obj.pricing_method == "group":

            for item in pricing:

                minimum = int(
                    item["min_guests"]
                )

                maximum = int(
                    item["max_guests"]
                )

                if (
                    minimum
                    <= guests
                    <= maximum
                ):

                    return float(
                        item["price"]
                    )


    # ----------------------------------------------
    # OLD DATA FALLBACK
    #
    # This allows existing properties to continue
    # working until they are updated with the new
    # Admin pricing system.
    # ----------------------------------------------

    if guests == 1:

        return property_obj.price_1_guest

    elif guests == 2:

        return property_obj.price_2_guest

    elif guests == 3:

        return property_obj.price_3_guest

    elif guests == 4:

        return property_obj.price_4_guest

    elif guests == 5:

        return property_obj.price_5_guest

    return None


# ==================================================
# HOME PAGE
# ==================================================

@app.route("/")
def home():

    search_location = request.args.get(
        "location",
        ""
    ).strip()

    properties = []

    if search_location:

        properties = Property.query.filter(
            Property.status == "approved",
            Property.location.ilike(
                f"%{search_location}%"
            )
        ).order_by(
            Property.created_at.desc()
        ).all()

    return render_template(
        "home.html",
        properties=properties,
        search_location=search_location
    )


# ==================================================
# PROPERTY DETAILS
# ==================================================

@app.route(
    "/property/<int:property_id>"
)
def property_details(property_id):

    property_obj = db.session.get(
        Property,
        property_id
    )

    if not property_obj:

        return (
            "Property not found",
            404
        )

    if property_obj.status != "approved":

        return (
            "Property not available",
            404
        )

    return render_template(
        "property_details.html",
        property=property_obj
    )


# ==================================================
# BOOK PROPERTY
# ==================================================

@app.route(
    "/book/<int:property_id>",
    methods=["GET", "POST"]
)
@login_required
def book_property(property_id):

    property_obj = db.session.get(
        Property,
        property_id
    )

    if not property_obj:

        return (
            "Property not found",
            404
        )

    if property_obj.status != "approved":

        return (
            "Property not available",
            404
        )


    # ----------------------------------------------
    # SHOW BOOKING FORM
    # ----------------------------------------------

    if request.method == "GET":

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user
        )


    # ----------------------------------------------
    # FORM DATA
    # ----------------------------------------------

    check_in_text = request.form.get(
        "check_in",
        ""
    ).strip()

    check_out_text = request.form.get(
        "check_out",
        ""
    ).strip()

    guests_text = request.form.get(
        "guests",
        ""
    ).strip()


    customer_name = request.form.get(
        "customer_name",
        ""
    ).strip()

    customer_contact = request.form.get(
        "customer_contact",
        ""
    ).strip()

    customer_email = request.form.get(
        "customer_email",
        ""
    ).strip()


    # ----------------------------------------------
    # VALIDATION
    # ----------------------------------------------

    if not check_in_text:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Please select check-in date."
        )


    if not check_out_text:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Please select check-out date."
        )


    if not guests_text:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Please select number of guests."
        )


    if not customer_name:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Name is required."
        )


    if not customer_contact:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Contact number is required."
        )


    if not customer_email:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Email is required."
        )


    # ----------------------------------------------
    # DATE PARSING
    # ----------------------------------------------

    try:

        check_in = datetime.strptime(
            check_in_text,
            "%Y-%m-%d"
        ).date()

        check_out = datetime.strptime(
            check_out_text,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Invalid date selected."
        )


    if check_out <= check_in:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error=(
                "Check-out date must be after "
                "check-in date."
            )
        )


    # ----------------------------------------------
    # GUEST PARSING
    # ----------------------------------------------

    try:

        guests = int(
            guests_text
        )

    except ValueError:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="Invalid number of guests."
        )


    if guests < 1:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error="At least one guest is required."
        )


    if guests > property_obj.max_guests:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error=(
                f"This property allows a maximum "
                f"of {property_obj.max_guests} guests."
            )
        )


    # ----------------------------------------------
    # GET ADMIN-CONFIGURED PRICE
    # ----------------------------------------------

    price_per_day = get_property_price(
        property_obj,
        guests
    )


    if price_per_day is None:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            error=(
                "Price for the selected number "
                "of guests has not been configured "
                "by Admin yet."
            )
        )


    # ----------------------------------------------
    # CALCULATE NIGHTS
    # ----------------------------------------------

    nights = (
        check_out - check_in
    ).days


    total_price = (
        price_per_day * nights
    )


    # ----------------------------------------------
    # CREATE BOOKING
    # ----------------------------------------------

    booking = Booking(

        user_id=current_user.id,

        property_id=property_obj.id,

        check_in=check_in,

        check_out=check_out,

        guests=guests,

        nights=nights,

        price_per_day=price_per_day,

        total_price=total_price,

        customer_name=customer_name,

        customer_contact=customer_contact,

        customer_email=customer_email,

        status="inquiry"
    )


    db.session.add(
        booking
    )

    db.session.commit()


    # ----------------------------------------------
    # OWNER CONTACT
    # ----------------------------------------------

    owner = property_obj.owner

    owner_contact = None

    if owner:

        owner_contact = owner.contact


    # ----------------------------------------------
    # WHATSAPP MESSAGE
    # ----------------------------------------------

    message = f"""
Hello Goinn Property Owner,

I am interested in booking your property.

Property:
{property_obj.property_name}

Location:
{property_obj.location}

Customer Name:
{customer_name}

Contact:
{customer_contact}

Email:
{customer_email}

Check-in:
{check_in.strftime("%d-%m-%Y")}

Check-out:
{check_out.strftime("%d-%m-%Y")}

Number of Guests:
{guests}

Number of Nights:
{nights}

Initial Price Per Day:
₹{price_per_day:.2f}

Initial Total:
₹{total_price:.2f}

Booking ID:
{booking.id}

I would like to discuss/negotiate the final price and booking details.

Thank you.
"""


    encoded_message = urllib.parse.quote(
        message
    )


    # ----------------------------------------------
    # WHATSAPP REDIRECT
    # ----------------------------------------------

    if owner_contact:

        whatsapp_number = (
            owner_contact
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

        whatsapp_url = (
            "https://wa.me/"
            + whatsapp_number
            + "?text="
            + encoded_message
        )

    else:

        whatsapp_url = (
            "https://wa.me/?text="
            + encoded_message
        )


    return redirect(
        whatsapp_url
    )


# ==================================================
# LOGIN PAGE
# ==================================================

@app.route("/login")
def login():

    if current_user.is_authenticated:

        return redirect(
            url_for("home")
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

        return (
            "Google credential missing",
            400
        )

    try:

        google_user = id_token.verify_oauth2_token(
            credential,
            requests.Request(),
            app.config["GOOGLE_CLIENT_ID"]
        )

        google_id = google_user.get(
            "sub"
        )

        email = google_user.get(
            "email"
        )

        name = google_user.get(
            "name"
        )

        if not google_id:

            return (
                "Google ID missing",
                400
            )

        if not email:

            return (
                "Google account email "
                "not available",
                400
            )


        # ------------------------------------------
        # ADMIN EMAIL
        # ------------------------------------------

        admin_email = os.environ.get(
            "ADMIN_EMAIL",
            ""
        ).strip().lower()

        is_admin = (
            bool(admin_email)
            and
            email.strip().lower()
            == admin_email
        )


        # ------------------------------------------
        # FIND USER
        # ------------------------------------------

        user = User.query.filter_by(
            google_id=google_id
        ).first()


        # ------------------------------------------
        # EXISTING USER
        # ------------------------------------------

        if user:

            if is_admin:

                user.role = "admin"

                db.session.commit()


            login_user(user)


            return redirect(
                url_for("home")
            )


        # ------------------------------------------
        # CHECK EMAIL
        # ------------------------------------------

        existing_email_user = User.query.filter_by(
            email=email
        ).first()

        if existing_email_user:

            return (
                "An account already exists with "
                "this email but is linked to "
                "another Google account.",
                409
            )


        # ------------------------------------------
        # NEW USER
        # ------------------------------------------

        session["profile_google_id"] = google_id

        session["profile_email"] = email

        session["profile_name"] = (
            name
            or
            "Goinn User"
        )

        session["profile_is_admin"] = is_admin


        return redirect(
            url_for("complete_profile")
        )


    except ValueError:

        return (
            "Invalid Google login token",
            400
        )


    except Exception as error:

        print(
            "Google login error:",
            error
        )

        return (
            "Unable to complete "
            "Google login",
            500
        )


# ==================================================
# COMPLETE PROFILE
# ==================================================

@app.route(
    "/complete-profile",
    methods=["GET", "POST"]
)
def complete_profile():

    google_id = session.get(
        "profile_google_id"
    )

    email = session.get(
        "profile_email"
    )

    google_name = session.get(
        "profile_name"
    )

    is_admin = session.get(
        "profile_is_admin",
        False
    )


    if not google_id or not email:

        return redirect(
            url_for("login")
        )


    if request.method == "GET":

        return render_template(
            "complete_profile.html",
            name=google_name,
            email=email
        )


    name = request.form.get(
        "name",
        ""
    ).strip()

    contact = request.form.get(
        "contact",
        ""
    ).strip()


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
            error=(
                "Please enter a valid "
                "contact number."
            )
        )


    if len(clean_contact) < 10:

        return render_template(
            "complete_profile.html",
            name=name,
            email=email,
            error=(
                "Contact number must contain "
                "at least 10 digits."
            )
        )


    existing_user = User.query.filter_by(
        google_id=google_id
    ).first()


    if existing_user:

        existing_user.name = name

        existing_user.contact = clean_contact


        if is_admin:

            existing_user.role = "admin"


        db.session.commit()

        user = existing_user


    else:

        user = User(

            google_id=google_id,

            name=name,

            email=email,

            contact=clean_contact,

            role=(
                "admin"
                if is_admin
                else "user"
            )
        )

        db.session.add(user)

        db.session.commit()


    # ------------------------------------------
    # CLEAR PROFILE SESSION
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

    session.pop(
        "profile_is_admin",
        None
    )


    login_user(user)


    return redirect(
        url_for("home")
    )


# ==================================================
# USER DASHBOARD
# ==================================================

@app.route("/user")
@login_required
def user_dashboard():

    bookings = Booking.query.filter_by(
        user_id=current_user.id
    ).order_by(
        Booking.created_at.desc()
    ).all()


    return render_template(
        "user_dashboard.html",
        user=current_user,
        bookings=bookings
    )


# ==================================================
# BECOME OWNER
# ==================================================

@app.route("/become-owner")
@login_required
def become_owner():

    if current_user.role == "admin":

        return redirect(
            url_for("admin_dashboard")
        )


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

    if current_user.role not in [
        "owner",
        "admin"
    ]:

        return (
            "Access denied",
            403
        )


    properties = Property.query.filter_by(
        owner_id=current_user.id
    ).order_by(
        Property.created_at.desc()
    ).all()


    bookings = []


    if properties:

        property_ids = [
            p.id
            for p in properties
        ]

        bookings = Booking.query.filter(
            Booking.property_id.in_(
                property_ids
            )
        ).order_by(
            Booking.created_at.desc()
        ).all()


    return render_template(
        "owner_dashboard.html",
        user=current_user,
        properties=properties,
        bookings=bookings
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

    if current_user.role not in [
        "owner",
        "admin"
    ]:

        return (
            "Access denied",
            403
        )


    if request.method == "GET":

        return render_template(
            "add_property.html"
        )


    # ----------------------------------------------
    # PROPERTY INFORMATION ONLY
    #
    # NO PRICING HERE
    # ----------------------------------------------

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

    max_guests_text = request.form.get(
        "max_guests",
        ""
    ).strip()


    # ----------------------------------------------
    # VALIDATION
    # ----------------------------------------------

    if not property_name:

        return (
            "Property name is required",
            400
        )


    if not property_address:

        return (
            "Property address is required",
            400
        )


    if not location:

        return (
            "Location is required",
            400
        )


    if not max_guests_text:

        return (
            "Maximum guests is required",
            400
        )


    try:

        maximum_guests = int(
            max_guests_text
        )

    except ValueError:

        return (
            "Maximum guests must be a valid number.",
            400
        )


    if maximum_guests < 1:

        return (
            "Maximum guests must be at least 1.",
            400
        )


    if maximum_guests > 100:

        return (
            "Maximum guests cannot exceed 100.",
            400
        )


    # ----------------------------------------------
    # CREATE PROPERTY
    # ----------------------------------------------

    property_obj = Property(

        owner_id=current_user.id,

        property_name=property_name,

        property_address=property_address,

        location=location,

        images=images,

        max_guests=maximum_guests,

        pricing_method=None,

        pricing_data=None,

        status="pending"
    )


    db.session.add(
        property_obj
    )

    db.session.commit()


    return redirect(
        url_for("owner_dashboard")
    )


# ==================================================
# ADMIN DASHBOARD
# ==================================================

@app.route("/admin")
@login_required
def admin_dashboard():

    if current_user.role != "admin":

        return (
            "Access denied",
            403
        )


    properties = Property.query.order_by(
        Property.created_at.desc()
    ).all()


    bookings = Booking.query.order_by(
        Booking.created_at.desc()
    ).all()


    return render_template(
        "admin_dashboard.html",
        properties=properties,
        bookings=bookings
    )


# ==================================================
# ADMIN PRICE FORM
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/set-price",
    methods=["POST"]
)
@login_required
def set_property_price(property_id):

    # ----------------------------------------------
    # ADMIN ONLY
    # ----------------------------------------------

    if current_user.role != "admin":

        return (
            "Access denied",
            403
        )


    # ----------------------------------------------
    # FIND PROPERTY
    # ----------------------------------------------

    property_obj = db.session.get(
        Property,
        property_id
    )


    if not property_obj:

        return (
            "Property not found",
            404
        )


    # ----------------------------------------------
    # GET FORM DATA
    # ----------------------------------------------

    pricing_method = request.form.get(
        "pricing_method",
        ""
    ).strip().lower()


    max_guests_text = request.form.get(
        "max_guests",
        ""
    ).strip()


    # ----------------------------------------------
    # VALIDATE METHOD
    # ----------------------------------------------

    if pricing_method not in [
        "individual",
        "group"
    ]:

        return (
            "Invalid pricing method.",
            400
        )


    # ----------------------------------------------
    # VALIDATE MAX GUESTS
    # ----------------------------------------------

    try:

        max_guests = int(
            max_guests_text
        )

    except ValueError:

        return (
            "Maximum guests must be a valid number.",
            400
        )


    if max_guests < 1 or max_guests > 100:

        return (
            "Maximum guests must be between 1 and 100.",
            400
        )


    # ==================================================
    # INDIVIDUAL PRICING
    # ==================================================

    if pricing_method == "individual":

        pricing = []


        for guest_number in range(
            1,
            max_guests + 1
        ):

            price_text = request.form.get(
                f"price_{guest_number}",
                ""
            ).strip()


            if not price_text:

                return (
                    f"Price for {guest_number} "
                    f"guest(s) is required.",
                    400
                )


            try:

                price = float(
                    price_text
                )

            except ValueError:

                return (
                    f"Invalid price for "
                    f"{guest_number} guest(s).",
                    400
                )


            if price < 0:

                return (
                    "Price cannot be negative.",
                    400
                )


            pricing.append({

                "guests": guest_number,

                "price": price
            })


    # ==================================================
    # GROUP PRICING
    # ==================================================

    else:

        pricing = []

        group_count_text = request.form.get(
            "group_count",
            ""
        ).strip()


        try:

            group_count = int(
                group_count_text
            )

        except ValueError:

            return (
                "Invalid number of groups.",
                400
            )


        if group_count < 1:

            return (
                "At least one group is required.",
                400
            )


        expected_start = 1


        for group_number in range(
            1,
            group_count + 1
        ):

            min_text = request.form.get(
                f"group_{group_number}_min",
                ""
            ).strip()

            max_text = request.form.get(
                f"group_{group_number}_max",
                ""
            ).strip()

            price_text = request.form.get(
                f"group_{group_number}_price",
                ""
            ).strip()


            if not min_text or not max_text:

                return (
                    "Every guest group must have "
                    "a minimum and maximum.",
                    400
                )


            try:

                minimum = int(
                    min_text
                )

                maximum = int(
                    max_text
                )

                price = float(
                    price_text
                )

            except ValueError:

                return (
                    "Invalid group pricing information.",
                    400
                )


            # ------------------------------------------
            # GROUP VALIDATION
            # ------------------------------------------

            if minimum != expected_start:

                return (
                    "Guest groups must start from "
                    f"{expected_start}.",
                    400
                )


            if maximum < minimum:

                return (
                    "Group maximum cannot be less "
                    "than group minimum.",
                    400
                )


            if maximum > max_guests:

                return (
                    "Guest group exceeds maximum "
                    "guest count.",
                    400
                )


            if price < 0:

                return (
                    "Price cannot be negative.",
                    400
                )


            pricing.append({

                "min_guests": minimum,

                "max_guests": maximum,

                "price": price
            })


            expected_start = maximum + 1


        # ------------------------------------------
        # MAKE SURE ALL GUEST COUNTS ARE COVERED
        # ------------------------------------------

        if expected_start != max_guests + 1:

            return (
                "Guest groups must cover all guests "
                f"from 1 to {max_guests}.",
                400
            )


    # ==================================================
    # SAVE PRICING
    # ==================================================

    property_obj.max_guests = max_guests

    property_obj.pricing_method = (
        pricing_method
    )

    property_obj.pricing_data = json.dumps(
        pricing
    )

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

        return (
            "Access denied",
            403
        )


    property_obj = db.session.get(
        Property,
        property_id
    )


    if not property_obj:

        return (
            "Property not found",
            404
        )


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
# CREATE DATABASE TABLES
# ==================================================

with app.app_context():

    db.create_all()

    update_database_schema()


# ==================================================
# START APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )
    )

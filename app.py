from flask import (
    Flask,
    render_template,
    request,
    redirect,
    flash,
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

from datetime import datetime, date, timedelta
import os
import urllib.parse
import json
import secrets

from sqlalchemy.exc import IntegrityError

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
# JINJA FILTER
# ==================================================

@app.template_filter("fromjson")
def fromjson_filter(value):

    try:

        return json.loads(value) if value else []

    except (ValueError, TypeError, json.JSONDecodeError):

        return []


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
    @property
    def is_admin(self):
        return self.role == "admin"


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

    # ------------------------------------------------
    # LEGACY PRICE FIELDS
    # ------------------------------------------------

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

    # ------------------------------------------------
    # MAX GUESTS
    # ------------------------------------------------
    #
    # ONLY ADMIN CAN SET THIS.
    #
    # 0 means "not configured yet".
    #

    max_guests = db.Column(
        db.Integer,
        nullable=True,
        default=None
    )

    # ------------------------------------------------
    # NEW PRICING
    # ------------------------------------------------

    pricing_method = db.Column(
        db.String(30),
        nullable=True
    )

    pricing_data = db.Column(
        db.Text,
        nullable=True
    )

    # ------------------------------------------------
    # STATUS
    # ------------------------------------------------

    status = db.Column(
        db.String(30),
        default="pending",
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # ------------------------------------------------
    # OWNER
    # ------------------------------------------------

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
        default="pending",
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
# LOAD USER
# ==================================================

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# ==================================================
# DATABASE MIGRATION
# ==================================================

def ensure_database_columns():

    try:

        inspector = db.inspect(
            db.engine
        )

        tables = inspector.get_table_names()

        if "property" not in tables:

            return

        columns = {
            column["name"]
            for column in inspector.get_columns(
                "property"
            )
        }

        # ------------------------------------------
        # PRICING METHOD
        # ------------------------------------------

        if "pricing_method" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN pricing_method VARCHAR(30)
                    """
                )

        # ------------------------------------------
        # PRICING DATA
        # ------------------------------------------

        if "pricing_data" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN pricing_data TEXT
                    """
                )

        # ------------------------------------------
        # MAX GUESTS
        # ------------------------------------------

        if "max_guests" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN max_guests INTEGER
                    """
                )

    except Exception as error:

        print(
            "Database migration warning:",
            error
        )

# ==================================================
# PRICING HELPER
# ==================================================

def get_property_price(
    property_obj,
    guests
):

    if not property_obj:
        return None

    if not guests or guests < 1:
        return None

    # ------------------------------------------------
    # MAX GUEST VALIDATION
    # ------------------------------------------------

    if (
        not property_obj.max_guests
        or property_obj.max_guests < 1
    ):
        return None

    if guests > property_obj.max_guests:
        return None

    # ------------------------------------------------
    # NEW PRICING
    # ------------------------------------------------

    if (
        property_obj.pricing_method
        and property_obj.pricing_data
    ):

        try:

            pricing = json.loads(
                property_obj.pricing_data
            )

        except Exception as error:

            print(
                "Pricing JSON error:",
                error
            )

            pricing = []

        # ============================================
        # INDIVIDUAL PRICING
        # ============================================

        if (
            property_obj.pricing_method
            == "individual"
        ):

            for item in pricing:

                try:

                    item_guests = int(
                        item.get("guests")
                    )

                    item_price = float(
                        item.get("price")
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    continue

                if item_guests == guests:

                    return item_price

        # ============================================
        # GROUP PRICING
        # ============================================

        elif (
            property_obj.pricing_method
            == "group"
        ):

            for item in pricing:

                try:

                    minimum = int(
                        item.get("min_guests")
                    )

                    maximum = int(
                        item.get("max_guests")
                    )

                    item_price = float(
                        item.get("price")
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    continue

                if (
                    minimum <= guests <= maximum
                ):

                    return item_price

    # ------------------------------------------------
    # LEGACY PRICING
    # ------------------------------------------------

    legacy_prices = {

        1: property_obj.price_1_guest,

        2: property_obj.price_2_guest,

        3: property_obj.price_3_guest,

        4: property_obj.price_4_guest,

        5: property_obj.price_5_guest

    }

    return legacy_prices.get(
        guests
    )


# ==================================================
# MAKE PRICE HELPER AVAILABLE TO JINJA
# ==================================================

app.jinja_env.globals[
    "get_property_price"
] = get_property_price

# ==================================================
# HOME
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

    # ==================================================
    # PROPERTY VALIDATION
    # ==================================================

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

    # ==================================================
    # TODAY / TOMORROW
    # ==================================================

    today = date.today()

    tomorrow = (
        today + timedelta(days=1)
    )

    today_string = today.isoformat()

    tomorrow_string = tomorrow.isoformat()

    # ==================================================
    # GET
    # ==================================================

    if request.method == "GET":

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string
        )

    # ==================================================
    # FORM DATA
    # ==================================================

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

    # ==================================================
    # REQUIRED VALIDATION
    # ==================================================

    if not check_in_text:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="Please select check-in date."
        )

    if not check_out_text:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="Please select check-out date."
        )

    if not guests_text:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="Please select number of guests."
        )

    if not customer_name:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="Name is required."
        )

    if not customer_contact:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="Contact number is required."
        )

    if not customer_email:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="Email is required."
        )

    # ==================================================
    # DATES
    # ==================================================

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
            today=today_string,
            tomorrow=tomorrow_string,
            error="Invalid date selected."
        )

    # ==================================================
    # CHECK-IN CANNOT BE IN THE PAST
    # ==================================================

    if check_in < today:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error=(
                "Check-in date cannot be "
                "before today."
            )
        )

    # ==================================================
    # CHECK-OUT MUST BE AFTER CHECK-IN
    # ==================================================

    if check_out <= check_in:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error=(
                "Check-out date must be after "
                "check-in date."
            )
        )

    # ==================================================
    # GUESTS
    # ==================================================

    try:

        guests = int(
            guests_text
        )

    except ValueError:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="Invalid number of guests."
        )

    if guests < 1:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error="At least one guest is required."
        )

    # ==================================================
    # MAX GUESTS
    # ==================================================

    if (
        not property_obj.max_guests
        or property_obj.max_guests < 1
    ):

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error=(
                "Guest capacity has not been "
                "configured for this property."
            )
        )

    if guests > property_obj.max_guests:

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error=(
                f"This property allows a maximum "
                f"of {property_obj.max_guests} guests."
            )
        )

    # ==================================================
    # PRICE
    # ==================================================

    price_per_day = get_property_price(
        property_obj,
        guests
    )

    if (
        price_per_day is None
        or price_per_day < 0
    ):

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error=(
                "Price for the selected number "
                "of guests is not configured."
            )
        )

    # ==================================================
    # NIGHTS
    # ==================================================

    nights = (
        check_out - check_in
    ).days

    total_price = (
        price_per_day * nights
    )

    # ==================================================
    # CREATE BOOKING
    # ==================================================

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

        status="pending"
    )

    db.session.add(
        booking
    )

    db.session.commit()

    # ==================================================
    # OWNER
    # ==================================================

    owner = property_obj.owner

    owner_contact = None

    if owner:

        owner_contact = owner.contact

    # ==================================================
    # WHATSAPP MESSAGE
    # ==================================================

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

Price Per Day:
₹{price_per_day:.2f}

Total:
₹{total_price:.2f}

Booking ID:
{booking.id}

I would like to discuss/negotiate the final price and booking details.

Thank you.
"""

    encoded_message = urllib.parse.quote(
        message
    )

    # ==================================================
    # WHATSAPP URL
    # ==================================================

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


@app.route("/admin/booking/<int:booking_id>/approve", methods=["POST"])
@login_required
def approve_booking(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    booking.status = "approved"

    db.session.commit()

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/booking/<int:booking_id>/reject", methods=["POST"])
@login_required
def reject_booking(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    booking.status = "rejected"

    db.session.commit()

    return redirect(url_for("admin_dashboard"))



# ==================================================
# LOGIN
# ==================================================
@app.route("/login")
def login():

    if current_user.is_authenticated:

        return redirect(
            url_for("home")
        )

    # Save the page the user originally wanted
    next_url = request.args.get("next")

    if next_url:
        session["login_next"] = next_url

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

        # --------------------------------------------------
        # ADMIN
        # --------------------------------------------------

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

        # --------------------------------------------------
        # CHECK GOOGLE USER
        # --------------------------------------------------

        user = User.query.filter_by(
            google_id=google_id
        ).first()

        if user:

            if is_admin:

                user.role = "admin"

                db.session.commit()

            login_user(user)

            # ----------------------------------------------
            # RETURN TO ORIGINAL PAGE
            # ----------------------------------------------

            next_url = session.pop(
                "login_next",
                None
            )

            if next_url:

                return redirect(
                    next_url
                )

            return redirect(
                url_for("home")
            )

        # --------------------------------------------------
        # CHECK EMAIL
        # --------------------------------------------------

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

        # --------------------------------------------------
        # STORE GOOGLE PROFILE
        # --------------------------------------------------

        session["profile_google_id"] = google_id

        session["profile_email"] = email

        session["profile_name"] = (
            name
            or
            "Goinn User"
        )

        session["profile_is_admin"] = is_admin

        # IMPORTANT:
        # Do NOT remove login_next here.

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

    # Return the user to the page they originally
# wanted to access before signing in.
    next_url = session.pop("login_next", None)
    if next_url:
        return redirect(next_url)

    return redirect(
        url_for("home")
    )


# ==================================================
# USER DASHBOARD
# ==================================================

@app.route("/user")
@login_required
def user_dashboard():

    bookings = (
        Booking.query
        .filter_by(user_id=current_user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )

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
#
# OWNER CANNOT SET:
#
# - Maximum guests
# - Pricing
#
# Admin will configure these.
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

    # ==================================================
    # GET REQUEST
    # ==================================================

    if request.method == "GET":

        # Generate a unique token for this form.
        #
        # This prevents duplicate property creation
        # if the browser/iPhone submits the same form
        # more than once.

        submission_token = secrets.token_urlsafe(32)

        session["add_property_token"] = (
            submission_token
        )

        return render_template(
            "add_property.html",
            submission_token=submission_token
        )

    # ==================================================
    # POST REQUEST
    # ==================================================

    submitted_token = request.form.get(
        "submission_token",
        ""
    ).strip()

    session_token = session.pop(
        "add_property_token",
        None
    )

    # ==================================================
    # DUPLICATE SUBMISSION PROTECTION
    # ==================================================

    # If the token does not match, this request is
    # either a duplicate submission or an old
    # browser resubmission.

    if (
        not submitted_token
        or submitted_token != session_token
    ):

        return redirect(
            url_for("owner_dashboard"),
            code=303
        )

    # ==================================================
    # FORM DATA
    # ==================================================

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

    # ==================================================
    # VALIDATION
    # ==================================================

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

    # ==================================================
    # CREATE PROPERTY
    # ==================================================

    property_obj = Property(

        owner_id=current_user.id,

        property_name=property_name,

        property_address=property_address,

        location=location,

        images=images,

        # Owner does NOT configure guests.
        # Admin will configure max guests and pricing.

        max_guests=0,

        pricing_method=None,

        pricing_data=None,

        status="pending"
    )

    db.session.add(
        property_obj
    )

    db.session.commit()

    # ==================================================
    # POST -> REDIRECT -> GET
    # ==================================================

    return redirect(
        url_for("owner_dashboard"),
        code=303
    )


# ==================================================
# ADMIN DASHBOARD
# ==================================================

@app.route("/admin")
@login_required
def admin_dashboard():

    if not current_user.is_admin:
        return "Unauthorized", 403

    properties = Property.query.order_by(
        Property.id.desc()
    ).all()

    bookings = Booking.query.order_by(
        Booking.id.desc()
    ).all()

    # All registered users
    users = User.query.order_by(
        User.id.desc()
    ).all()

    # Property owners are users with role = "owner"
    property_owners = User.query.filter_by(
        role="owner"
    ).order_by(
        User.id.desc()
    ).all()

    # Booking counts
    pending_bookings = Booking.query.filter_by(
        status="pending"
    ).count()

    rejected_bookings = Booking.query.filter_by(
        status="rejected"
    ).count()

    # Property counts
    rejected_properties = Property.query.filter_by(
        status="rejected"
    ).count()

    return render_template(
        "admin_dashboard.html",
        properties=properties,
        bookings=bookings,
        users=users,
        pending_bookings=pending_bookings,
        rejected_bookings=rejected_bookings,
        rejected_properties=rejected_properties,
        property_owners=property_owners
    )

# ==================================================
# ADMIN SET / UPDATE PRICE
# ==================================================
#
# ADMIN CAN CHANGE:
#
# - Maximum guests
# - Individual pricing
# - Group pricing
#
# Example:
#
# Max guests = 6
#
# Individual:
# 1 guest
# 2 guests
# 3 guests
# 4 guests
# 5 guests
# 6 guests
#
# Group:
# 1-2
# 3-4
# 5-6
#
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/set-price",
    methods=["POST"]
)
@login_required
def set_property_price(property_id):

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

    pricing_method = request.form.get(
        "pricing_method",
        ""
    ).strip().lower()

    max_guests_text = request.form.get(
        "max_guests",
        ""
    ).strip()

    # =================================================
    # MAX GUESTS
    # =================================================

    if not max_guests_text:

        return (
            "Maximum guests is required.",
            400
        )

    try:

        max_guests = int(
            max_guests_text
        )

    except ValueError:

        return (
            "Maximum guests must be a valid number.",
            400
        )

    if max_guests < 1:

        return (
            "Maximum guests must be at least 1.",
            400
        )

    if max_guests > 100:

        return (
            "Maximum guests cannot exceed 100.",
            400
        )

    # =================================================
    # PRICING METHOD
    # =================================================

    if pricing_method not in [
        "individual",
        "group"
    ]:

        return (
            "Invalid pricing method.",
            400
        )

    # =================================================
    # INDIVIDUAL PRICING
    # =================================================

    if pricing_method == "individual":

        pricing = []

        for guest in range(
            1,
            max_guests + 1
        ):

            price_text = request.form.get(
                f"price_{guest}",
                ""
            ).strip()

            if not price_text:

                return (
                    f"Price for {guest} guest"
                    f"{'s' if guest != 1 else ''} "
                    "is required.",
                    400
                )

            try:

                price = float(
                    price_text
                )

            except ValueError:

                return (
                    f"Invalid price for {guest} guest"
                    f"{'s' if guest != 1 else ''}.",
                    400
                )

            if price < 0:

                return (
                    "Price cannot be negative.",
                    400
                )

            pricing.append({

                "guests": guest,

                "price": price

            })

    # =================================================
    # GROUP PRICING
    # =================================================

    else:

        pricing = []

        group_number = 1

        expected_start = 1

        while True:

            min_field = (
                f"group_{group_number}_min"
            )

            max_field = (
                f"group_{group_number}_max"
            )

            price_field = (
                f"group_{group_number}_price"
            )

            min_text = request.form.get(
                min_field
            )

            max_text = request.form.get(
                max_field
            )

            price_text = request.form.get(
                price_field
            )

            # -----------------------------------------
            # NO MORE GROUPS
            # -----------------------------------------

            if (
                min_text is None
                and max_text is None
                and price_text is None
            ):

                break

            min_text = (
                min_text or ""
            ).strip()

            max_text = (
                max_text or ""
            ).strip()

            price_text = (
                price_text or ""
            ).strip()

            # -----------------------------------------
            # REQUIRED
            # -----------------------------------------

            if not min_text:

                return (
                    f"Group {group_number}: "
                    "From value is required.",
                    400
                )

            if not max_text:

                return (
                    f"Group {group_number}: "
                    "To value is required.",
                    400
                )

            if not price_text:

                return (
                    f"Group {group_number}: "
                    "Price is required.",
                    400
                )

            # -----------------------------------------
            # PARSE
            # -----------------------------------------

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
                    f"Group {group_number}: "
                    "Invalid numeric value.",
                    400
                )

            # -----------------------------------------
            # VALIDATION
            # -----------------------------------------

            if minimum < 1:

                return (
                    f"Group {group_number}: "
                    "Minimum guests must be at least 1.",
                    400
                )

            if maximum < minimum:

                return (
                    f"Group {group_number}: "
                    "Maximum guests cannot be less "
                    "than minimum guests.",
                    400
                )

            if maximum > max_guests:

                return (
                    f"Group {group_number}: "
                    f"Maximum cannot exceed "
                    f"{max_guests} guests.",
                    400
                )

            if price < 0:

                return (
                    f"Group {group_number}: "
                    "Price cannot be negative.",
                    400
                )

            # -----------------------------------------
            # NO GAPS
            # -----------------------------------------

            if minimum != expected_start:

                return (
                    "Guest groups must cover all "
                    f"guest counts from 1 to "
                    f"{max_guests} without gaps. "
                    f"Expected group {group_number} "
                    f"to start at {expected_start}.",
                    400
                )

            pricing.append({

                "min_guests": minimum,

                "max_guests": maximum,

                "price": price

            })

            expected_start = (
                maximum + 1
            )

            # -----------------------------------------
            # COMPLETE
            # -----------------------------------------

            if expected_start > max_guests:

                break

            group_number += 1

            if group_number > 100:

                return (
                    "Too many guest groups.",
                    400
                )

        # ------------------------------------------------
        # AT LEAST ONE GROUP
        # ------------------------------------------------

        if not pricing:

            return (
                "Please add at least one guest group.",
                400
            )

        # ------------------------------------------------
        # MUST END AT MAX
        # ------------------------------------------------

        if expected_start != max_guests + 1:

            return (
                "Guest groups must cover all guest "
                f"counts from 1 to {max_guests} "
                "without gaps.",
                400
            )

    # =================================================
    # SAVE
    # =================================================

    property_obj.max_guests = max_guests

    property_obj.pricing_method = (
        pricing_method
    )

    property_obj.pricing_data = json.dumps(
        pricing
    )

    # =================================================
    # CLEAR LEGACY PRICES
    # =================================================

    property_obj.price_1_guest = None
    property_obj.price_2_guest = None
    property_obj.price_3_guest = None
    property_obj.price_4_guest = None
    property_obj.price_5_guest = None

    # =================================================
    # SYNCHRONIZE LEGACY INDIVIDUAL PRICES
    # =================================================

    if pricing_method == "individual":

        for item in pricing:

            guest_count = item["guests"]

            price = item["price"]

            if guest_count == 1:

                property_obj.price_1_guest = price

            elif guest_count == 2:

                property_obj.price_2_guest = price

            elif guest_count == 3:

                property_obj.price_3_guest = price

            elif guest_count == 4:

                property_obj.price_4_guest = price

            elif guest_count == 5:

                property_obj.price_5_guest = price

    # =================================================
    # APPROVE
    # =================================================

    property_obj.status = "approved"

    db.session.commit()

    return redirect(
        url_for("admin_dashboard")
    )


# ==================================================
# EDIT PRICE
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/edit-price",
    methods=["POST"]
)
@login_required
def edit_property_price(property_id):

    if current_user.role != "admin":

        return (
            "Access denied",
            403
        )

    return set_property_price(
        property_id
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

    if (
        not property_obj.max_guests
        or property_obj.max_guests < 1
    ):

        return (
            "Maximum guests must be configured "
            "before approval.",
            400
        )

    if (
        not property_obj.pricing_method
        or not property_obj.pricing_data
    ):

        return (
            "Pricing must be configured "
            "before approval.",
            400
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



# Delete route 

# ==================================================
# DELETE NORMAL USER
# ==================================================

@app.route(
    "/admin/delete-user/<int:user_id>",
    methods=["POST"]
)
@login_required
def delete_user(user_id):

    # Only admin can delete users
    if not current_user.is_admin:
        return "Unauthorized", 403

    user = db.session.get(
        User,
        user_id
    )

    if not user:
        flash(
            "User not found.",
            "danger"
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # Never allow an admin account to be deleted
    if user.is_admin:
        flash(
            "Admin users cannot be deleted.",
            "danger"
        )

        return redirect(
            url_for("admin_dashboard")
        )

    try:

        # ------------------------------------------------
        # DELETE BOOKINGS CREATED BY THIS USER
        # ------------------------------------------------

        Booking.query.filter_by(
            user_id=user.id
        ).delete(
            synchronize_session=False
        )


        # ------------------------------------------------
        # IF USER HAS PROPERTIES, DELETE THEIR BOOKINGS
        # AND PROPERTIES TOO
        # ------------------------------------------------

        user_properties = Property.query.filter_by(
            owner_id=user.id
        ).all()

        for property_obj in user_properties:

            Booking.query.filter_by(
                property_id=property_obj.id
            ).delete(
                synchronize_session=False
            )

            db.session.delete(
                property_obj
            )


        # ------------------------------------------------
        # DELETE USER
        # ------------------------------------------------

        user_name = user.name

        db.session.delete(
            user
        )

        db.session.commit()

        flash(
            f"User {user_name} deleted successfully.",
            "success"
        )

    except Exception as error:

        db.session.rollback()

        print(
            "DELETE USER ERROR:",
            error
        )

        flash(
            "Unable to delete user. "
            "Please check the application logs.",
            "danger"
        )

    return redirect(
        url_for("admin_dashboard")
    )


# ==================================================
# DELETE PROPERTY OWNER
# ==================================================

@app.route(
    "/admin/delete-property-owner/<int:owner_id>",
    methods=["POST"]
)
@login_required
def delete_property_owner(owner_id):

    # Only admin can delete property owners
    if not current_user.is_admin:
        return "Unauthorized", 403

    owner = User.query.filter_by(
        id=owner_id,
        role="owner"
    ).first()

    if not owner:

        flash(
            "Property owner not found.",
            "danger"
        )

        return redirect(
            url_for("admin_dashboard")
        )

    try:

        # ------------------------------------------------
        # FIND ALL PROPERTIES BELONGING TO OWNER
        # ------------------------------------------------

        owner_properties = Property.query.filter_by(
            owner_id=owner.id
        ).all()


        # ------------------------------------------------
        # DELETE BOOKINGS FOR OWNER PROPERTIES
        # ------------------------------------------------

        for property_obj in owner_properties:

            Booking.query.filter_by(
                property_id=property_obj.id
            ).delete(
                synchronize_session=False
            )

            db.session.delete(
                property_obj
            )


        # ------------------------------------------------
        # DELETE BOOKINGS CREATED BY OWNER
        # ------------------------------------------------

        Booking.query.filter_by(
            user_id=owner.id
        ).delete(
            synchronize_session=False
        )


        # ------------------------------------------------
        # DELETE OWNER
        # ------------------------------------------------

        owner_name = owner.name

        db.session.delete(
            owner
        )

        db.session.commit()

        flash(
            f"Property owner {owner_name} "
            f"and associated properties deleted successfully.",
            "success"
        )

    except Exception as error:

        db.session.rollback()

        print(
            "DELETE PROPERTY OWNER ERROR:",
            error
        )

        flash(
            "Unable to delete property owner. "
            "Please check the application logs.",
            "danger"
        )

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

    ensure_database_columns()


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

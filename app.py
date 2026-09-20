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
    # AVAILABILITY TYPE
    # ------------------------------------------------

    availability_type = db.Column(
        db.String(20),
        nullable=False,
        default="type1"
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
# PROPERTY IMAGE MODEL
# ==================================================

class PropertyImage(db.Model):

    __tablename__ = "property_images"

    id = db.Column(db.Integer, primary_key=True)

    property_id = db.Column(
        db.Integer,
        db.ForeignKey("property.id"),
        nullable=False
    )

    slot = db.Column(db.Integer, nullable=False)

    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    image_data = db.Column(db.LargeBinary, nullable=False)

    status = db.Column(
        db.String(30),
        nullable=False,
        default="pending"
    )

    rejection_reason = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

    property = db.relationship(
        "Property",
        backref=db.backref(
            "property_images",
            lazy=True,
            cascade="all, delete-orphan",
            order_by="PropertyImage.slot"
        )
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
# PROPERTY BLOCKED DATE MODEL
# ==================================================

class PropertyBlockedDate(db.Model):

    __tablename__ = "property_blocked_dates"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    property_id = db.Column(
        db.Integer,
        db.ForeignKey("property.id"),
        nullable=False
    )

    block_date = db.Column(
        db.Date,
        nullable=False
    )

    blocked_by = db.Column(
        db.String(20),
        nullable=False,
        default="owner"
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    property = db.relationship(
        "Property",
        backref=db.backref(
            "blocked_dates",
            lazy=True,
            cascade="all, delete-orphan"
        )
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

        # ------------------------------------------
        # AVAILABILITY TYPE
        # ------------------------------------------

        if "availability_type" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN availability_type VARCHAR(20)
                    """
                )

                connection.exec_driver_sql(
                    """
                    UPDATE property
                    SET availability_type = 'type1'
                    WHERE availability_type IS NULL
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
# PROPERTY AVAILABILITY HELPER
# ==================================================

def is_property_available(
    property_id,
    check_in,
    check_out
):

    # A pending or approved booking blocks the property
    # for overlapping dates. Rejected bookings do not.
    existing_booking = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status.in_(["pending", "approved"]),
        Booking.check_in < check_out,
        Booking.check_out > check_in
    ).first()

    if existing_booking:
        return False

    existing_block = PropertyBlockedDate.query.filter(
        PropertyBlockedDate.property_id == property_id,
        PropertyBlockedDate.block_date >= check_in,
        PropertyBlockedDate.block_date < check_out
    ).first()

    return existing_block is None


# ==================================================
# HOME
# ==================================================

@app.route("/")
def home():

    search_location = request.args.get(
        "location",
        ""
    ).strip()

    check_in_text = request.args.get(
        "check_in",
        ""
    ).strip()

    check_out_text = request.args.get(
        "check_out",
        ""
    ).strip()

    guests_text = request.args.get(
        "guests",
        ""
    ).strip()

    today = date.today()
    tomorrow = today + timedelta(days=1)

    properties = []
    search_error = None
    search_performed = False
    search_guests = None
    check_in = None
    check_out = None

    # --------------------------------------------------
    # SEARCH IS PERFORMED ONLY WHEN ALL FOUR VALUES
    # ARE PROVIDED.
    # --------------------------------------------------

    if (
        search_location
        or check_in_text
        or check_out_text
        or guests_text
    ):

        if not search_location:
            search_error = "Please enter a location."

        elif not check_in_text:
            search_error = "Please select check-in date."

        elif not check_out_text:
            search_error = "Please select check-out date."

        elif not guests_text:
            search_error = "Please select number of guests."

        else:
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
                search_error = "Invalid date selected."

            if not search_error and check_in < today:
                search_error = (
                    "Check-in date cannot be before today."
                )

            if not search_error and check_out <= check_in:
                search_error = (
                    "Check-out date must be after check-in date."
                )

            if not search_error:
                try:
                    search_guests = int(guests_text)
                except ValueError:
                    search_error = "Invalid number of guests."

            if not search_error and search_guests < 1:
                search_error = "At least one guest is required."

        # --------------------------------------------------
        # FILTER APPROVED PROPERTIES BY LOCATION, CAPACITY,
        # PRICING AND DATE AVAILABILITY.
        # --------------------------------------------------

        if not search_error:
            search_performed = True

            candidate_properties = Property.query.filter(
                Property.status == "approved",
                Property.location.ilike(
                    f"%{search_location}%"
                )
            ).order_by(
                Property.created_at.desc()
            ).all()

            for property_obj in candidate_properties:

                # Property must have an admin-configured capacity.
                if (
                    not property_obj.max_guests
                    or property_obj.max_guests < 1
                ):
                    continue

                if search_guests > property_obj.max_guests:
                    continue

                # A valid price must exist for the selected
                # guest count, including group pricing.
                price = get_property_price(
                    property_obj,
                    search_guests
                )

                if price is None or price < 0:
                    continue

                # Do not show properties already booked for
                # any overlapping part of the selected dates.
                if not is_property_available(
                    property_obj.id,
                    check_in,
                    check_out
                ):
                    continue

                properties.append(property_obj)

    # --------------------------------------------------
    # REMEMBER THE USER'S SEARCH
    # --------------------------------------------------
    #
    # When the user opens a property from these search
    # results and then proceeds to booking, the selected
    # check-in, check-out and guest count will be carried
    # forward automatically.
    #
    # We only save a complete and valid search. This means
    # a direct visit to a property will still show the
    # normal blank booking form.
    # --------------------------------------------------

    if search_performed and not search_error:

        session["booking_search_check_in"] = (
            check_in_text
        )

        session["booking_search_check_out"] = (
            check_out_text
        )

        session["booking_search_guests"] = (
            str(search_guests)
        )

    return render_template(
        "home.html",
        properties=properties,
        search_location=search_location,
        check_in=check_in_text,
        check_out=check_out_text,
        search_guests=search_guests,
        search_error=search_error,
        search_performed=search_performed,
        today=today.isoformat(),
        tomorrow=tomorrow.isoformat()
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

        # --------------------------------------------------
        # RESTORE SEARCH VALUES FROM HOME PAGE
        # --------------------------------------------------
        #
        # If the user reached this property through a home
        # page search, pre-fill the exact dates and guest
        # count they searched for.
        #
        # Query-string values are also supported, so this
        # continues to work if the property-details template
        # is later changed to pass the values explicitly.
        # --------------------------------------------------

        booking_check_in = request.args.get(
            "check_in",
            session.get("booking_search_check_in", "")
        ).strip()

        booking_check_out = request.args.get(
            "check_out",
            session.get("booking_search_check_out", "")
        ).strip()

        booking_guests = request.args.get(
            "guests",
            session.get("booking_search_guests", "")
        ).strip()

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            selected_check_in=booking_check_in,
            selected_check_out=booking_check_out,
            selected_guests=booking_guests
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
    # PROPERTY AVAILABILITY
    # ==================================================

    # Type 3 is a request-for-confirmation flow.
    # Type 1 and Type 2 use the normal availability check.

    if property_obj.availability_type != "type3":

        if not is_property_available(
            property_obj.id,
            check_in,
            check_out
        ):

            return render_template(
                "booking.html",
                property=property_obj,
                user=current_user,
                today=today_string,
                tomorrow=tomorrow_string,
                error=(
                    "Sorry, this property is already booked "
                    "for the selected dates. Please choose "
                    "different dates."
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

    booking_status = (
        "availability_requested"
        if property_obj.availability_type == "type3"
        else "pending"
    )

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

        status=booking_status
    )

    db.session.add(
        booking
    )

    db.session.commit()

    # ==================================================
    # WHATSAPP ROUTING
    # ==================================================

    if property_obj.availability_type == "type3":

        goinn_contact = os.environ.get(
            "GOINN_WHATSAPP_NUMBER",
            ""
        ).strip()

        message = f"""
Hello Goinn,

I want to check availability for a Type 3 property.

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

Estimated Price Per Day:
₹{price_per_day:.2f}

Estimated Total:
₹{total_price:.2f}

Availability Request ID:
{booking.id}

Please contact the property owner and confirm availability.
"""

        encoded_message = urllib.parse.quote(message)

        if goinn_contact:
            whatsapp_number = (
                goinn_contact
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

        return redirect(whatsapp_url)

    # Type 1 / Type 2 continue to contact the property owner.
    owner = property_obj.owner
    owner_contact = owner.contact if owner else None

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

    encoded_message = urllib.parse.quote(message)

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

    return redirect(whatsapp_url)


@app.route("/admin/booking/<int:booking_id>/approve", methods=["POST"])
@login_required
def approve_booking(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    owner_block = PropertyBlockedDate.query.filter(
        PropertyBlockedDate.property_id == booking.property_id,
        PropertyBlockedDate.block_date >= booking.check_in,
        PropertyBlockedDate.block_date < booking.check_out
    ).first()

    if owner_block:
        flash(
            "This booking overlaps with dates blocked by the property owner. The booking cannot be approved.",
            "danger"
        )
        return redirect(url_for("admin_dashboard"))

    existing_approved_booking = Booking.query.filter(
        Booking.id != booking.id,
        Booking.property_id == booking.property_id,
        Booking.status == "approved",
        Booking.check_in < booking.check_out,
        Booking.check_out > booking.check_in
    ).first()

    if existing_approved_booking:
        flash(
            "Another approved booking already exists for these dates.",
            "danger"
        )
        return redirect(url_for("admin_dashboard"))

    booking.status = "approved"
    db.session.commit()

    flash("Booking approved successfully.", "success")

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
# MODIFY PROPERTY - OWNER
# ==================================================
#
# Owners can modify ONLY their own property while it
# is still pending Admin approval.
#
# Owner-editable fields:
# - Property name
# - Property address
# - Location
# - Images
#
# Admin-controlled fields are never accepted from this
# form: max guests, pricing, pricing method and
# availability type.
#
# Once a property is approved or rejected, the owner
# cannot modify it.
# ==================================================
@app.route(
    "/owner/property/<int:property_id>/modify",
    methods=["GET", "POST"]
)
@login_required
def modify_property(property_id):

    if current_user.role not in [
        "owner",
        "admin"
    ]:
        return "Access denied", 403

    property_obj = Property.query.filter_by(
        id=property_id,
        owner_id=current_user.id
    ).first()

    if not property_obj:
        flash(
            "Property not found or you do not have permission to modify it.",
            "danger"
        )
        return redirect(url_for("owner_dashboard"))

    # IMPORTANT: Modify is available only before Admin approval.
    if property_obj.status != "pending":
        flash(
            "This property can no longer be modified because it is not pending Admin approval.",
            "danger"
        )
        return redirect(url_for("owner_dashboard"))

    # ==================================================
    # GET
    # ==================================================
    if request.method == "GET":

        submission_token = secrets.token_urlsafe(32)

        session["modify_property_token"] = {
            "property_id": property_id,
            "token": submission_token
        }

        return render_template(
            "modify_property.html",
            property=property_obj,
            submission_token=submission_token
        )

    # ==================================================
    # POST
    # ==================================================
    token_data = session.pop(
        "modify_property_token",
        None
    )

    submitted_token = request.form.get(
        "submission_token",
        ""
    ).strip()

    if not isinstance(token_data, dict):
        return redirect(
            url_for("owner_dashboard"),
            code=303
        )

    if (
        token_data.get("property_id") != property_id
        or not submitted_token
        or submitted_token != token_data.get("token")
    ):
        return redirect(
            url_for("owner_dashboard"),
            code=303
        )

    # Re-check the database status on POST so an already-approved
    # property cannot be changed using an old edit page.
    property_obj = Property.query.filter_by(
        id=property_id,
        owner_id=current_user.id
    ).first()

    if not property_obj:
        flash("Property not found.", "danger")
        return redirect(url_for("owner_dashboard"))

    if property_obj.status != "pending":
        flash(
            "This property has already been processed by Admin and can no longer be modified.",
            "danger"
        )
        return redirect(url_for("owner_dashboard"))

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
        return "Property name is required", 400

    if not property_address:
        return "Property address is required", 400

    if not location:
        return "Location is required", 400

    # Only owner-editable fields are updated here.
    property_obj.property_name = property_name
    property_obj.property_address = property_address
    property_obj.location = location

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    for slot in range(1, 11):
        file = request.files.get(f"image_{slot}")
        if not file or not file.filename:
            continue
        mime = (file.mimetype or "").lower()
        if mime not in allowed_types:
            return f"Image {slot} has an unsupported format.", 400
        data = file.read()
        if not data:
            return f"Image {slot} is empty.", 400

        image = PropertyImage.query.filter_by(
            property_id=property_id, slot=slot
        ).first()
        if not image:
            image = PropertyImage(
                property_id=property_id,
                slot=slot
            )
            db.session.add(image)

        # Owners may replace an image only when it is not already approved.
        if image.status == "approved":
            continue

        image.filename = file.filename
        image.mime_type = mime
        image.image_data = data
        image.status = "pending"
        image.rejection_reason = None

    # Do NOT change:
    # - status
    # - max_guests
    # - pricing_method
    # - pricing_data
    # - availability_type

    db.session.commit()

    flash(
        "Property details updated successfully. The property remains pending Admin approval.",
        "success"
    )

    return redirect(
        url_for("owner_dashboard"),
        code=303
    )


# ==================================================
# PROPERTY IMAGE ROUTES
# ==================================================

@app.route("/property-image/<int:image_id>")
def property_image(image_id):
    image = db.session.get(PropertyImage, image_id)
    if not image or image.status != "approved":
        return "Image not available", 404
    return app.response_class(
        image.image_data,
        mimetype=image.mime_type,
        headers={"Cache-Control": "public, max-age=3600"}
    )


@app.route("/admin/property-image/<int:image_id>/view")
@login_required
def admin_view_property_image(image_id):
    if not current_user.is_admin:
        return "Unauthorized", 403
    image = db.session.get(PropertyImage, image_id)
    if not image:
        return "Image not found", 404
    return app.response_class(
        image.image_data,
        mimetype=image.mime_type,
        headers={"Content-Disposition": "inline"}
    )


@app.route("/owner/property-image/<int:image_id>")
@login_required
def owner_view_property_image(image_id):
    """Allow the property owner to preview their own pending images."""
    image = db.session.get(PropertyImage, image_id)
    if not image:
        return "Image not found", 404

    property_obj = db.session.get(Property, image.property_id)
    if not property_obj:
        return "Property not found", 404

    if not current_user.is_admin and property_obj.owner_id != current_user.id:
        return "Unauthorized", 403

    return app.response_class(
        image.image_data,
        mimetype=image.mime_type,
        headers={"Content-Disposition": "inline", "Cache-Control": "no-store"}
    )


@app.route("/admin/property-image/<int:image_id>/download")
@login_required
def admin_download_property_image(image_id):
    if not current_user.is_admin:
        return "Unauthorized", 403
    image = db.session.get(PropertyImage, image_id)
    if not image:
        return "Image not found", 404
    return app.response_class(
        image.image_data,
        mimetype=image.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{image.filename}"'
        }
    )


@app.route("/admin/property-image/<int:image_id>/approve", methods=["POST"])
@login_required
def approve_property_image(image_id):
    if not current_user.is_admin:
        return "Unauthorized", 403
    image = db.session.get(PropertyImage, image_id)
    if not image:
        return "Image not found", 404
    image.status = "approved"
    image.rejection_reason = None
    db.session.commit()
    flash(f"Image {image.slot} approved.", "success")
    return redirect(url_for("admin_dashboard") + "#properties")


@app.route("/admin/property-image/<int:image_id>/request-reupload", methods=["POST"])
@login_required
def request_property_image_reupload(image_id):
    if not current_user.is_admin:
        return "Unauthorized", 403
    image = db.session.get(PropertyImage, image_id)
    if not image:
        return "Image not found", 404
    reason = request.form.get("reason", "Image needs to be replaced by the owner.").strip()
    image.status = "reupload_required"
    image.rejection_reason = reason[:1000] if reason else "Image needs to be replaced by the owner."
    db.session.commit()
    flash(f"Image {image.slot} was removed and the owner was asked to re-upload it.", "info")
    return redirect(url_for("admin_dashboard") + "#properties")


@app.route("/admin/property/<int:property_id>/image/<int:slot>/upload", methods=["POST"])
@login_required
def admin_upload_property_image(property_id, slot):
    """Admin can upload or replace any of the 10 property image slots."""
    if not current_user.is_admin or slot < 1 or slot > 10:
        return "Access denied", 403

    property_obj = db.session.get(Property, property_id)
    if not property_obj:
        return "Property not found", 404

    file = request.files.get("image")
    if not file or not file.filename:
        flash(f"Please select an image for slot {slot}.", "danger")
        return redirect(url_for("admin_dashboard") + "#properties")

    mime = (file.mimetype or "").lower()
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if mime not in allowed_types:
        flash("Unsupported image format. Use JPG, PNG, WEBP or GIF.", "danger")
        return redirect(url_for("admin_dashboard") + "#properties")

    data = file.read()
    if not data:
        flash("The uploaded image is empty.", "danger")
        return redirect(url_for("admin_dashboard") + "#properties")

    image = PropertyImage.query.filter_by(
        property_id=property_id, slot=slot
    ).first()

    if not image:
        image = PropertyImage(property_id=property_id, slot=slot)
        db.session.add(image)

    image.filename = file.filename
    image.mime_type = mime
    image.image_data = data
    image.status = "approved"
    image.rejection_reason = None

    db.session.commit()

    flash(f"Image {slot} uploaded by Admin and approved.", "success")
    return redirect(url_for("admin_dashboard") + "#properties")


@app.route("/owner/property/<int:property_id>/image/<int:slot>/upload", methods=["POST"])
@login_required
def owner_reupload_property_image(property_id, slot):
    if current_user.role not in ["owner", "admin"] or slot < 1 or slot > 10:
        return "Access denied", 403

    property_obj = Property.query.filter_by(
        id=property_id, owner_id=current_user.id
    ).first()
    if not property_obj:
        return "Property not found", 404
    if property_obj.status != "pending":
        flash("Images can only be changed before Admin approves the property.", "danger")
        return redirect(url_for("owner_dashboard"))

    file = request.files.get("image")
    if not file or not file.filename:
        flash("Please select an image.", "danger")
        return redirect(url_for("owner_dashboard"))

    mime = (file.mimetype or "").lower()
    if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        flash("Unsupported image format.", "danger")
        return redirect(url_for("owner_dashboard"))

    data = file.read()
    if not data:
        flash("The uploaded image is empty.", "danger")
        return redirect(url_for("owner_dashboard"))

    image = PropertyImage.query.filter_by(
        property_id=property_id, slot=slot
    ).first()

    if not image:
        image = PropertyImage(property_id=property_id, slot=slot)
        db.session.add(image)

    image.filename = file.filename
    image.mime_type = mime
    image.image_data = data
    image.status = "pending"
    image.rejection_reason = None
    db.session.commit()

    flash(f"Image {slot} uploaded and sent to Admin for review.", "success")
    return redirect(url_for("owner_dashboard"))


# ==================================================
# ADMIN TYPE 2 CALENDAR
# ==================================================

@app.route("/admin/property/<int:property_id>/calendar")
@login_required
def admin_type2_calendar(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    properties = Property.query.filter(
        Property.status == "approved",
        Property.availability_type == "type2"
    ).order_by(Property.created_at.desc()).all()

    selected_property = db.session.get(Property, property_id)

    if (
        not selected_property
        or selected_property.status != "approved"
        or selected_property.availability_type != "type2"
    ):
        return "Type 2 property not found", 404

    return render_template(
        "admin_type2_calendar.html",
        properties=properties,
        selected_property=selected_property
    )


@app.route("/admin/property/<int:property_id>/calendar/data")
@login_required
def admin_type2_calendar_data(property_id):

    if not current_user.is_admin:
        return {"status": "error", "message": "Unauthorized"}, 403

    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    if not year or not month or month < 1 or month > 12:
        return {"status": "error", "message": "Invalid calendar request."}, 400

    property_obj = db.session.get(Property, property_id)

    if (
        not property_obj
        or property_obj.status != "approved"
        or property_obj.availability_type != "type2"
    ):
        return {"status": "error", "message": "Type 2 property not found."}, 404

    month_start = date(year, month, 1)
    next_month = (
        date(year + 1, 1, 1)
        if month == 12
        else date(year, month + 1, 1)
    )

    blocks = PropertyBlockedDate.query.filter(
        PropertyBlockedDate.property_id == property_id,
        PropertyBlockedDate.block_date >= month_start,
        PropertyBlockedDate.block_date < next_month
    ).all()

    owner_blocked_dates = sorted(
        b.block_date.isoformat()
        for b in blocks
        if b.blocked_by == "owner"
    )

    goinn_blocked_dates = sorted(
        b.block_date.isoformat()
        for b in blocks
        if b.blocked_by in ["goinn", "booking"]
    )

    bookings = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status == "approved",
        Booking.check_in < next_month,
        Booking.check_out > month_start
    ).all()

    booked_dates = set()

    for booking in bookings:
        current_date = max(booking.check_in, month_start)
        booking_end = min(booking.check_out, next_month)

        while current_date < booking_end:
            booked_dates.add(current_date.isoformat())
            current_date += timedelta(days=1)

    return {
        "status": "ok",
        "property_id": property_id,
        "year": year,
        "month": month,
        "today": date.today().isoformat(),
        "booked_dates": sorted(booked_dates),
        "owner_blocked_dates": owner_blocked_dates,
        "goinn_blocked_dates": goinn_blocked_dates
    }


@app.route("/admin/property/<int:property_id>/calendar/block", methods=["POST"])
@login_required
def admin_type2_block_date(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    property_obj = db.session.get(Property, property_id)

    if (
        not property_obj
        or property_obj.status != "approved"
        or property_obj.availability_type != "type2"
    ):
        return "Type 2 property not found", 404

    block_date_text = request.form.get("block_date", "").strip()

    try:
        block_date = datetime.strptime(
            block_date_text,
            "%Y-%m-%d"
        ).date()
    except ValueError:
        flash("Invalid date.", "danger")
        return redirect(url_for("admin_type2_calendar", property_id=property_id))

    if block_date < date.today():
        flash("Past dates cannot be blocked.", "danger")
        return redirect(url_for("admin_type2_calendar", property_id=property_id))

    booking = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status.in_(["pending", "approved"]),
        Booking.check_in <= block_date,
        Booking.check_out > block_date
    ).first()

    if booking:
        flash("This date has a booking and cannot be blocked.", "danger")
        return redirect(url_for("admin_type2_calendar", property_id=property_id))

    existing = PropertyBlockedDate.query.filter_by(
        property_id=property_id,
        block_date=block_date
    ).first()

    if existing:
        flash("This date is already blocked.", "info")
    else:
        db.session.add(PropertyBlockedDate(
            property_id=property_id,
            block_date=block_date,
            blocked_by="goinn"
        ))
        db.session.commit()
        flash("Date blocked successfully.", "success")

    return redirect(url_for("admin_type2_calendar", property_id=property_id))


@app.route("/admin/property/<int:property_id>/calendar/unblock", methods=["POST"])
@login_required
def admin_type2_unblock_date(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    property_obj = db.session.get(Property, property_id)

    if (
        not property_obj
        or property_obj.status != "approved"
        or property_obj.availability_type != "type2"
    ):
        return "Type 2 property not found", 404

    block_date_text = request.form.get("block_date", "").strip()

    try:
        block_date = datetime.strptime(
            block_date_text,
            "%Y-%m-%d"
        ).date()
    except ValueError:
        flash("Invalid date.", "danger")
        return redirect(url_for("admin_type2_calendar", property_id=property_id))

    blocked_date = PropertyBlockedDate.query.filter_by(
        property_id=property_id,
        block_date=block_date,
        blocked_by="goinn"
    ).first()

    if not blocked_date:
        flash("This date is not blocked by Goinn.", "info")
    else:
        db.session.delete(blocked_date)
        db.session.commit()
        flash("Date is available again.", "success")

    return redirect(url_for("admin_type2_calendar", property_id=property_id))


# ==================================================
# TYPE 3 AVAILABILITY
# ==================================================

def _block_booking_dates(booking, blocked_by="booking"):

    current_date = booking.check_in

    while current_date < booking.check_out:

        existing = PropertyBlockedDate.query.filter_by(
            property_id=booking.property_id,
            block_date=current_date
        ).first()

        if not existing:
            db.session.add(PropertyBlockedDate(
                property_id=booking.property_id,
                block_date=current_date,
                blocked_by=blocked_by
            ))

        current_date += timedelta(days=1)


@app.route("/admin/availability/<int:booking_id>/available", methods=["POST"])
@login_required
def type3_available(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    if booking.status != "availability_requested":
        flash("This availability request has already been handled.", "info")
        return redirect(url_for("admin_dashboard"))

    property_obj = booking.property

    if not property_obj or property_obj.availability_type != "type3":
        return "Invalid Type 3 request", 400

    if not is_property_available(
        property_obj.id,
        booking.check_in,
        booking.check_out
    ):
        flash("The requested dates are no longer available.", "danger")
        return redirect(url_for("admin_dashboard"))

    booking.status = "approved"

    _block_booking_dates(booking, blocked_by="booking")

    db.session.commit()

    flash(
        f"Type 3 request #{booking.id} approved and dates blocked.",
        "success"
    )

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/availability/<int:booking_id>/not-available", methods=["POST"])
@login_required
def type3_not_available(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    if booking.status != "availability_requested":
        flash("This availability request has already been handled.", "info")
        return redirect(url_for("admin_dashboard"))

    booking.status = "rejected"
    db.session.commit()

    flash(
        f"Type 3 request #{booking.id} marked as not available.",
        "success"
    )

    return redirect(url_for("admin_dashboard"))


# ==================================================
# OWNER CALENDAR
# ==================================================

@app.route("/owner/calendar")
@login_required
def owner_calendar():

    if current_user.role not in ["owner", "admin"]:
        return "Access denied", 403

    properties = Property.query.filter_by(
        owner_id=current_user.id
    ).order_by(
        Property.created_at.desc()
    ).all()

    selected_property_id = request.args.get(
        "property_id",
        type=int
    )

    selected_property = None

    if selected_property_id:
        selected_property = Property.query.filter_by(
            id=selected_property_id,
            owner_id=current_user.id
        ).first()

    if not selected_property and properties:
        selected_property = properties[0]

    return render_template(
        "owner_calendar.html",
        properties=properties,
        selected_property=selected_property
    )


@app.route("/owner/calendar/data")
@login_required
def owner_calendar_data():

    if current_user.role not in ["owner", "admin"]:
        return {"status": "error", "message": "Access denied"}, 403

    property_id = request.args.get("property_id", type=int)
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    if not property_id or not year or not month or month < 1 or month > 12:
        return {"status": "error", "message": "Invalid calendar request."}, 400

    property_obj = Property.query.filter_by(
        id=property_id,
        owner_id=current_user.id
    ).first()

    if not property_obj:
        return {"status": "error", "message": "Property not found."}, 404

    month_start = date(year, month, 1)

    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    # Owner blocks: one query for the month.
    owner_blocks = PropertyBlockedDate.query.filter(
        PropertyBlockedDate.property_id == property_id,
        PropertyBlockedDate.blocked_by == "owner",
        PropertyBlockedDate.block_date >= month_start,
        PropertyBlockedDate.block_date < next_month
    ).all()

    owner_blocked_dates = [
        blocked.block_date.isoformat()
        for blocked in owner_blocks
    ]

    goinn_blocks = PropertyBlockedDate.query.filter(
        PropertyBlockedDate.property_id == property_id,
        PropertyBlockedDate.blocked_by.in_(["goinn", "booking"]),
        PropertyBlockedDate.block_date >= month_start,
        PropertyBlockedDate.block_date < next_month
    ).all()

    goinn_blocked_dates = [
        blocked.block_date.isoformat()
        for blocked in goinn_blocks
    ]

    # Approved bookings: one query for all bookings touching this month.
    bookings = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status == "approved",
        Booking.check_in < next_month,
        Booking.check_out > month_start
    ).all()

    booked_dates = set()

    for booking in bookings:
        current_date = max(
            booking.check_in,
            month_start
        )
        booking_end = min(
            booking.check_out,
            next_month
        )

        while current_date < booking_end:
            booked_dates.add(
                current_date.isoformat()
            )
            current_date += timedelta(days=1)

    return {
        "status": "ok",
        "property_id": property_id,
        "year": year,
        "month": month,
        "today": date.today().isoformat(),
        "booked_dates": sorted(booked_dates),
        "owner_blocked_dates": sorted(owner_blocked_dates),
        "goinn_blocked_dates": sorted(goinn_blocked_dates)
    }


@app.route("/owner/calendar/block", methods=["POST"])
@login_required
def owner_block_date():

    if current_user.role not in ["owner", "admin"]:
        return "Access denied", 403

    property_id = request.form.get("property_id", type=int)
    block_date_text = request.form.get("block_date", "").strip()

    property_obj = Property.query.filter_by(
        id=property_id,
        owner_id=current_user.id
    ).first()

    if not property_obj:
        flash("Property not found.", "danger")
        return redirect(url_for("owner_calendar"))

    if property_obj.availability_type != "type1":
        flash(
            "Only Type 1 properties can be managed by the owner.",
            "danger"
        )
        return redirect(
            url_for(
                "owner_calendar",
                property_id=property_id
            )
        )

    try:
        block_date = datetime.strptime(
            block_date_text, "%Y-%m-%d"
        ).date()
    except ValueError:
        flash("Invalid date.", "danger")
        return redirect(url_for("owner_calendar", property_id=property_id))

    if block_date < date.today():
        flash("Past dates cannot be blocked.", "danger")
        return redirect(url_for("owner_calendar", property_id=property_id))

    booking = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status.in_(["pending", "approved"]),
        Booking.check_in <= block_date,
        Booking.check_out > block_date
    ).first()

    if booking:
        if booking.status == "approved":
            flash("This date belongs to an approved booking and cannot be changed.", "danger")
        else:
            flash("This date has a pending booking and cannot be blocked.", "danger")
        return redirect(url_for("owner_calendar", property_id=property_id))

    existing_block = PropertyBlockedDate.query.filter_by(
        property_id=property_id,
        block_date=block_date
    ).first()

    if existing_block:
        flash("This date is already blocked.", "info")
        return redirect(url_for("owner_calendar", property_id=property_id))

    db.session.add(PropertyBlockedDate(
        property_id=property_id,
        block_date=block_date,
        blocked_by="owner"
    ))
    db.session.commit()

    flash(
        f"{block_date.strftime('%d-%m-%Y')} has been blocked successfully.",
        "success"
    )

    return redirect(url_for("owner_calendar", property_id=property_id))


@app.route("/owner/calendar/unblock", methods=["POST"])
@login_required
def owner_unblock_date():

    if current_user.role not in ["owner", "admin"]:
        return "Access denied", 403

    property_id = request.form.get("property_id", type=int)
    block_date_text = request.form.get("block_date", "").strip()

    property_obj = Property.query.filter_by(
        id=property_id,
        owner_id=current_user.id
    ).first()

    if not property_obj:
        flash("Property not found.", "danger")
        return redirect(url_for("owner_calendar"))

    if property_obj.availability_type != "type1":
        flash(
            "Only Type 1 properties can be managed by the owner.",
            "danger"
        )
        return redirect(
            url_for(
                "owner_calendar",
                property_id=property_id
            )
        )

    try:
        block_date = datetime.strptime(
            block_date_text, "%Y-%m-%d"
        ).date()
    except ValueError:
        flash("Invalid date.", "danger")
        return redirect(url_for("owner_calendar", property_id=property_id))

    approved_booking = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status == "approved",
        Booking.check_in <= block_date,
        Booking.check_out > block_date
    ).first()

    if approved_booking:
        flash(
            "This date belongs to an approved booking and cannot be unblocked.",
            "danger"
        )
        return redirect(url_for("owner_calendar", property_id=property_id))

    blocked_date = PropertyBlockedDate.query.filter_by(
        property_id=property_id,
        block_date=block_date,
        blocked_by="owner"
    ).first()

    if not blocked_date:
        flash("This date is not blocked by you.", "info")
        return redirect(url_for("owner_calendar", property_id=property_id))

    db.session.delete(blocked_date)
    db.session.commit()

    flash(
        f"{block_date.strftime('%d-%m-%Y')} is available again.",
        "success"
    )

    return redirect(url_for("owner_calendar", property_id=property_id))


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

    if current_user.role not in ["owner", "admin"]:
        return "Access denied", 403

    if request.method == "GET":
        submission_token = secrets.token_urlsafe(32)
        session["add_property_token"] = submission_token
        return render_template(
            "add_property.html",
            submission_token=submission_token
        )

    submitted_token = request.form.get("submission_token", "").strip()
    session_token = session.pop("add_property_token", None)

    if not submitted_token or submitted_token != session_token:
        return redirect(url_for("owner_dashboard"), code=303)

    property_name = request.form.get("property_name", "").strip()
    property_address = request.form.get("property_address", "").strip()
    location = request.form.get("location", "").strip()

    if not property_name:
        return "Property name is required", 400
    if not property_address:
        return "Property address is required", 400
    if not location:
        return "Location is required", 400

    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif"
    }

    uploaded = []
    for slot in range(1, 11):
        file = request.files.get(f"image_{slot}")
        if not file or not file.filename:
            continue
        mime = (file.mimetype or "").lower()
        if mime not in allowed_types:
            return f"Image {slot} has an unsupported format. Use JPG, JPEG, PNG, WEBP or GIF.", 400
        data = file.read()
        if not data:
            continue
        uploaded.append((slot, file.filename, mime, data))

    if len(uploaded) == 0:
        return "Please upload at least one property image.", 400

    property_obj = Property(
        owner_id=current_user.id,
        property_name=property_name,
        property_address=property_address,
        location=location,
        images=None,
        max_guests=0,
        pricing_method=None,
        pricing_data=None,
        availability_type="type1",
        status="pending"
    )

    db.session.add(property_obj)
    db.session.flush()

    for slot, filename, mime, data in uploaded:
        db.session.add(PropertyImage(
            property_id=property_obj.id,
            slot=slot,
            filename=filename,
            mime_type=mime,
            image_data=data,
            status="pending"
        ))

    db.session.commit()

    flash(
        "Property created successfully. Admin will review each image before it is shown to customers.",
        "success"
    )
    return redirect(url_for("owner_dashboard"), code=303)


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

    availability_requests = Booking.query.filter_by(
        status="availability_requested"
    ).count()

    return render_template(
        "admin_dashboard.html",
        properties=properties,
        bookings=bookings,
        users=users,
        pending_bookings=pending_bookings,
        rejected_bookings=rejected_bookings,
        rejected_properties=rejected_properties,
        property_owners=property_owners,
        availability_requests=availability_requests
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

    availability_type = request.form.get(
        "availability_type",
        "type1"
    ).strip().lower()

    if availability_type not in ["type1", "type2", "type3"]:
        return "Invalid availability type.", 400

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

    property_obj.availability_type = availability_type

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
    # APPROVE ONLY AFTER AT LEAST ONE IMAGE IS APPROVED
    # =================================================

    approved_image_count = PropertyImage.query.filter_by(
        property_id=property_obj.id,
        status="approved"
    ).count()

    if approved_image_count < 1:
        property_obj.status = "pending"
        db.session.commit()
        flash(
            "Pricing saved, but the property remains Pending. Admin must approve at least one property image before the property can go live.",
            "info"
        )
        return redirect(url_for("admin_dashboard"))

    property_obj.status = "approved"

    db.session.commit()

    flash("Pricing saved and property approved successfully.", "success")

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

            PropertyBlockedDate.query.filter_by(
                property_id=property_obj.id
            ).delete(
                synchronize_session=False
            )

            PropertyImage.query.filter_by(
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

            PropertyBlockedDate.query.filter_by(
                property_id=property_obj.id
            ).delete(
                synchronize_session=False
            )

            PropertyImage.query.filter_by(
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

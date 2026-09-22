from flask import (
    Flask,
    render_template,
    request,
    redirect,
    flash,
    url_for,
    session,
    jsonify
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
import re
import os
import urllib.parse
import json
import secrets
import smtplib
from email.message import EmailMessage
from html import escape as html_escape

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
# GMAIL EMAIL CONFIGURATION
# ==================================================
# Use a Gmail address and a Google App Password.
# Do NOT use the normal Gmail account password.
app.config["GMAIL_ADDRESS"] = os.environ.get(
    "GMAIL_ADDRESS",
    ""
).strip()

app.config["GMAIL_APP_PASSWORD"] = os.environ.get(
    "GMAIL_APP_PASSWORD",
    ""
).strip()

app.config["GMAIL_SMTP_HOST"] = os.environ.get(
    "GMAIL_SMTP_HOST",
    "smtp.gmail.com"
).strip()

app.config["GMAIL_SMTP_PORT"] = int(
    os.environ.get(
        "GMAIL_SMTP_PORT",
        "587"
    )
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

# Keep PostgreSQL connections healthy on Render.  A stale pooled
# connection can otherwise make the calendar API fail intermittently.
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

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

    # ------------------------------------------------
    # ADMIN MAP LOCATION
    # ------------------------------------------------
    # Stored separately from the searchable city/location text.
    # Coordinates are set by the admin in Property Steps.
    map_latitude = db.Column(
        db.Float,
        nullable=True
    )

    map_longitude = db.Column(
        db.Float,
        nullable=True
    )

    map_location_url = db.Column(
        db.Text,
        nullable=True
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

    rejection_reason = db.Column(
        db.Text,
        nullable=True
    )

    # ------------------------------------------------
    # ADMIN-CONTROLLED AMENITIES
    # ------------------------------------------------

    # Stored as JSON: {"Category": ["Amenity", ...]}
    amenities_data = db.Column(
        db.Text,
        nullable=True
    )

    # ------------------------------------------------
    # TERMS & CONDITIONS
    # ------------------------------------------------

    terms_conditions = db.Column(
        db.Text,
        nullable=True
    )

    # ------------------------------------------------
    # ADMIN PROPERTY STEPS
    # ------------------------------------------------

    property_type = db.Column(
        db.String(40),
        nullable=True
    )

    property_details_data = db.Column(
        db.Text,
        nullable=True
    )

    type_pricing_data = db.Column(
        db.Text,
        nullable=True
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
# PROPERTY STEP IMAGE MODEL
# ==================================================

class PropertyStepImage(db.Model):

    __tablename__ = "property_step_images"

    id = db.Column(db.Integer, primary_key=True)

    property_id = db.Column(
        db.Integer,
        db.ForeignKey("property.id"),
        nullable=False
    )

    category = db.Column(db.String(40), nullable=False)
    target_key = db.Column(db.String(120), nullable=False)
    unit_index = db.Column(db.Integer, nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    image_data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    property = db.relationship(
        "Property",
        backref=db.backref(
            "step_images",
            lazy=True,
            cascade="all, delete-orphan"
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

    # JSON describing the exact rooms/units/flats selected by the user.
    selected_accommodations = db.Column(
        db.Text,
        nullable=True
    )

    rejection_reason = db.Column(
        db.Text,
        nullable=True
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
# INVENTORY BLOCKED DATE MODEL
# ==================================================

class InventoryBlockedDate(db.Model):
    __tablename__ = "inventory_blocked_dates"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False)
    inventory_key = db.Column(db.String(160), nullable=False)
    block_date = db.Column(db.Date, nullable=False)
    blocked_by = db.Column(db.String(20), nullable=False, default="owner")
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    property = db.relationship("Property", backref=db.backref("inventory_blocked_dates", lazy=True, cascade="all, delete-orphan"))


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
        # BOOKING REJECTION REASON
        # ------------------------------------------

        if "booking" in tables:

            booking_columns = {
                column["name"]
                for column in inspector.get_columns(
                    "booking"
                )
            }

            if "rejection_reason" not in booking_columns:

                with db.engine.begin() as connection:

                    connection.exec_driver_sql(
                        """ALTER TABLE booking ADD COLUMN rejection_reason TEXT"""
                    )

            if "selected_accommodations" not in booking_columns:

                with db.engine.begin() as connection:

                    connection.exec_driver_sql(
                        """ALTER TABLE booking ADD COLUMN selected_accommodations TEXT"""
                    )

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
        # REJECTION REASON
        # ------------------------------------------

        if "rejection_reason" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN rejection_reason TEXT
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

        # ------------------------------------------
        # AMENITIES DATA
        # ------------------------------------------

        if "amenities_data" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN amenities_data TEXT
                    """
                )

        # ------------------------------------------
        # TERMS & CONDITIONS
        # ------------------------------------------

        if "terms_conditions" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN terms_conditions TEXT
                    """
                )

        # ------------------------------------------
        # PROPERTY TYPE
        # ------------------------------------------

        if "property_type" not in columns:

            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN property_type VARCHAR(40)
                    """
                )

        # ------------------------------------------
        # PROPERTY DETAILS JSON
        # ------------------------------------------

        if "property_details_data" not in columns:

            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN property_details_data TEXT
                    """
                )

        # ------------------------------------------
        # TYPE-SPECIFIC PRICING JSON
        # ------------------------------------------

        if "type_pricing_data" not in columns:

            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN type_pricing_data TEXT
                    """
                )

        # ------------------------------------------
        # ADMIN MAP LOCATION
        # ------------------------------------------

        if "map_latitude" not in columns:
            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN map_latitude DOUBLE PRECISION
                    """
                )

        if "map_longitude" not in columns:
            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN map_longitude DOUBLE PRECISION
                    """
                )

        if "map_location_url" not in columns:
            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    ALTER TABLE property
                    ADD COLUMN map_location_url TEXT
                    """
                )

        # PropertyStepImage is created by db.create_all().

    except Exception as error:

        print(
            "Database migration warning:",
            error
        )

# ==================================================
# AMENITIES HELPER
# ==================================================

def get_property_amenities(property_obj):
    if not property_obj or not property_obj.amenities_data:
        return {}
    try:
        data = json.loads(property_obj.amenities_data)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_property_step_details(property_obj):
    if not property_obj or not property_obj.property_details_data:
        return {}
    try:
        data = json.loads(property_obj.property_details_data)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_type_pricing(property_obj):
    if not property_obj or not property_obj.type_pricing_data:
        return {}
    try:
        data = json.loads(property_obj.type_pricing_data)
        return data if isinstance(data, (dict, list)) else {}
    except Exception:
        return {}


def get_booking_accommodations(booking):
    """Safely read the accommodation selection stored on a booking.

    The calendar, availability and inventory allocation code all use this
    helper.  Older bookings and guesthouse bookings may not have a value,
    while malformed legacy JSON must not be allowed to break the calendar API.
    """
    if not booking or not booking.selected_accommodations:
        return []

    try:
        data = json.loads(booking.selected_accommodations)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    return [item for item in data if isinstance(item, dict)]


def get_accommodation_options(property_obj):
    """Return configured logical accommodation inventory for calendar and booking."""
    if not property_obj or property_obj.property_type == "guesthouse":
        return []

    details = get_property_step_details(property_obj)
    pricing = get_type_pricing(property_obj)
    ptype = property_obj.property_type
    options = []

    if ptype == "resort":
        for unit in details.get("units", []):
            try:
                idx = int(unit.get("unit"))
            except (TypeError, ValueError):
                continue
            price = pricing.get(str(idx), {}) if isinstance(pricing, dict) else {}
            options.append({
                "key": f"unit:{idx}",
                "label": f"Unit {idx}",
                "group": "Resort Unit",
                "count": 1,
                "max_guests": int((price or {}).get("max_guests", 0) or 0),
                "price": float((price or {}).get("price", 0) or 0)
            })

    elif ptype == "hotel":
        labels = dict(HOTEL_ROOM_TYPES)
        for key, raw_count in details.get("room_types", {}).items():
            try:
                count = int(raw_count or 0)
            except (TypeError, ValueError):
                count = 0
            if count <= 0:
                continue
            price = pricing.get(key, {}) if isinstance(pricing, dict) else {}
            options.append({
                "key": str(key),
                "label": labels.get(key, key.replace("_", " ").title()),
                "group": "Hotel Room",
                "count": count,
                "max_guests": int((price or {}).get("max_guests", 0) or 0),
                "price": float((price or {}).get("price", 0) or 0)
            })

    elif ptype == "service_apartment":
        labels = dict(FLAT_TYPES)
        for key, raw_count in details.get("flat_types", {}).items():
            try:
                count = int(raw_count or 0)
            except (TypeError, ValueError):
                count = 0
            if count <= 0:
                continue
            price = pricing.get(key, {}) if isinstance(pricing, dict) else {}
            options.append({
                "key": str(key),
                "label": labels.get(key, key.upper()),
                "group": "Service Apartment",
                "count": count,
                "max_guests": int((price or {}).get("max_guests", 0) or 0),
                "price": float((price or {}).get("price", 0) or 0)
            })

    return options


def get_physical_inventory(property_obj):
    """Expand resort units, hotel rooms and BHK flats into individually manageable calendar inventory."""
    if not property_obj or property_obj.property_type == "guesthouse":
        return [{"key": "property", "base_key": "property", "label": property_obj.property_name if property_obj else "Property"}]
    physical = []
    for opt in get_accommodation_options(property_obj):
        for number in range(1, int(opt.get("count", 0)) + 1):
            key = f"{opt['key']}:{number}"
            physical.append({"key": key, "base_key": str(opt["key"]),
                             "label": f"{opt['label']} #{number}",
                             "group": opt.get("group", "Accommodation"),
                             "max_guests": opt.get("max_guests", 0)})
    return physical


def get_inventory_blocked_counts(property_obj, check_in, check_out):
    """Return how many physical inventory items are blocked for the
    requested stay.

    A physical room/unit/flat is counted only once, even when it has
    multiple blocked-date rows inside the requested date range.
    """
    if not property_obj or property_obj.property_type == "guesthouse":
        return {}

    rows = InventoryBlockedDate.query.filter(
        InventoryBlockedDate.property_id == property_obj.id,
        InventoryBlockedDate.block_date >= check_in,
        InventoryBlockedDate.block_date < check_out
    ).all()

    # Count unique physical inventory keys per logical accommodation.
    # Example:
    #   queen:1 blocked on two nights + queen:2 blocked on one night
    #   => 2 unavailable Queen rooms, not 3.
    blocked_physical = {}
    for row in rows:
        key = str(row.inventory_key or "")
        if not key:
            continue
        base = inventory_base_key(property_obj, key)
        blocked_physical.setdefault(base, set()).add(key)

    return {
        base: len(keys)
        for base, keys in blocked_physical.items()
    }



def get_available_accommodation_options(property_obj, check_in, check_out):
    """Return accommodation options with availability for a specific stay.

    The returned ``count`` is the number of physical rooms/units/flats
    actually available for the requested date range. It accounts for both
    active bookings and manual calendar blocks.
    """
    options = get_accommodation_options(property_obj)

    if not property_obj or property_obj.property_type == "guesthouse":
        return options

    reserved = get_reserved_accommodation_counts(
        property_obj,
        check_in,
        check_out
    )
    blocked = get_inventory_blocked_counts(
        property_obj,
        check_in,
        check_out
    )

    result = []
    for opt in options:
        total = int(opt.get("count", 0) or 0)
        held = int(reserved.get(opt["key"], 0) or 0)
        blocked_count = int(blocked.get(opt["key"], 0) or 0)
        available = max(0, total - held - blocked_count)

        item = dict(opt)
        item["available"] = available
        # ``count`` is what the existing property-details template uses
        # for its visible "X available" value and quantity limit.
        item["count"] = available
        result.append(item)

    return result


def inventory_base_key(property_obj, key):
    key = str(key or "")
    if property_obj and property_obj.property_type == "resort" and key.startswith("unit:") and key.count(":") >= 2:
        return key.rsplit(":", 1)[0]
    if property_obj and property_obj.property_type in ("hotel", "service_apartment") and key.count(":") >= 1 and key.split(":")[-1].isdigit():
        return key.rsplit(":", 1)[0]
    return key


def get_reserved_accommodation_counts(property_obj, check_in, check_out, exclude_booking_id=None):
    """Count logical accommodation quantities held by active bookings."""
    result = {}
    query = Booking.query.filter(
        Booking.property_id == property_obj.id,
        Booking.status.in_(["pending", "availability_requested", "approved"]),
        Booking.check_in < check_out,
        Booking.check_out > check_in
    )
    if exclude_booking_id is not None:
        query = query.filter(Booking.id != exclude_booking_id)
    for booking in query.all():
        for item in get_booking_accommodations(booking):
            key = str(item.get("key", ""))
            # Approved bookings may contain physical keys; convert them to logical keys.
            base = inventory_base_key(property_obj, key)
            try:
                qty = int(item.get("quantity", 0))
            except (TypeError, ValueError):
                qty = 0
            if base:
                result[base] = result.get(base, 0) + max(0, qty)
    return result


def validate_accommodation_selection(property_obj, selected, guests, check_in=None, check_out=None, exclude_booking_id=None):
    """Validate the cart including manual inventory blocks."""
    if property_obj.property_type == "guesthouse":
        price = get_property_price(property_obj, guests)
        return (price is not None, "Price for the selected guests is not configured.", [], price)
    if not isinstance(selected, list) or not selected:
        return False, "Please select at least one accommodation unit.", [], None
    options = {str(o["key"]): o for o in get_accommodation_options(property_obj)}
    reserved = get_reserved_accommodation_counts(property_obj, check_in, check_out, exclude_booking_id=exclude_booking_id) if check_in and check_out else {}
    blocked = get_inventory_blocked_counts(property_obj, check_in, check_out) if check_in and check_out else {}
    normalized, capacity, total_price = [], 0, 0.0
    for item in selected:
        key = str(item.get("key", ""))
        if key not in options:
            return False, "One of the selected accommodations is no longer available.", [], None
        try:
            qty = int(item.get("quantity", 0))
        except (TypeError, ValueError):
            return False, "Invalid accommodation quantity.", [], None
        if qty < 1:
            continue
        opt = options[key]
        available = int(opt["count"]) - int(reserved.get(key, 0)) - int(blocked.get(key, 0))
        if qty > available:
            return False, f"Only {max(0, available)} {opt['label']} available for the selected dates.", [], None
        capacity += qty * int(opt["max_guests"])
        total_price += qty * float(opt["price"])
        normalized.append({"key": key, "label": opt["label"], "quantity": qty,
                           "max_guests": int(opt["max_guests"]), "price": float(opt["price"])})
    if not normalized:
        return False, "Please select at least one accommodation unit.", [], None
    if capacity < guests:
        return False, f"Your selected accommodation capacity is {capacity} guests, but you entered {guests}. Add another room/unit/flat or choose a larger one.", [], None
    return True, "", normalized, total_price


def allocate_booking_inventory(booking):
    """On approval, assign logical selections to exact physical inventory slots."""
    if booking.property.property_type == "guesthouse":
        return True, ""
    physical = get_physical_inventory(booking.property)
    by_base = {}
    for item in physical:
        by_base.setdefault(item["base_key"], []).append(item["key"])
    blocked = {r.inventory_key for r in InventoryBlockedDate.query.filter(
        InventoryBlockedDate.property_id == booking.property_id,
        InventoryBlockedDate.block_date < booking.check_out,
        InventoryBlockedDate.block_date >= booking.check_in
    ).all()}
    reserved = set()
    for other in Booking.query.filter(
        Booking.property_id == booking.property_id,
        Booking.id != booking.id,
        Booking.status == "approved",
        Booking.check_in < booking.check_out,
        Booking.check_out > booking.check_in
    ).all():
        for item in get_booking_accommodations(other):
            key = str(item.get("key", ""))
            if key.count(":") >= 1 and key.split(":")[-1].isdigit():
                reserved.add(key)
    selected = get_booking_accommodations(booking)
    assigned = []
    for item in selected:
        base = str(item.get("key", ""))
        qty = int(item.get("quantity", 0))
        candidates = [k for k in by_base.get(base, []) if k not in blocked and k not in reserved]
        if len(candidates) < qty:
            return False, f"Not enough {item.get('label', base)} inventory is available for the requested dates."
        for key in candidates[:qty]:
            assigned.append({"key": key, "label": item.get("label", base), "quantity": 1,
                             "max_guests": item.get("max_guests", 0), "price": item.get("price", 0)})
            reserved.add(key)
    booking.selected_accommodations = json.dumps(assigned)
    return True, ""

def get_property_max_guests(property_obj):
    """Return public guest capacity from legacy or type-specific pricing."""
    if not property_obj:
        return None
    if property_obj.property_type in (None, "", "guesthouse"):
        return property_obj.max_guests if property_obj.max_guests and property_obj.max_guests > 0 else None
    pricing = get_type_pricing(property_obj)
    capacities = []
    if isinstance(pricing, dict):
        for item in pricing.values():
            if isinstance(item, dict):
                try:
                    value = int(item.get("max_guests", 0))
                    if value > 0:
                        capacities.append(value)
                except (TypeError, ValueError):
                    pass
    return max(capacities) if capacities else None


def get_property_total_capacity(property_obj):
    """Return the total guest capacity configured for the property.

    Guesthouse/Farmhouse uses the property's max_guests value.
    Resort units, hotel room types and service-apartment BHK types use
    their configured max_guests multiplied by the number of physical
    units/rooms/flats.
    """
    if not property_obj:
        return None

    ptype = (property_obj.property_type or "").strip().lower()

    if ptype in ("", "guesthouse"):
        try:
            value = int(property_obj.max_guests or 0)
        except (TypeError, ValueError):
            value = 0
        return value if value > 0 else None

    details = get_property_step_details(property_obj)
    pricing = get_type_pricing(property_obj)

    if not isinstance(pricing, dict):
        return None

    total = 0

    if ptype == "resort":
        units = details.get("units", [])
        if not isinstance(units, list):
            units = []

        for unit in units:
            try:
                unit_no = str(int(unit.get("unit")))
            except (TypeError, ValueError, AttributeError):
                continue

            price_info = pricing.get(unit_no, {})
            if not isinstance(price_info, dict):
                continue

            try:
                max_guests = int(price_info.get("max_guests", 0) or 0)
            except (TypeError, ValueError):
                max_guests = 0

            if max_guests > 0:
                total += max_guests

    elif ptype == "hotel":
        room_types = details.get("room_types", {})
        if not isinstance(room_types, dict):
            room_types = {}

        for room_key, raw_count in room_types.items():
            try:
                count = int(raw_count or 0)
            except (TypeError, ValueError):
                count = 0

            if count <= 0:
                continue

            price_info = pricing.get(str(room_key), {})
            if not isinstance(price_info, dict):
                continue

            try:
                max_guests = int(price_info.get("max_guests", 0) or 0)
            except (TypeError, ValueError):
                max_guests = 0

            if max_guests > 0:
                total += max_guests * count

    elif ptype == "service_apartment":
        flat_types = details.get("flat_types", {})
        if not isinstance(flat_types, dict):
            flat_types = {}

        for flat_key, raw_count in flat_types.items():
            try:
                count = int(raw_count or 0)
            except (TypeError, ValueError):
                count = 0

            if count <= 0:
                continue

            price_info = pricing.get(str(flat_key), {})
            if not isinstance(price_info, dict):
                continue

            try:
                max_guests = int(price_info.get("max_guests", 0) or 0)
            except (TypeError, ValueError):
                max_guests = 0

            if max_guests > 0:
                total += max_guests * count

    return total if total > 0 else None

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
    # TYPE-SPECIFIC PRICING
    # ------------------------------------------------
    if property_obj.property_type in {"resort", "hotel", "service_apartment"}:
        pricing = get_type_pricing(property_obj)
        matching_prices = []
        if isinstance(pricing, dict):
            for item in pricing.values():
                if not isinstance(item, dict):
                    continue
                try:
                    max_g = int(item.get("max_guests", 0))
                    price = float(item.get("price", -1))
                except (TypeError, ValueError):
                    continue
                if max_g >= guests and price >= 0:
                    matching_prices.append(price)
        return min(matching_prices) if matching_prices else None

    # ------------------------------------------------
    # LEGACY / GUESTHOUSE MAX GUEST VALIDATION
    # ------------------------------------------------
    if not property_obj.max_guests or property_obj.max_guests < 1:
        return None
    if guests > get_property_max_guests(property_obj):
        return None

    # ------------------------------------------------
    # EXISTING GUESTHOUSE PRICING
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
# BOOKING HOLD / FREEZE SETTINGS
# ==================================================

# A newly created booking request temporarily freezes the
# selected dates for 15 minutes. If the request is not
# approved (or otherwise handled) within that period, the
# hold expires and the property becomes available again.
BOOKING_FREEZE_MINUTES = 15


def expire_booking_holds():
    """Release expired pending/availability requests.

    Only temporary booking requests expire. Approved bookings
    are never touched by this cleanup.
    """

    cutoff = datetime.utcnow() - timedelta(
        minutes=BOOKING_FREEZE_MINUTES
    )

    expired = Booking.query.filter(
        Booking.status.in_([
            "pending",
            "availability_requested"
        ]),
        Booking.created_at.isnot(None),
        Booking.created_at < cutoff
    ).all()

    if not expired:
        return 0

    for booking in expired:
        booking.status = "cancelled"
        booking.rejection_reason = (
            "Booking request expired after 15 minutes without "
            "admin approval. The property was released automatically."
        )

    db.session.commit()
    return len(expired)


def get_property_booking_state(
    property_id,
    check_in,
    check_out,
    guests=None,
    exclude_booking_id=None
):
    """Return public availability for the requested dates.

    For multi-inventory properties (resort, hotel and service apartment),
    availability is calculated from the individual physical units/rooms/flats.
    Blocking two rooms therefore does NOT make the whole property booked when
    other inventory can still satisfy the requested guest count.

    States: available, freezing, booked, unavailable.
    """
    property_obj = db.session.get(Property, property_id)
    if not property_obj:
        return "unavailable"

    ptype = (property_obj.property_type or "").strip().lower()

    # Guesthouse/Farmhouse has one property-level inventory.
    if ptype in ("", "guesthouse"):
        approved_query = Booking.query.filter(
            Booking.property_id == property_id,
            Booking.status == "approved",
            Booking.check_in < check_out,
            Booking.check_out > check_in
        )
        if exclude_booking_id is not None:
            approved_query = approved_query.filter(Booking.id != exclude_booking_id)
        if approved_query.first():
            return "booked"

        pending_query = Booking.query.filter(
            Booking.property_id == property_id,
            Booking.status.in_(["pending", "availability_requested"]),
            Booking.check_in < check_out,
            Booking.check_out > check_in
        )
        if exclude_booking_id is not None:
            pending_query = pending_query.filter(Booking.id != exclude_booking_id)
        if pending_query.first():
            return "freezing"

        if PropertyBlockedDate.query.filter(
            PropertyBlockedDate.property_id == property_id,
            PropertyBlockedDate.block_date >= check_in,
            PropertyBlockedDate.block_date < check_out
        ).first():
            return "unavailable"

        return "available"

    # Multi-inventory properties use physical room/unit/flat availability.
    options = get_accommodation_options(property_obj)
    if not options:
        return "unavailable"

    # get_reserved_accommodation_counts includes pending requests too, so
    # calculate approved and pending quantities separately for correct state.
    def booking_counts(statuses):
        result = {}
        query = Booking.query.filter(
            Booking.property_id == property_id,
            Booking.status.in_(statuses),
            Booking.check_in < check_out,
            Booking.check_out > check_in
        )
        if exclude_booking_id is not None:
            query = query.filter(Booking.id != exclude_booking_id)

        for booking in query.all():
            for item in get_booking_accommodations(booking):
                key = inventory_base_key(property_obj, str(item.get("key", "")))
                try:
                    qty = int(item.get("quantity", 0) or 0)
                except (TypeError, ValueError):
                    qty = 0
                if key:
                    result[key] = result.get(key, 0) + max(0, qty)
        return result

    approved = booking_counts(["approved"])
    pending = booking_counts(["pending", "availability_requested"])
    blocked = get_inventory_blocked_counts(property_obj, check_in, check_out)

    # Calculate remaining guest capacity after selected categories of holds.
    def remaining_capacity(use_blocked=True, use_pending=False):
        total_capacity = 0

        for opt in options:
            key = str(opt["key"])
            try:
                count = int(opt.get("count", 0) or 0)
                max_guests = int(opt.get("max_guests", 0) or 0)
            except (TypeError, ValueError):
                continue

            used = int(approved.get(key, 0))

            if use_blocked:
                used += int(blocked.get(key, 0))

            if use_pending:
                used += int(pending.get(key, 0))

            available_units = max(0, count - used)
            total_capacity += available_units * max_guests

        return total_capacity

    requested_guests = max(1, int(guests or 1))

    # Approved bookings are permanent occupancy. If enough inventory remains
    # after approved bookings AND owner/Goinn blocks, the property is available
    # even when some rooms/units/flats are blocked.
    capacity_after_approved_only = remaining_capacity(
        use_blocked=False,
        use_pending=False
    )
    capacity_after_blocks = remaining_capacity(
        use_blocked=True,
        use_pending=False
    )

    if capacity_after_blocks >= requested_guests:
        return "available"

    # If approved bookings themselves consume the required capacity, the
    # public state is booked.
    if capacity_after_approved_only < requested_guests:
        return "booked"

    # Pending requests can temporarily consume the remaining inventory.
    capacity_after_pending = remaining_capacity(
        use_blocked=True,
        use_pending=True
    )
    if capacity_after_pending < requested_guests:
        return "freezing"

    # Approved bookings leave enough capacity, but blocked inventory removes
    # enough of it to prevent this request.
    return "unavailable"


def is_property_available(
    property_id,
    check_in,
    check_out,
    guests=None,
    exclude_booking_id=None
):
    return get_property_booking_state(
        property_id,
        check_in,
        check_out,
        guests=guests,
        exclude_booking_id=exclude_booking_id
    ) == "available"


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
    property_booking_states = {}
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

            # Release any expired 15-minute booking holds before
            # calculating the public state of the search results.
            expire_booking_holds()

            for property_obj in candidate_properties:

                # Property must have an admin-configured capacity.
                max_capacity = get_property_total_capacity(property_obj)
                if not max_capacity or search_guests > max_capacity:
                    continue

                # A valid price must exist for the selected
                # guest count, including group pricing.
                price = get_property_price(
                    property_obj,
                    search_guests
                )

                if price is None or price < 0:
                    continue

                # Show every approved property in the search
                # results. Do not hide properties just because
                # another user is booking them. Instead, expose
                # the state as Available / Freezing / Booked.
                property_booking_states[property_obj.id] = (
                    get_property_booking_state(
                        property_obj.id,
                        check_in,
                        check_out,
                        guests=search_guests
                    )
                )

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

        session["booking_search_location"] = (
            search_location
        )

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
        property_booking_states=property_booking_states,
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

@app.route("/property/<int:property_id>/availability-check")
def property_availability_check(property_id):
    property_obj = Property.query.get_or_404(property_id)
    check_in_text = request.args.get("check_in", "").strip()
    check_out_text = request.args.get("check_out", "").strip()
    guests = request.args.get("guests", type=int)

    try:
        check_in = datetime.strptime(check_in_text, "%Y-%m-%d").date()
        check_out = datetime.strptime(check_out_text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"available": False, "message": "Invalid dates."}, 400

    if check_out <= check_in:
        return {"available": False, "message": "Check-out must be after check-in."}, 400

    if guests is None or guests < 1:
        return {"available": False, "message": "Invalid guest count."}, 400

    if property_obj.max_guests and guests > property_obj.max_guests:
        return {"available": False, "message": f"Maximum guests is {property_obj.max_guests}."}

    if not is_property_available(
        property_obj.id,
        check_in,
        check_out,
        guests=guests
    ):
        return {"available": False, "message": "No availability for the selected dates."}

    return {"available": True}


# ==================================================
# BOOKING WHATSAPP HELPER
# ==================================================

def build_booking_whatsapp_url(booking):

    property_obj = booking.property

    selected_items = get_booking_accommodations(booking)
    accommodation_text = "\n".join(
        f"- {item.get('label', item.get('key', 'Accommodation'))} × {item.get('quantity', 1)}"
        for item in selected_items
    ) or "- Standard property booking"

    if not property_obj:
        return ""

    if property_obj.availability_type == "type3":

        whatsapp_contact = os.environ.get(
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
{booking.customer_name}

Contact:
{booking.customer_contact}

Email:
{booking.customer_email}

Check-in:
{booking.check_in.strftime("%d-%m-%Y")}

Check-out:
{booking.check_out.strftime("%d-%m-%Y")}

Number of Guests:
{booking.guests}

Selected Accommodation:
{accommodation_text}

Number of Nights:
{booking.nights}

Estimated Price Per Day:
₹{booking.price_per_day:.2f}

Estimated Total:
₹{booking.total_price:.2f}

Availability Request ID:
{booking.id}

Please contact the property owner and confirm availability.
"""

    else:

        owner = property_obj.owner

        whatsapp_contact = (
            owner.contact
            if owner and owner.contact
            else ""
        )

        message = f"""
Hello Goinn Property Owner,

I am interested in booking your property.

Property:
{property_obj.property_name}

Location:
{property_obj.location}

Customer Name:
{booking.customer_name}

Contact:
{booking.customer_contact}

Email:
{booking.customer_email}

Check-in:
{booking.check_in.strftime("%d-%m-%Y")}

Check-out:
{booking.check_out.strftime("%d-%m-%Y")}

Number of Guests:
{booking.guests}

Selected Accommodation:
{accommodation_text}

Number of Nights:
{booking.nights}

Price Per Day:
₹{booking.price_per_day:.2f}

Total:
₹{booking.total_price:.2f}

Booking ID:
{booking.id}

I would like to discuss/negotiate the final price and booking details.

Thank you.
"""

    encoded_message = urllib.parse.quote(message)

    whatsapp_number = (
        whatsapp_contact
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if whatsapp_number:
        return (
            "https://wa.me/"
            + whatsapp_number
            + "?text="
            + encoded_message
        )

    return "https://wa.me/?text=" + encoded_message


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

    # --------------------------------------------------
    # RESTORE THE EXACT SEARCH DATA FROM HOME
    # --------------------------------------------------
    # Prefer query-string values when present. The home page
    # also stores the completed search in session, so the flow
    # remains reliable when the user simply clicks View Property.
    search_location = request.args.get(
        "location",
        session.get("booking_search_location", "")
    ).strip()

    # --------------------------------------------------
    # EDIT DATES & GUESTS AVAILABILITY VALIDATION
    # --------------------------------------------------
    # When the user changes dates from the Property Details
    # page, do not replace the current selection unless the
    # newly selected dates are actually available.
    edit_error = request.args.get("edit_error", "").strip()
    edit_requested = request.args.get("edit_selection", "") == "1"

    requested_check_in = request.args.get("check_in", "").strip()
    requested_check_out = request.args.get("check_out", "").strip()
    requested_guests = request.args.get("guests", "").strip()

    if edit_requested and requested_check_in and requested_check_out:
        try:
            requested_in_date = datetime.strptime(
                requested_check_in, "%Y-%m-%d"
            ).date()
            requested_out_date = datetime.strptime(
                requested_check_out, "%Y-%m-%d"
            ).date()

            if requested_out_date <= requested_in_date:
                edit_error = "Check-out date must be after check-in date."
            else:
                # Expire old temporary holds before checking the new dates.
                expire_booking_holds()

                requested_state = get_property_booking_state(
                    property_obj.id,
                    requested_in_date,
                    requested_out_date
                )

                if requested_state != "available":
                    edit_error = (
                        "This property is booked for the selected dates. "
                        "Please choose different dates."
                    )
                elif (
                    property_obj.max_guests
                    and requested_guests
                    and int(requested_guests) > get_property_max_guests(property_obj)
                ):
                    edit_error = (
                        f"This property allows a maximum of "
                        f"{property_obj.max_guests} guests."
                    )
                else:
                    # Only now accept the edited values.
                    session["booking_search_location"] = search_location
                    session["booking_search_check_in"] = requested_check_in
                    session["booking_search_check_out"] = requested_check_out
                    session["booking_search_guests"] = requested_guests

        except (ValueError, TypeError):
            edit_error = "Please select valid check-in and check-out dates."

    if edit_requested and edit_error:
        # Keep the old selection when the new dates are unavailable.
        selected_check_in = session.get(
            "booking_search_check_in", ""
        ).strip()
        selected_check_out = session.get(
            "booking_search_check_out", ""
        ).strip()
        selected_guests = session.get(
            "booking_search_guests", ""
        ).strip()
    else:
        selected_check_in = request.args.get(
            "check_in",
            session.get("booking_search_check_in", "")
        ).strip()

        selected_check_out = request.args.get(
            "check_out",
            session.get("booking_search_check_out", "")
        ).strip()

        selected_guests = request.args.get(
            "guests",
            session.get("booking_search_guests", "")
        ).strip()

    selected_price = None
    selected_nights = None
    selected_total = None

    # Calculate the exact price for the guest count selected on Home.
    # This works for both individual and group pricing.
    if selected_guests:
        try:
            guest_count = int(selected_guests)
            if guest_count > 0:
                selected_price = get_property_price(
                    property_obj,
                    guest_count
                )
        except (TypeError, ValueError):
            selected_guests = ""

    if selected_check_in and selected_check_out:
        try:
            selected_check_in_date = datetime.strptime(
                selected_check_in,
                "%Y-%m-%d"
            ).date()
            selected_check_out_date = datetime.strptime(
                selected_check_out,
                "%Y-%m-%d"
            ).date()

            if selected_check_out_date > selected_check_in_date:
                selected_nights = (
                    selected_check_out_date - selected_check_in_date
                ).days

                if selected_price is not None:
                    selected_total = (
                        selected_price * selected_nights
                    )
        except ValueError:
            selected_check_in = ""
            selected_check_out = ""

    # --------------------------------------------------
    # EXPIRE OLD BOOKING HOLDS BEFORE DISPLAYING THE PROPERTY
    # --------------------------------------------------

    expire_booking_holds()

    # --------------------------------------------------
    # EXISTING ACTIVE BOOKING REQUEST
    # --------------------------------------------------

    booking_request = None
    booking_request_sent = False
    booking_whatsapp_url = ""

    if (
        current_user.is_authenticated
        and selected_check_in
        and selected_check_out
    ):
        try:
            selected_check_in_date = datetime.strptime(
                selected_check_in,
                "%Y-%m-%d"
            ).date()

            selected_check_out_date = datetime.strptime(
                selected_check_out,
                "%Y-%m-%d"
            ).date()

            booking_request = Booking.query.filter(
                Booking.user_id == current_user.id,
                Booking.property_id == property_obj.id,
                Booking.status.in_(
                    ["pending", "availability_requested"]
                ),
                Booking.check_in == selected_check_in_date,
                Booking.check_out == selected_check_out_date
            ).order_by(
                Booking.created_at.desc()
            ).first()

            if booking_request:
                booking_request_sent = True
                booking_whatsapp_url = build_booking_whatsapp_url(
                    booking_request
                )

        except ValueError:
            pass

    terms_error = request.args.get(
        "terms_error",
        ""
    ).strip()

    # Parse the saved amenities in the backend before rendering.
    # This avoids relying on Jinja JSON parsing in the user-facing page.
    public_amenities = get_property_amenities(property_obj)

    selected_booking_state = "available"
    if selected_check_in and selected_check_out:
        try:
            selected_booking_state = get_property_booking_state(
                property_obj.id,
                datetime.strptime(selected_check_in, "%Y-%m-%d").date(),
                datetime.strptime(selected_check_out, "%Y-%m-%d").date()
            )
        except ValueError:
            selected_booking_state = "available"

    # Build the accommodation selector with the REAL availability for
    # the dates selected on the search page. This prevents the page from
    # initially showing total inventory (for example "2 available") when
    # those rooms are blocked/booked for the selected dates.
    accommodation_options = get_accommodation_options(property_obj)
    if selected_check_in and selected_check_out and property_obj.property_type != "guesthouse":
        try:
            selector_check_in = datetime.strptime(
                selected_check_in, "%Y-%m-%d"
            ).date()
            selector_check_out = datetime.strptime(
                selected_check_out, "%Y-%m-%d"
            ).date()
            if selector_check_out > selector_check_in:
                accommodation_options = get_available_accommodation_options(
                    property_obj,
                    selector_check_in,
                    selector_check_out
                )
        except (ValueError, TypeError):
            pass

    return render_template(
        "property_details.html",
        property=property_obj,
        public_amenities=public_amenities,
        property_step_details=get_property_step_details(property_obj),
        type_pricing=get_type_pricing(property_obj),
        accommodation_options=accommodation_options,
        property_step_images=property_obj.step_images,
        search_location=search_location,
        selected_check_in=selected_check_in,
        selected_check_out=selected_check_out,
        selected_guests=selected_guests,
        selected_price=selected_price,
        selected_nights=selected_nights,
        selected_total=selected_total,
        booking_request=booking_request,
        booking_request_sent=booking_request_sent,
        booking_whatsapp_url=booking_whatsapp_url,
        selected_booking_state=selected_booking_state,
        terms_error=terms_error,
        edit_error=edit_error
    )


@app.route("/api/property/<int:property_id>/accommodations")
def property_accommodation_availability(property_id):
    property_obj = db.session.get(Property, property_id)
    if not property_obj or property_obj.status != "approved":
        return jsonify({"error": "Property not found"}), 404
    check_in_text = request.args.get("check_in", "").strip()
    check_out_text = request.args.get("check_out", "").strip()
    try:
        check_in = datetime.strptime(check_in_text, "%Y-%m-%d").date()
        check_out = datetime.strptime(check_out_text, "%Y-%m-%d").date()
        if check_out <= check_in:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid dates"}), 400
    expire_booking_holds()

    # Availability must include BOTH:
    #   1. rooms/units/flats held by active bookings
    #   2. physical inventory manually blocked in the calendar
    options = get_available_accommodation_options(
        property_obj,
        check_in,
        check_out
    )

    return jsonify({
        "property_type": property_obj.property_type,
        "options": options
    })


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

        # Show the configured accommodation units/rooms/flats on the
        # booking page. If dates are available, show their current
        # availability for those dates.
        accommodation_options = get_accommodation_options(property_obj)
        if (
            property_obj.property_type != "guesthouse"
            and booking_check_in
            and booking_check_out
        ):
            try:
                ci = datetime.strptime(booking_check_in, "%Y-%m-%d").date()
                co = datetime.strptime(booking_check_out, "%Y-%m-%d").date()
                if co > ci:
                    accommodation_options = get_available_accommodation_options(
                        property_obj, ci, co
                    )
            except ValueError:
                pass

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            selected_check_in=booking_check_in,
            selected_check_out=booking_check_out,
            selected_guests=booking_guests,
            accommodation_options=accommodation_options
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

    terms_accepted = (
        request.form.get(
            "accept_terms",
            ""
        ).strip().lower()
        == "yes"
    )

    # ==================================================
    # TERMS & CONDITIONS ACCEPTANCE
    # ==================================================

    if not property_obj.terms_conditions:

        return redirect(
            url_for(
                "property_details",
                property_id=property_obj.id,
                location=session.get(
                    "booking_search_location",
                    ""
                ),
                check_in=check_in_text,
                check_out=check_out_text,
                guests=guests_text,
                terms_error=(
                    "Terms & Conditions have not been "
                    "configured for this property. "
                    "Booking cannot continue."
                )
            )
        )

    if not terms_accepted:

        return redirect(
            url_for(
                "property_details",
                property_id=property_obj.id,
                location=session.get(
                    "booking_search_location",
                    ""
                ),
                check_in=check_in_text,
                check_out=check_out_text,
                guests=guests_text,
                terms_error=(
                    "Please accept the Terms & Conditions "
                    "before booking."
                )
            )
        )

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
    # DUPLICATE ACTIVE BOOKING REQUEST
    # ==================================================

    existing_request = Booking.query.filter(
        Booking.user_id == current_user.id,
        Booking.property_id == property_obj.id,
        Booking.status.in_(
            ["pending", "availability_requested"]
        ),
        Booking.check_in == check_in,
        Booking.check_out == check_out
    ).first()

    if existing_request:

        return redirect(
            url_for(
                "property_details",
                property_id=property_obj.id,
                location=session.get(
                    "booking_search_location",
                    ""
                ),
                check_in=check_in_text,
                check_out=check_out_text,
                guests=guests_text
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

    capacity_for_booking = (
        int(property_obj.max_guests or 0)
        if property_obj.property_type == "guesthouse"
        else get_property_total_capacity(property_obj)
    )

    if capacity_for_booking < 1:
        return render_template(
            "booking.html", property=property_obj, user=current_user,
            today=today_string, tomorrow=tomorrow_string,
            error="Guest capacity has not been configured for this property."
        )

    # Accommodation cart for resorts, hotels and service apartments.
    selected_accommodations_text = request.form.get("selected_accommodations", "[]").strip()
    try:
        selected_accommodations = json.loads(selected_accommodations_text or "[]")
    except Exception:
        selected_accommodations = []

    # Robust fallback: also read the actual accommodation quantity
    # controls submitted by the booking form. This prevents a stale or
    # empty hidden JSON field from losing the user's selection.
    if not isinstance(selected_accommodations, list) or not selected_accommodations:
        accommodation_keys = request.form.getlist("accommodation_key[]")
        accommodation_quantities = request.form.getlist("accommodation_qty[]")
        fallback_selection = []
        for key, quantity in zip(accommodation_keys, accommodation_quantities):
            key = str(key or "").strip()
            try:
                quantity = int(quantity or 0)
            except (TypeError, ValueError):
                quantity = 0
            if key and quantity > 0:
                fallback_selection.append({
                    "key": key,
                    "quantity": quantity
                })
        if fallback_selection:
            selected_accommodations = fallback_selection

    if property_obj.property_type == "guesthouse" and guests > int(property_obj.max_guests or 0):
        return render_template(
            "booking.html", property=property_obj, user=current_user, today=today_string,
            tomorrow=tomorrow_string, error=f"This property allows a maximum of {property_obj.max_guests} guests."
        )

    if property_obj.property_type != "guesthouse":
        # Rebuild the displayed inventory for the selected dates so that
        # validation errors do not render a booking page without the
        # accommodation controls.
        accommodation_options = get_available_accommodation_options(
            property_obj, check_in, check_out
        )
        ok, selection_error, normalized_selection, cart_price = validate_accommodation_selection(
            property_obj, selected_accommodations, guests, check_in, check_out
        )
        if not ok:
            if (
                not selected_accommodations
                and accommodation_options
                and not any(int(o.get("count", 0) or 0) > 0 for o in accommodation_options)
            ):
                selection_error = (
                    "No accommodation unit is available for the selected dates. "
                    "Please choose different dates or check the property calendar."
                )
            return render_template(
                "booking.html", property=property_obj, user=current_user, today=today_string,
                tomorrow=tomorrow_string, error=selection_error,
                selected_check_in=check_in_text,
                selected_check_out=check_out_text,
                selected_guests=guests_text,
                accommodation_options=accommodation_options
            )
    else:
        normalized_selection = []
        cart_price = get_property_price(property_obj, guests)

    # ==================================================
    # PROPERTY AVAILABILITY / 15-MINUTE FREEZE
    # ==================================================

    # All availability types use the same temporary hold.
    # An approved booking is permanently booked for these
    # dates, while another pending request freezes them for
    # up to 15 minutes.

    if property_obj.property_type == "guesthouse" and not is_property_available(
        property_obj.id, check_in, check_out, guests=guests
    ):

        return render_template(
            "booking.html",
            property=property_obj,
            user=current_user,
            today=today_string,
            tomorrow=tomorrow_string,
            error=(
                "These dates are currently unavailable or "
                "temporarily frozen because another booking "
                "request is being processed. Please try again "
                "later."
            )
        )

    # ==================================================
    # PRICE
    # ==================================================

    price_per_day = cart_price if property_obj.property_type != "guesthouse" else get_property_price(property_obj, guests)

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

        selected_accommodations=json.dumps(normalized_selection),

        status=booking_status
    )

    db.session.add(
        booking
    )

    db.session.commit()

    # ==================================================
    # WHATSAPP ROUTING
    # ==================================================

    whatsapp_url = build_booking_whatsapp_url(
        booking
    )

    return redirect(whatsapp_url)



# ==================================================
# BOOKING EMAIL HELPERS
# ==================================================

def _get_assistance_contacts_for_property(property_obj):
    """Return valid Step 9 assistance contacts for email rendering."""
    try:
        step_details = get_property_step_details(property_obj)
        contacts = step_details.get("assistance_contacts", [])
        if not isinstance(contacts, list):
            return []
        return [
            item for item in contacts
            if isinstance(item, dict)
            and str(item.get("name", "")).strip()
            and re.fullmatch(r"\d{10}", str(item.get("phone", "")).strip())
        ]
    except Exception:
        return []


def _booking_email_context(booking):
    """Build the same core booking information shown in My Bookings."""
    selected = get_booking_accommodations(booking)

    if not isinstance(selected, list):
        selected = []

    assistance = _get_assistance_contacts_for_property(
        booking.property
    )

    return {
        "booking": booking,
        "property": booking.property,
        "selected_accommodations": selected,
        "assistance_contacts": assistance,
    }


def _send_booking_email(booking, email_type, rejection_reason=None):
    """
    Send a booking confirmation/rejection through Gmail SMTP.

    Returns:
        (True, message) on success
        (False, message) on failure

    The caller changes the booking status only after this succeeds.
    """
    sender = app.config.get("GMAIL_ADDRESS", "").strip()
    app_password = app.config.get("GMAIL_APP_PASSWORD", "").strip()

    if not sender or not app_password:
        return (
            False,
            "Gmail is not configured. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in Render Environment Variables."
        )

    recipient = (booking.customer_email or "").strip()

    if not recipient:
        return (
            False,
            "The booking does not contain a customer email address."
        )

    context = _booking_email_context(booking)
    property_obj = context["property"]
    selected = context["selected_accommodations"]
    assistance = context["assistance_contacts"]

    if email_type == "approved":
        subject = f"Goinn Booking Confirmation - Booking #{booking.id}"
        heading = "Booking Confirmed"
        intro = (
            "Your booking has been approved and confirmed by Goinn. "
            "Please find your booking details below."
        )
    elif email_type == "rejected":
        subject = f"Goinn Booking Update - Booking #{booking.id}"
        heading = "Booking Request Rejected"
        intro = (
            "Your booking request could not be approved. "
            "Please find the booking details and the reason below."
        )
    else:
        return False, "Invalid booking email type."

    check_in = booking.check_in.strftime("%d-%m-%Y")
    check_out = booking.check_out.strftime("%d-%m-%Y")

    selected_text = "Not specified"
    if selected:
        parts = []
        for item in selected:
            if isinstance(item, dict):
                label = item.get("label", item.get("key", "Accommodation"))
                quantity = item.get("quantity", 1)
                parts.append(f"{label} × {quantity}")
            else:
                parts.append(str(item))
        selected_text = ", ".join(parts)

    assistance_text = "Not available"
    if assistance:
        assistance_text = "\n".join(
            f"{item.get('name', '').strip()} - {item.get('phone', '').strip()}"
            for item in assistance
        )

    reason = (rejection_reason or booking.rejection_reason or "").strip()

    plain_lines = [
        f"Hello {booking.customer_name},",
        "",
        intro,
        "",
        "BOOKING DETAILS",
        f"Booking ID: #{booking.id}",
        f"Property: {property_obj.property_name if property_obj else 'N/A'}",
        f"Location: {property_obj.location if property_obj else 'N/A'}",
        f"Address: {property_obj.property_address if property_obj else 'N/A'}",
        f"Check-in: {check_in}",
        f"Check-out: {check_out}",
        f"Guests: {booking.guests}",
        f"Selected Accommodation: {selected_text}",
        f"Nights: {booking.nights}",
        f"Price / Day: ₹{booking.price_per_day:.2f}",
        f"Total: ₹{booking.total_price:.2f}",
        f"Customer Name: {booking.customer_name}",
        f"Customer Contact: {booking.customer_contact}",
        f"Customer Email: {booking.customer_email}",
    ]

    if email_type == "approved":
        plain_lines.extend([
            "",
            "ASSISTANCE CONTACTS",
            assistance_text,
        ])
    else:
        plain_lines.extend([
            "",
            "REJECTION REASON",
            reason or "No reason was provided.",
        ])

    plain_lines.extend([
        "",
        "Thank you,",
        "Goinn",
    ])

    def row(label, value):
        return f"""
        <tr>
            <td style="padding:9px 12px;border:1px solid #e5e7eb;background:#f8fafc;font-weight:700;width:38%;">{html_escape(str(label))}</td>
            <td style="padding:9px 12px;border:1px solid #e5e7eb;">{html_escape(str(value))}</td>
        </tr>
        """

    selected_html = "<br>".join(
        html_escape(
            f"{item.get('label', item.get('key', 'Accommodation'))} × {item.get('quantity', 1)}"
        )
        for item in selected
        if isinstance(item, dict)
    ) or "Not specified"

    assistance_html = ""
    if email_type == "approved":
        if assistance:
            assistance_html = """
            <h3 style="margin:25px 0 10px;">Assistance Contacts</h3>
            <table style="border-collapse:collapse;width:100%;font-size:14px;">
            """
            for item in assistance:
                assistance_html += row(
                    item.get("name", "").strip(),
                    item.get("phone", "").strip()
                )
            assistance_html += "</table>"
        else:
            assistance_html = """
            <h3 style="margin:25px 0 10px;">Assistance Contacts</h3>
            <p style="color:#666;">No assistance contacts are currently available.</p>
            """
    else:
        assistance_html = f"""
        <h3 style="margin:25px 0 10px;">Rejection Reason</h3>
        <div style="padding:12px;background:#fff1f2;border:1px solid #fecdd3;border-radius:8px;color:#9f1239;white-space:pre-wrap;">
            {html_escape(reason or "No reason was provided.")}
        </div>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0;background:#f4f6f8;font-family:Arial,Helvetica,sans-serif;color:#202124;">
      <div style="max-width:700px;margin:25px auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
        <div style="background:#111827;color:#ffffff;padding:22px 25px;">
          <div style="font-size:24px;font-weight:800;">Goinn</div>
          <div style="font-size:18px;font-weight:700;margin-top:8px;">{html_escape(heading)}</div>
        </div>
        <div style="padding:25px;">
          <p>Hello {html_escape(booking.customer_name)},</p>
          <p style="line-height:1.6;">{html_escape(intro)}</p>

          <h3 style="margin:25px 0 10px;">Booking Details</h3>
          <table style="border-collapse:collapse;width:100%;font-size:14px;">
            {row("Booking ID", f"#{booking.id}")}
            {row("Status", "Approved" if email_type == "approved" else "Rejected")}
            {row("Property", property_obj.property_name if property_obj else "N/A")}
            {row("Location", property_obj.location if property_obj else "N/A")}
            {row("Address", property_obj.property_address if property_obj else "N/A")}
            {row("Check-in", check_in)}
            {row("Check-out", check_out)}
            {row("Guests", booking.guests)}
            {row("Selected Accommodation", selected_html)}
            {row("Nights", booking.nights)}
            {row("Price / Day", f"₹{booking.price_per_day:.2f}")}
            {row("Total", f"₹{booking.total_price:.2f}")}
            {row("Customer Name", booking.customer_name)}
            {row("Customer Contact", booking.customer_contact)}
            {row("Customer Email", booking.customer_email)}
          </table>

          {assistance_html}

          <p style="margin-top:28px;line-height:1.6;">
            Thank you,<br><strong>Goinn</strong>
          </p>
        </div>
      </div>
    </body>
    </html>
    """

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("\n".join(plain_lines))
    message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(
            app.config["GMAIL_SMTP_HOST"],
            app.config["GMAIL_SMTP_PORT"],
            timeout=30
        ) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(sender, app_password)
            smtp.send_message(message)

        return True, f"Email sent successfully to {recipient}."

    except Exception as error:
        app.logger.exception(
            "Booking email failed for booking #%s",
            booking.id
        )
        return (
            False,
            f"Unable to send email to {recipient}. "
            "The booking status was not changed."
        )


@app.route("/admin/booking/<int:booking_id>/approve", methods=["POST"])
@login_required
def approve_booking(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    if booking.status not in ["pending", "availability_requested"]:
        flash("This booking is no longer pending.", "info")
        return redirect(url_for("admin_dashboard", tab="bookings"))

    # Guesthouse/Farmhouse has one property-level inventory.
    if booking.property.property_type == "guesthouse":
        owner_block = PropertyBlockedDate.query.filter(
            PropertyBlockedDate.property_id == booking.property_id,
            PropertyBlockedDate.block_date >= booking.check_in,
            PropertyBlockedDate.block_date < booking.check_out
        ).first()

        if owner_block:
            flash(
                "This booking overlaps with dates blocked by the property owner. "
                "The booking cannot be approved.",
                "danger"
            )
            return redirect(url_for("admin_dashboard", tab="bookings"))

    existing_approved_booking = Booking.query.filter(
        Booking.id != booking.id,
        Booking.property_id == booking.property_id,
        Booking.status == "approved",
        Booking.check_in < booking.check_out,
        Booking.check_out > booking.check_in
    ).first()

    if (
        existing_approved_booking
        and booking.property.property_type == "guesthouse"
    ):
        flash(
            "Another approved booking already exists for these dates.",
            "danger"
        )
        return redirect(url_for("admin_dashboard", tab="bookings"))

    # Validate/allocate inventory before sending the confirmation email.
    if booking.property.property_type != "guesthouse":
        ok, message = allocate_booking_inventory(booking)
        if not ok:
            flash(message, "danger")
            return redirect(url_for("admin_dashboard", tab="bookings"))

    # IMPORTANT:
    # Do not change status to approved until the confirmation email succeeds.
    email_ok, email_message = _send_booking_email(
        booking,
        "approved"
    )

    if not email_ok:
        db.session.rollback()
        flash(
            f"Booking #{booking.id} was NOT approved because the confirmation email could not be sent. {email_message}",
            "danger"
        )
        return redirect(url_for("admin_dashboard", tab="bookings"))

    booking.status = "approved"

    if booking.property.property_type == "guesthouse":
        _block_booking_dates(
            booking,
            blocked_by="booking"
        )

    db.session.commit()

    flash(
        f"Booking #{booking.id} approved and confirmation email sent.",
        "success"
    )

    return redirect(
        url_for(
            "admin_dashboard",
            tab="bookings"
        )
    )


@app.route("/admin/booking/<int:booking_id>/reject", methods=["POST"])
@login_required
def reject_booking(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    if booking.status not in ["pending", "availability_requested"]:
        flash("This booking is no longer pending.", "info")
        return redirect(url_for("admin_dashboard", tab="bookings"))

    reason = request.form.get(
        "rejection_reason",
        ""
    ).strip()

    if not reason:
        flash(
            "A rejection reason is required.",
            "danger"
        )
        return redirect(
            url_for(
                "admin_dashboard",
                tab="bookings"
            )
        )

    # IMPORTANT:
    # Do not move the booking to rejected until the rejection email succeeds.
    email_ok, email_message = _send_booking_email(
        booking,
        "rejected",
        rejection_reason=reason[:2000]
    )

    if not email_ok:
        db.session.rollback()
        flash(
            f"Booking #{booking.id} was NOT rejected because the rejection email could not be sent. {email_message}",
            "danger"
        )
        return redirect(
            url_for(
                "admin_dashboard",
                tab="bookings"
            )
        )

    booking.status = "rejected"
    booking.rejection_reason = reason[:2000]

    db.session.commit()

    flash(
        f"Booking #{booking.id} rejected and email sent.",
        "info"
    )

    return redirect(
        url_for(
            "admin_dashboard",
            tab="bookings"
        )
    )


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
# EDIT USER PROFILE
# ==================================================

@app.route("/user/edit-profile", methods=["POST"])
@login_required
def edit_user_profile():

    name = request.form.get("name", "").strip()
    contact = request.form.get("contact", "").strip()

    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("user_dashboard"))

    clean_contact = (
        contact
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if not clean_contact or not clean_contact.isdigit():
        flash("Please enter a valid contact number.", "danger")
        return redirect(url_for("user_dashboard"))

    if len(clean_contact) < 10:
        flash("Contact number must contain at least 10 digits.", "danger")
        return redirect(url_for("user_dashboard"))

    current_user.name = name
    current_user.contact = clean_contact
    db.session.commit()

    flash("Profile updated successfully.", "success")
    return redirect(url_for("user_dashboard"))


# ==================================================
# USER BOOKING WHATSAPP
# ==================================================

@app.route("/user/booking/<int:booking_id>/whatsapp")
@login_required
def user_booking_whatsapp(booking_id):

    booking = Booking.query.filter_by(
        id=booking_id,
        user_id=current_user.id
    ).first_or_404()

    if booking.status == "cancelled":

        flash(
            "This booking request has already been released.",
            "info"
        )

        return redirect(
            url_for("user_dashboard")
        )

    return redirect(
        build_booking_whatsapp_url(booking)
    )


# ==================================================
# USER RELEASE BOOKING REQUEST
# ==================================================

@app.route(
    "/user/booking/<int:booking_id>/release",
    methods=["POST"]
)
@login_required
def user_release_booking(booking_id):

    booking = Booking.query.filter_by(
        id=booking_id,
        user_id=current_user.id
    ).first_or_404()

    if booking.status not in [
        "pending",
        "availability_requested"
    ]:

        flash(
            "This booking request can no longer be released.",
            "info"
        )

        return redirect(
            url_for("user_dashboard")
        )

    booking.status = "cancelled"

    db.session.commit()

    flash(
        "Booking request released. The property is available again for other users.",
        "success"
    )

    return redirect(
        url_for(
            "property_details",
            property_id=booking.property_id,
            location=booking.property.location,
            check_in=booking.check_in.isoformat(),
            check_out=booking.check_out.isoformat(),
            guests=booking.guests
        )
    )


# ==================================================
# USER BOOKING DETAILS
# ==================================================

@app.route("/user/booking/<int:booking_id>")
@login_required
def user_booking_details(booking_id):

    booking = Booking.query.filter_by(
        id=booking_id,
        user_id=current_user.id
    ).first_or_404()

    property_obj = booking.property

    amenities = []
    if property_obj.amenities_data:
        try:
            amenities = json.loads(property_obj.amenities_data)
        except (ValueError, TypeError, json.JSONDecodeError):
            amenities = []

    pricing = []
    if property_obj.pricing_data:
        try:
            pricing = json.loads(property_obj.pricing_data)
        except (ValueError, TypeError, json.JSONDecodeError):
            pricing = []

    approved_images = [
        image for image in property_obj.property_images
        if image.status == "approved"
    ]

    step_details = get_property_step_details(property_obj)
    assistance_contacts = step_details.get("assistance_contacts", [])
    if not isinstance(assistance_contacts, list):
        assistance_contacts = []

    return render_template(
        "user_booking_details.html",
        user=current_user,
        booking=booking,
        property=property_obj,
        amenities=amenities,
        pricing=pricing,
        approved_images=approved_images,
        assistance_contacts=assistance_contacts
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
# DELETE OWNER PROFILE / RETURN TO USER PROFILE
# ==================================================

@app.route("/owner/delete-profile", methods=["POST"])
@login_required
def delete_owner_profile():

    if current_user.role != "owner":
        if current_user.role == "admin":
            return redirect(url_for("admin_dashboard"))
        return "Access denied", 403

    owner_properties = Property.query.filter_by(
        owner_id=current_user.id
    ).all()

    try:
        # Remove properties and all property-specific data.
        # The user account itself is kept and changed back to a normal user.
        for property_obj in owner_properties:

            Booking.query.filter_by(
                property_id=property_obj.id
            ).delete(synchronize_session=False)

            PropertyBlockedDate.query.filter_by(
                property_id=property_obj.id
            ).delete(synchronize_session=False)

            PropertyImage.query.filter_by(
                property_id=property_obj.id
            ).delete(synchronize_session=False)

            db.session.delete(property_obj)

        current_user.role = "user"
        db.session.commit()

        flash(
            "Owner Profile deleted successfully. You can continue using Goinn as a user.",
            "success"
        )

    except Exception as error:
        db.session.rollback()
        print("DELETE OWNER PROFILE ERROR:", error)
        flash(
            "Unable to delete Owner Profile. Please try again.",
            "danger"
        )

    return redirect(url_for("user_dashboard"))


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

    property_obj = db.session.get(Property, image.property_id)
    target_tab = (
        "approved-properties"
        if property_obj and property_obj.status == "approved"
        else "pending-properties"
    )

    flash(f"Image {image.slot} approved.", "success")

    return redirect(
        url_for(
            "admin_dashboard",
            tab=target_tab
        )
    )


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

    property_obj = db.session.get(Property, image.property_id)
    target_tab = (
        "approved-properties"
        if property_obj and property_obj.status == "approved"
        else "pending-properties"
    )

    flash(
        f"Image {image.slot} was removed and the owner was asked to re-upload it.",
        "info"
    )

    return redirect(
        url_for(
            "admin_dashboard",
            tab=target_tab
        )
    )


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
    properties = Property.query.filter(Property.status == "approved").order_by(Property.created_at.desc()).all()
    selected_property = db.session.get(Property, property_id)
    if not selected_property or selected_property.status != "approved":
        return "Approved property not found", 404
    return render_template("admin_type2_calendar.html", properties=properties, selected_property=selected_property)


@app.route("/admin/property/<int:property_id>/calendar/data")
@login_required
def admin_type2_calendar_data(property_id):
    if not current_user.is_admin:
        return {"status":"error","message":"Unauthorized"},403
    year=request.args.get("year",type=int); month=request.args.get("month",type=int)
    if not year or not month or not 1 <= month <= 12:
        return {"status":"error","message":"Invalid calendar request."},400
    property_obj=db.session.get(Property,property_id)
    if not property_obj or property_obj.status != "approved":
        return {"status":"error","message":"Approved property not found."},404
    month_start=date(year,month,1); next_month=date(year+1,1,1) if month==12 else date(year,month+1,1)
    physical=get_physical_inventory(property_obj)
    blocks=InventoryBlockedDate.query.filter(InventoryBlockedDate.property_id==property_id,InventoryBlockedDate.block_date>=month_start,InventoryBlockedDate.block_date<next_month).all()
    block_map={}
    for b in blocks: block_map.setdefault(b.inventory_key,[]).append(b.block_date.isoformat())
    bookings=Booking.query.filter(Booking.property_id==property_id,Booking.status.in_(["pending","availability_requested","approved"]),Booking.check_in<next_month,Booking.check_out>month_start).order_by(Booking.check_in.asc()).all()
    inventory=[]
    for inv in physical:
        booked=[]; pending=[]
        for b in bookings:
            for item in get_booking_accommodations(b):
                key=str(item.get("key","")); qty=int(item.get("quantity",0) or 0)
                if key != inv["key"] and not (key==inv["base_key"] and qty>0 and property_obj.property_type != "resort"):
                    continue
                d=max(b.check_in,month_start); e=min(b.check_out,next_month)
                while d<e:
                    (booked if b.status=="approved" else pending).append(d.isoformat()); d+=timedelta(days=1)
        inventory.append({**inv,"blocked_dates":sorted(set(block_map.get(inv["key"],[]))),"booked_dates":sorted(set(booked)),"pending_dates":sorted(set(pending))})
    return {"status":"ok","property_id":property_id,"property_name":property_obj.property_name,"property_type":property_obj.property_type,"availability_type":property_obj.availability_type,"year":year,"month":month,"today":date.today().isoformat(),"inventory":inventory}


@app.route("/admin/property/<int:property_id>/calendar/block",methods=["POST"])
@login_required
def admin_type2_block_date(property_id):
    if not current_user.is_admin: return "Unauthorized",403
    property_obj=db.session.get(Property,property_id)
    if not property_obj or property_obj.status != "approved": return "Approved property not found",404
    text=request.form.get("block_date","").strip(); inventory_key=request.form.get("inventory_key","property").strip()
    try: block_date=datetime.strptime(text,"%Y-%m-%d").date()
    except ValueError: flash("Invalid date.","danger"); return redirect(url_for("admin_type2_calendar",property_id=property_id))
    if block_date<date.today(): flash("Past dates cannot be blocked.","danger"); return redirect(url_for("admin_type2_calendar",property_id=property_id))
    valid_keys={x["key"] for x in get_physical_inventory(property_obj)}
    if inventory_key not in valid_keys: flash("Invalid inventory selection.","danger"); return redirect(url_for("admin_type2_calendar",property_id=property_id))
    if property_obj.property_type=="guesthouse":
        conflict=Booking.query.filter(Booking.property_id==property_id,Booking.status.in_(["pending","approved","availability_requested"]),Booking.check_in<=block_date,Booking.check_out>block_date).first()
        if conflict: flash("This date has a booking and cannot be blocked.","danger"); return redirect(url_for("admin_type2_calendar",property_id=property_id))
    else:
        conflict=False
        for b in Booking.query.filter(Booking.property_id==property_id,Booking.status.in_(["pending","approved","availability_requested"]),Booking.check_in<=block_date,Booking.check_out>block_date).all():
            for item in get_booking_accommodations(b):
                key=str(item.get("key",""));
                if key==inventory_key or key==inventory_key.rsplit(":",1)[0]: conflict=True; break
            if conflict: break
        if conflict: flash("This inventory is involved in a booking on that date.","danger"); return redirect(url_for("admin_type2_calendar",property_id=property_id))
    existing=InventoryBlockedDate.query.filter_by(property_id=property_id,inventory_key=inventory_key,block_date=block_date).first()
    if existing: flash("This inventory is already blocked on that date.","info")
    else:
        db.session.add(InventoryBlockedDate(property_id=property_id,inventory_key=inventory_key,block_date=block_date,blocked_by="goinn")); db.session.commit(); flash("Inventory date blocked successfully.","success")
    return redirect(url_for("admin_type2_calendar",property_id=property_id))


@app.route("/admin/property/<int:property_id>/calendar/unblock",methods=["POST"])
@login_required
def admin_type2_unblock_date(property_id):
    if not current_user.is_admin: return "Unauthorized",403
    property_obj=db.session.get(Property,property_id)
    if not property_obj or property_obj.status != "approved": return "Approved property not found",404
    text=request.form.get("block_date","").strip(); inventory_key=request.form.get("inventory_key","property").strip()
    try: block_date=datetime.strptime(text,"%Y-%m-%d").date()
    except ValueError: flash("Invalid date.","danger"); return redirect(url_for("admin_type2_calendar",property_id=property_id))
    row=InventoryBlockedDate.query.filter_by(property_id=property_id,inventory_key=inventory_key,block_date=block_date,blocked_by="goinn").first()
    if not row: flash("This inventory date is not blocked by Goinn.","info")
    else: db.session.delete(row); db.session.commit(); flash("Inventory is available again.","success")
    return redirect(url_for("admin_type2_calendar",property_id=property_id))


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

    if property_obj.property_type == "guesthouse":
        if not is_property_available(
            property_obj.id,
            booking.check_in,
            booking.check_out,
            guests=booking.guests,
            exclude_booking_id=booking.id
        ):
            flash(
                "The requested dates are no longer available.",
                "danger"
            )
            return redirect(url_for("admin_dashboard", tab="bookings"))
    else:
        ok, message, normalized, _ = validate_accommodation_selection(
            property_obj,
            get_booking_accommodations(booking),
            booking.guests,
            booking.check_in,
            booking.check_out,
            exclude_booking_id=booking.id
        )

        if not ok:
            flash(
                message or "The selected accommodation is no longer available.",
                "danger"
            )
            return redirect(url_for("admin_dashboard", tab="bookings"))

        booking.selected_accommodations = json.dumps(normalized)

        ok, message = allocate_booking_inventory(booking)

        if not ok:
            flash(message, "danger")
            return redirect(url_for("admin_dashboard", tab="bookings"))

    # Only approve after the confirmation email succeeds.
    email_ok, email_message = _send_booking_email(
        booking,
        "approved"
    )

    if not email_ok:
        db.session.rollback()
        flash(
            f"Booking #{booking.id} was NOT approved because the confirmation email could not be sent. {email_message}",
            "danger"
        )
        return redirect(
            url_for(
                "admin_dashboard",
                tab="bookings"
            )
        )

    booking.status = "approved"

    if property_obj.property_type == "guesthouse":
        _block_booking_dates(
            booking,
            blocked_by="booking"
        )

    db.session.commit()

    flash(
        f"Type 3 booking #{booking.id} approved and confirmation email sent.",
        "success"
    )

    return redirect(
        url_for(
            "admin_dashboard",
            tab="bookings"
        )
    )


@app.route("/admin/availability/<int:booking_id>/not-available", methods=["POST"])
@login_required
def type3_not_available(booking_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)

    if booking.status != "availability_requested":
        flash("This availability request has already been handled.", "info")
        return redirect(url_for("admin_dashboard"))

    reason = request.form.get(
        "rejection_reason",
        ""
    ).strip()

    if not reason:
        flash(
            "A reason is required when marking a Type 3 request as not available.",
            "danger"
        )
        return redirect(
            url_for(
                "admin_dashboard",
                tab="bookings"
            )
        )

    # Only reject after the rejection email succeeds.
    email_ok, email_message = _send_booking_email(
        booking,
        "rejected",
        rejection_reason=reason[:2000]
    )

    if not email_ok:
        db.session.rollback()
        flash(
            f"Booking #{booking.id} was NOT rejected because the rejection email could not be sent. {email_message}",
            "danger"
        )
        return redirect(
            url_for(
                "admin_dashboard",
                tab="bookings"
            )
        )

    booking.status = "rejected"
    booking.rejection_reason = reason[:2000]

    db.session.commit()

    flash(
        f"Type 3 booking #{booking.id} rejected and email sent.",
        "info"
    )

    return redirect(
        url_for(
            "admin_dashboard",
            tab="bookings"
        )
    )


# ==================================================
# ADMIN PROPERTY BOOKINGS CALENDAR
# ==================================================

@app.route("/admin/property-bookings/data")
@login_required
def admin_property_bookings_data():

    if not current_user.is_admin:
        return {"status": "error", "message": "Unauthorized"}, 403

    property_id = request.args.get("property_id", type=int)
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    if not property_id or not year or not month or month < 1 or month > 12:
        return {"status": "error", "message": "Invalid calendar request."}, 400

    property_obj = db.session.get(Property, property_id)

    if not property_obj:
        return {"status": "error", "message": "Property not found."}, 404

    month_start = date(year, month, 1)

    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    blocked = PropertyBlockedDate.query.filter(
        PropertyBlockedDate.property_id == property_id,
        PropertyBlockedDate.block_date >= month_start,
        PropertyBlockedDate.block_date < next_month
    ).all()

    owner_blocked_dates = []
    goinn_blocked_dates = []

    for item in blocked:

        value = item.block_date.isoformat()

        if item.blocked_by == "owner":
            owner_blocked_dates.append(value)

        elif item.blocked_by in ["goinn", "booking"]:
            goinn_blocked_dates.append(value)

    booking_rows = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status.in_([
            "pending",
            "availability_requested",
            "approved"
        ]),
        Booking.check_in < next_month,
        Booking.check_out > month_start
    ).order_by(
        Booking.check_in.asc()
    ).all()

    approved_dates = set()
    pending_dates = set()
    bookings_data = []

    for booking in booking_rows:

        bookings_data.append({
            "id": booking.id,
            "customer_name": booking.customer_name,
            "customer_contact": booking.customer_contact,
            "guests": booking.guests,
            "check_in": booking.check_in.isoformat(),
            "check_out": booking.check_out.isoformat(),
            "status": booking.status,
            "total_price": booking.total_price
        })

        current_date = max(
            booking.check_in,
            month_start
        )

        booking_end = min(
            booking.check_out,
            next_month
        )

        while current_date < booking_end:

            if booking.status == "approved":
                approved_dates.add(current_date.isoformat())
            else:
                pending_dates.add(current_date.isoformat())

            current_date += timedelta(days=1)

    return {
        "status": "ok",
        "property_id": property_id,
        "property_name": property_obj.property_name,
        "location": property_obj.location,
        "year": year,
        "month": month,
        "today": date.today().isoformat(),
        "approved_booking_dates": sorted(approved_dates),
        "pending_booking_dates": sorted(pending_dates),
        "owner_blocked_dates": sorted(set(owner_blocked_dates)),
        "goinn_blocked_dates": sorted(set(goinn_blocked_dates)),
        "bookings": bookings_data
    }


# ==================================================
# OWNER CALENDAR
# ==================================================

@app.route("/owner/calendar")
@login_required
def owner_calendar():
    if current_user.role not in ["owner","admin"]: return "Access denied",403
    properties=Property.query.filter_by(owner_id=current_user.id).order_by(Property.created_at.desc()).all()
    selected_id=request.args.get("property_id",type=int)
    selected=Property.query.filter_by(id=selected_id,owner_id=current_user.id).first() if selected_id else None
    if not selected and properties: selected=properties[0]
    return render_template("owner_calendar.html",properties=properties,selected_property=selected)


@app.route("/owner/calendar/data")
@login_required
def owner_calendar_data():
    if current_user.role not in ["owner","admin"]: return {"status":"error","message":"Access denied"},403
    property_id=request.args.get("property_id",type=int); year=request.args.get("year",type=int); month=request.args.get("month",type=int)
    if not property_id or not year or not month or not 1<=month<=12: return {"status":"error","message":"Invalid calendar request."},400
    property_obj=Property.query.filter_by(id=property_id,owner_id=current_user.id).first()
    if not property_obj: return {"status":"error","message":"Property not found."},404
    month_start=date(year,month,1); next_month=date(year+1,1,1) if month==12 else date(year,month+1,1)
    physical=get_physical_inventory(property_obj)
    blocks=InventoryBlockedDate.query.filter(InventoryBlockedDate.property_id==property_id,InventoryBlockedDate.block_date>=month_start,InventoryBlockedDate.block_date<next_month,InventoryBlockedDate.blocked_by=="owner").all()
    block_map={}
    for b in blocks: block_map.setdefault(b.inventory_key,[]).append(b.block_date.isoformat())
    bookings=Booking.query.filter(Booking.property_id==property_id,Booking.status.in_(["pending","availability_requested","approved"]),Booking.check_in<next_month,Booking.check_out>month_start).all()
    inventory=[]
    for inv in physical:
        booked=[]; pending=[]
        for b in bookings:
            for item in get_booking_accommodations(b):
                key=str(item.get("key",""));
                if key != inv["key"]: continue
                d=max(b.check_in,month_start); e=min(b.check_out,next_month)
                while d<e: (booked if b.status=="approved" else pending).append(d.isoformat()); d+=timedelta(days=1)
        inventory.append({**inv,"blocked_dates":sorted(set(block_map.get(inv["key"],[]))),"booked_dates":sorted(set(booked)),"pending_dates":sorted(set(pending))})
    return {"status":"ok","property_id":property_id,"property_name":property_obj.property_name,"property_type":property_obj.property_type,"availability_type":property_obj.availability_type,"year":year,"month":month,"today":date.today().isoformat(),"inventory":inventory}


@app.route("/owner/calendar/block",methods=["POST"])
@login_required
def owner_block_date():
    if current_user.role not in ["owner","admin"]: return "Access denied",403
    property_id=request.form.get("property_id",type=int); inventory_key=request.form.get("inventory_key","property").strip(); text=request.form.get("block_date","").strip()
    property_obj=Property.query.filter_by(id=property_id,owner_id=current_user.id).first()
    if not property_obj: flash("Property not found.","danger"); return redirect(url_for("owner_calendar"))
    if property_obj.availability_type!="type1": flash("Only Type 1 properties can be managed by the owner.","danger"); return redirect(url_for("owner_calendar",property_id=property_id))
    try: block_date=datetime.strptime(text,"%Y-%m-%d").date()
    except ValueError: flash("Invalid date.","danger"); return redirect(url_for("owner_calendar",property_id=property_id))
    if block_date<date.today(): flash("Past dates cannot be blocked.","danger"); return redirect(url_for("owner_calendar",property_id=property_id))
    valid={x["key"] for x in get_physical_inventory(property_obj)}
    if inventory_key not in valid: flash("Invalid inventory selection.","danger"); return redirect(url_for("owner_calendar",property_id=property_id))
    if property_obj.property_type=="guesthouse":
        conflict=Booking.query.filter(Booking.property_id==property_id,Booking.status.in_(["pending","approved","availability_requested"]),Booking.check_in<=block_date,Booking.check_out>block_date).first()
    else:
        conflict=False
        for b in Booking.query.filter(Booking.property_id==property_id,Booking.status.in_(["pending","approved","availability_requested"]),Booking.check_in<=block_date,Booking.check_out>block_date).all():
            if any(str(i.get("key",""))==inventory_key for i in get_booking_accommodations(b)): conflict=True; break
    if conflict: flash("This inventory has a booking/request on that date and cannot be blocked.","danger"); return redirect(url_for("owner_calendar",property_id=property_id))
    if not InventoryBlockedDate.query.filter_by(property_id=property_id,inventory_key=inventory_key,block_date=block_date,blocked_by="owner").first():
        db.session.add(InventoryBlockedDate(property_id=property_id,inventory_key=inventory_key,block_date=block_date,blocked_by="owner")); db.session.commit(); flash("Inventory date blocked successfully.","success")
    else: flash("This inventory date is already blocked.","info")
    return redirect(url_for("owner_calendar",property_id=property_id))


@app.route("/owner/calendar/unblock",methods=["POST"])
@login_required
def owner_unblock_date():
    if current_user.role not in ["owner","admin"]: return "Access denied",403
    property_id=request.form.get("property_id",type=int); inventory_key=request.form.get("inventory_key","property").strip(); text=request.form.get("block_date","").strip()
    property_obj=Property.query.filter_by(id=property_id,owner_id=current_user.id).first()
    if not property_obj: flash("Property not found.","danger"); return redirect(url_for("owner_calendar"))
    if property_obj.availability_type!="type1": flash("Only Type 1 properties can be managed by the owner.","danger"); return redirect(url_for("owner_calendar",property_id=property_id))
    try: block_date=datetime.strptime(text,"%Y-%m-%d").date()
    except ValueError: flash("Invalid date.","danger"); return redirect(url_for("owner_calendar",property_id=property_id))
    row=InventoryBlockedDate.query.filter_by(property_id=property_id,inventory_key=inventory_key,block_date=block_date,blocked_by="owner").first()
    if row: db.session.delete(row); db.session.commit(); flash("Inventory is available again.","success")
    else: flash("This inventory date is not blocked by you.","info")
    return redirect(url_for("owner_calendar",property_id=property_id))


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
# ADMIN PROPERTY STEPS
# ==================================================

PROPERTY_TYPES = [
    ("guesthouse", "Guesthouse / Farmhouse"),
    ("resort", "Resort"),
    ("hotel", "Hotel"),
    ("service_apartment", "Service Apartment"),
]

HOTEL_ROOM_TYPES = [
    ("king_bed", "King Bed Rooms"),
    ("queen_bed", "Queen Bed Rooms"),
    ("twin_bed", "Twin Bed Rooms"),
    ("suite", "Suite Rooms"),
    ("superior", "Superior Rooms"),
    ("deluxe", "Deluxe Rooms"),
    ("family", "Family Rooms"),
    ("executive", "Executive Rooms"),
    ("studio", "Studio Rooms"),
    ("triple", "Triple Rooms"),
    ("accessible", "Accessible Rooms"),
]

FLAT_TYPES = [
    ("1bhk", "1 BHK"),
    ("2bhk", "2 BHK"),
    ("3bhk", "3 BHK"),
    ("4bhk", "4 BHK"),
    ("5bhk", "5 BHK"),
    ("6bhk", "6 BHK"),
]


def _admin_property_or_404(property_id):
    if not current_user.is_authenticated or not current_user.is_admin:
        return None, ("Unauthorized", 403)
    property_obj = db.session.get(Property, property_id)
    if not property_obj:
        return None, ("Property not found", 404)
    return property_obj, None


@app.route("/admin/property/<int:property_id>/steps")
@login_required
def property_steps(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error

    if property_obj.status not in {"pending", "approved"}:
        flash("Only pending or approved properties can be managed through Property Steps.", "info")
        return redirect(url_for("admin_dashboard", tab="pending-properties"))

    return render_template(
        "admin_property_steps.html",
        property=property_obj,
        property_types=PROPERTY_TYPES,
        hotel_room_types=HOTEL_ROOM_TYPES,
        flat_types=FLAT_TYPES,
        step_details=get_property_step_details(property_obj),
        type_pricing=get_type_pricing(property_obj),
        is_approved=(property_obj.status == "approved"),
    )


@app.route("/admin/property/<int:property_id>/steps/owner-type", methods=["POST"])
@login_required
def save_property_owner_type(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error
    value = request.form.get("availability_type", "").strip().lower()
    if value not in {"type1", "type2", "type3"}:
        flash("Please select Owner Type 1, Type 2 or Type 3.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))
    property_obj.availability_type = value
    db.session.commit()
    flash("Owner type saved.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


@app.route("/admin/property/<int:property_id>/steps/property-type", methods=["POST"])
@login_required
def save_property_type(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error
    value = request.form.get("property_type", "").strip().lower()
    valid = {x[0] for x in PROPERTY_TYPES}
    if value not in valid:
        flash("Please select a valid property type.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))
    property_obj.property_type = value
    # Type-specific details are reset when admin intentionally changes the type.
    property_obj.property_details_data = None
    property_obj.type_pricing_data = None
    db.session.query(PropertyStepImage).filter_by(property_id=property_id).delete()
    db.session.commit()
    flash("Property type saved. Continue to accommodation details.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


def _bool_choice(form, name):
    value = form.get(name, "").strip().lower()
    return value if value in {"yes", "no"} else None


@app.route("/admin/property/<int:property_id>/steps/details", methods=["POST"])
@login_required
def save_property_step_details(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error
    ptype = property_obj.property_type
    if ptype not in {x[0] for x in PROPERTY_TYPES}:
        flash("Select the property type first.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    if ptype == "guesthouse":
        try:
            bedrooms = int(request.form.get("bedrooms", "0"))
            washrooms = int(request.form.get("washrooms", "0"))
        except ValueError:
            flash("Bedrooms and washrooms must be valid numbers.", "danger")
            return redirect(url_for("property_steps", property_id=property_id))
        if bedrooms < 1 or washrooms < 1:
            flash("Bedrooms and washrooms must be at least 1.", "danger")
            return redirect(url_for("property_steps", property_id=property_id))
        pool = _bool_choice(request.form, "swimming_pool")
        kitchen = _bool_choice(request.form, "kitchen")
        if not pool or not kitchen:
            flash("Please select Yes or No for swimming pool and kitchen.", "danger")
            return redirect(url_for("property_steps", property_id=property_id))
        data = {"bedrooms": bedrooms, "washrooms": washrooms, "swimming_pool": pool, "kitchen": kitchen}

    elif ptype == "resort":
        try:
            units = int(request.form.get("unit_count", "0"))
        except ValueError:
            units = 0
        if units < 1 or units > 100:
            flash("Resort units must be between 1 and 100.", "danger")
            return redirect(url_for("property_steps", property_id=property_id))
        # First save can be used only to generate the requested number of units.
        # The admin then fills each unit in the next view.
        has_unit_fields = any(
            request.form.get(f"unit_{i}_bedrooms") is not None
            for i in range(1, units + 1)
        )
        data_units = []
        if not has_unit_fields:
            existing = get_property_step_details(property_obj).get("units", [])
            existing_by_unit = {int(x.get("unit")): x for x in existing if isinstance(x, dict) and x.get("unit")}
            for i in range(1, units + 1):
                old = existing_by_unit.get(i, {})
                data_units.append({
                    "unit": i,
                    "bedrooms": old.get("bedrooms", 1),
                    "washrooms": old.get("washrooms", 1),
                    "swimming_pool": old.get("swimming_pool", "no"),
                    "kitchen": old.get("kitchen", "no")
                })
        else:
            for i in range(1, units + 1):
                try:
                    bedrooms = int(request.form.get(f"unit_{i}_bedrooms", "0"))
                    washrooms = int(request.form.get(f"unit_{i}_washrooms", "0"))
                except ValueError:
                    bedrooms = washrooms = 0
                pool = _bool_choice(request.form, f"unit_{i}_swimming_pool")
                kitchen = _bool_choice(request.form, f"unit_{i}_kitchen")
                if bedrooms < 1 or washrooms < 1 or not pool or not kitchen:
                    flash(f"Complete bedrooms, washrooms, pool and kitchen for Unit {i}.", "danger")
                    return redirect(url_for("property_steps", property_id=property_id))
                data_units.append({"unit": i, "bedrooms": bedrooms, "washrooms": washrooms, "swimming_pool": pool, "kitchen": kitchen})
        data = {"unit_count": units, "units": data_units}

    elif ptype == "hotel":
        rooms = {}
        total = 0
        for key, label in HOTEL_ROOM_TYPES:
            try:
                count = int(request.form.get(f"room_{key}", "0"))
            except ValueError:
                count = 0
            if count < 0:
                flash(f"{label} cannot be negative.", "danger")
                return redirect(url_for("property_steps", property_id=property_id))
            rooms[key] = count
            total += count
        if total < 1:
            flash("Select at least one hotel room type.", "danger")
            return redirect(url_for("property_steps", property_id=property_id))
        data = {"room_types": rooms, "total_rooms": total}

    else:
        flats = {}
        total = 0
        for key, label in FLAT_TYPES:
            try:
                count = int(request.form.get(f"flat_{key}", "0"))
            except ValueError:
                count = 0
            if count < 0:
                flash(f"{label} cannot be negative.", "danger")
                return redirect(url_for("property_steps", property_id=property_id))
            flats[key] = count
            total += count
        if total < 1:
            flash("Select at least one flat type.", "danger")
            return redirect(url_for("property_steps", property_id=property_id))
        data = {"flat_types": flats, "total_flats": total}

    property_obj.property_details_data = json.dumps(data)
    db.session.commit()
    flash("Property accommodation details saved. Continue to pricing.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


@app.route("/admin/property/<int:property_id>/steps/upload-image", methods=["POST"])
@login_required
def upload_property_step_image(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error
    category = request.form.get("category", "").strip()
    target_key = request.form.get("target_key", "").strip()
    unit_index_text = request.form.get("unit_index", "").strip()
    try:
        unit_index = int(unit_index_text) if unit_index_text else None
    except ValueError:
        unit_index = None
    files = [f for f in request.files.getlist("images") if f and f.filename]
    if not files:
        flash("Please select at least one image.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/heic", "image/heif"}
    # Replace existing images for this exact target so repeated saves do not duplicate images.
    query = PropertyStepImage.query.filter_by(property_id=property_id, category=category, target_key=target_key)
    if unit_index is None:
        query = query.filter(PropertyStepImage.unit_index.is_(None))
    else:
        query = query.filter_by(unit_index=unit_index)
    query.delete(synchronize_session=False)
    for f in files:
        mime = f.mimetype or "application/octet-stream"
        if mime not in allowed:
            flash(f"Unsupported image type: {f.filename}", "danger")
            db.session.rollback()
            return redirect(url_for("property_steps", property_id=property_id))
        data = f.read()
        if not data:
            continue
        db.session.add(PropertyStepImage(
            property_id=property_id,
            category=category,
            target_key=target_key,
            unit_index=unit_index,
            filename=f.filename[:255],
            mime_type=mime,
            image_data=data,
        ))
    db.session.commit()
    flash("Images uploaded successfully.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


@app.route("/admin/property-step-image/<int:image_id>")
@login_required
def admin_property_step_image(image_id):
    image = db.session.get(PropertyStepImage, image_id)
    if not image or not current_user.is_admin:
        return "Not found", 404
    from flask import Response
    return Response(image.image_data, mimetype=image.mime_type, headers={"Content-Disposition": f'inline; filename="{image.filename}"'})


@app.route("/property-step-image/<int:image_id>")
def public_property_step_image(image_id):
    image = db.session.get(PropertyStepImage, image_id)
    if not image or not image.property or image.property.status != "approved":
        return "Not found", 404
    from flask import Response
    return Response(image.image_data, mimetype=image.mime_type, headers={"Content-Disposition": f'inline; filename="{image.filename}"'})


@app.route("/admin/property-step-image/<int:image_id>/delete", methods=["POST"])
@login_required
def delete_property_step_image(image_id):
    if not current_user.is_admin:
        return "Unauthorized", 403

    image = db.session.get(PropertyStepImage, image_id)
    if not image:
        flash("Accommodation image not found.", "danger")
        return redirect(url_for("admin_dashboard", tab="approved-properties"))

    property_id = image.property_id
    db.session.delete(image)
    db.session.commit()
    flash("Accommodation image deleted successfully.", "success")
    return redirect(url_for("property_steps", property_id=property_id))

@app.route("/admin/property/<int:property_id>/steps/type-pricing", methods=["POST"])
@login_required
def save_type_pricing(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error
    if not property_obj.property_type or not property_obj.property_details_data:
        flash("Complete the property type and accommodation details first.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))
    ptype = property_obj.property_type
    pricing = {}
    try:
        if ptype == "resort":
            details = get_property_step_details(property_obj)
            units = int(details.get("unit_count", 0))
            for i in range(1, units + 1):
                max_g = int(request.form.get(f"unit_{i}_max_guests", "0"))
                price = float(request.form.get(f"unit_{i}_price", "-1"))
                if max_g < 1 or price < 0:
                    raise ValueError(f"Complete valid pricing for Unit {i}.")
                pricing[str(i)] = {"max_guests": max_g, "price": price}
        elif ptype == "hotel":
            details = get_property_step_details(property_obj)
            for key, label in HOTEL_ROOM_TYPES:
                count = int(details.get("room_types", {}).get(key, 0))
                if count > 0:
                    max_g = int(request.form.get(f"room_{key}_max_guests", "0"))
                    price = float(request.form.get(f"room_{key}_price", "-1"))
                    if max_g < 1 or price < 0:
                        raise ValueError(f"Complete valid pricing for {label}.")
                    pricing[key] = {"count": count, "max_guests": max_g, "price": price}
        elif ptype == "service_apartment":
            details = get_property_step_details(property_obj)
            for key, label in FLAT_TYPES:
                count = int(details.get("flat_types", {}).get(key, 0))
                if count > 0:
                    max_g = int(request.form.get(f"flat_{key}_max_guests", "0"))
                    price = float(request.form.get(f"flat_{key}_price", "-1"))
                    if max_g < 1 or price < 0:
                        raise ValueError(f"Complete valid pricing for {label}.")
                    pricing[key] = {"count": count, "max_guests": max_g, "price": price}
        else:
            raise ValueError("Guesthouse/Farmhouse uses the existing pricing form.")
    except (ValueError, TypeError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    check_in_time = request.form.get("check_in_time", "").strip()
    check_out_time = request.form.get("check_out_time", "").strip()
    import re
    time_pattern = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    if not time_pattern.match(check_in_time) or not time_pattern.match(check_out_time):
        flash("Please select valid check-in and check-out timings.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    step_details = get_property_step_details(property_obj)
    step_details["check_in_time"] = check_in_time
    step_details["check_out_time"] = check_out_time
    property_obj.property_details_data = json.dumps(step_details)

    property_obj.type_pricing_data = json.dumps(pricing)
    db.session.commit()
    flash("Property-type pricing saved. You can now approve the property.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


@app.route("/admin/property/<int:property_id>/steps/location", methods=["POST"])
@login_required
def save_property_location(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error

    url_value = request.form.get("map_location_url", "").strip()
    lat_text = request.form.get("map_latitude", "").strip()
    lng_text = request.form.get("map_longitude", "").strip()

    try:
        latitude = float(lat_text) if lat_text else None
        longitude = float(lng_text) if lng_text else None
    except ValueError:
        flash("Latitude and longitude must be valid numbers.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    if latitude is None or longitude is None:
        flash("Please select the property location on the map.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    if not (-90 <= latitude <= 90):
        flash("Latitude must be between -90 and 90.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    if not (-180 <= longitude <= 180):
        flash("Longitude must be between -180 and 180.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    property_obj.map_latitude = latitude
    property_obj.map_longitude = longitude
    property_obj.map_location_url = url_value or (
        f"https://www.google.com/maps?q={latitude},{longitude}"
    )

    db.session.commit()
    flash("Property map location saved successfully.", "success")
    return redirect(url_for("property_steps", property_id=property_id))



@app.route("/admin/property/<int:property_id>/steps/assistance", methods=["POST"])
@login_required
def save_property_assistance(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error

    # Step 9 stores one or more assistance contacts inside the existing
    # property_details_data JSON so no separate database table is required.
    names = request.form.getlist("assistance_name[]")
    phones = request.form.getlist("assistance_phone[]")

    contacts = []
    if len(names) != len(phones):
        flash("Please provide a valid name and phone number for every assistance contact.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    for index, (name, phone) in enumerate(zip(names, phones), start=1):
        name = (name or "").strip()
        phone = (phone or "").strip()

        if not name and not phone:
            continue

        if not name:
            flash(f"Please enter the name for Assistance Contact {index}.", "danger")
            return redirect(url_for("property_steps", property_id=property_id))

        # Exactly 10 numeric digits are accepted.
        if not re.fullmatch(r"\d{10}", phone):
            flash(
                f"Assistance Contact {index} phone number must contain exactly 10 digits.",
                "danger"
            )
            return redirect(url_for("property_steps", property_id=property_id))

        contacts.append({
            "name": name[:120],
            "phone": phone
        })

    if not contacts:
        flash("Please add at least one assistance contact with a valid 10-digit phone number.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    # Remove duplicate name + phone combinations while preserving order.
    unique_contacts = []
    seen = set()
    for contact in contacts:
        key = (contact["name"].casefold(), contact["phone"])
        if key not in seen:
            seen.add(key)
            unique_contacts.append(contact)

    step_details = get_property_step_details(property_obj)
    step_details["assistance_contacts"] = unique_contacts
    property_obj.property_details_data = json.dumps(step_details, ensure_ascii=False)

    db.session.commit()
    flash("Assistance contacts saved successfully.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


@app.route("/admin/property/<int:property_id>/steps/approve", methods=["POST"])
@login_required
def approve_property_from_steps(property_id):
    property_obj, error = _admin_property_or_404(property_id)
    if error:
        return error
    if not property_obj.availability_type:
        flash("Owner Type must be selected.", "danger")
    elif not property_obj.amenities_data:
        flash("Amenities must be saved.", "danger")
    elif not property_obj.terms_conditions:
        flash("Terms & Conditions must be saved.", "danger")
    elif not property_obj.property_type:
        flash("Property Type must be selected.", "danger")
    elif not property_obj.property_details_data:
        flash("Accommodation details must be saved.", "danger")
    elif property_obj.property_type == "guesthouse" and (not property_obj.max_guests or not property_obj.pricing_data):
        flash("Guesthouse/Farmhouse pricing must be configured.", "danger")
    elif property_obj.property_type != "guesthouse" and not property_obj.type_pricing_data:
        flash("Property-type pricing must be configured.", "danger")
    elif property_obj.map_latitude is None or property_obj.map_longitude is None:
        flash("Property map location must be selected and saved.", "danger")
    elif not get_property_step_details(property_obj).get("assistance_contacts"):
        flash("At least one valid assistance contact must be saved in Step 9.", "danger")
    elif PropertyImage.query.filter_by(property_id=property_id, status="approved").count() < 1:
        flash("At least one owner image must be approved.", "danger")
    else:
        property_obj.status = "approved"
        property_obj.rejection_reason = None
        db.session.commit()
        flash("Property approved successfully.", "success")
        return redirect(url_for("admin_dashboard", tab="approved-properties"))
    return redirect(url_for("property_steps", property_id=property_id))


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
# ADMIN SAVE PROPERTY AMENITIES
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/amenities",
    methods=["POST"]
)
@login_required
def save_property_amenities(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    property_obj = db.session.get(Property, property_id)

    if not property_obj:
        return "Property not found", 404

    selected = request.form.getlist("amenities")

    # Keep only non-empty values and remove duplicates while preserving order.
    selected = list(dict.fromkeys(
        item.strip() for item in selected if item and item.strip()
    ))

    if not selected:
        flash("Select at least one amenity before saving.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    # Store selected names grouped by the categories used in the admin UI.
    category_order = [
        "Highlighted Amenities",
        "Basic Facilities",
        "General Services",
        "Health and wellness",
        "Transfers",
        "Room Amenities",
        "Food and Drinks",
        "Payment Services",
        "Safety and Security",
        "Media and technology",
        "Common Area",
        "Business Center and Conferences",
        "Other Facilities",
    ]

    amenities_catalog = {
        "Highlighted Amenities": ["Gym", "Restaurant", "Lounge (Shared)", "Bar"],
        "Basic Facilities": [
            "Smoking Rooms", "Room Service", "Power Backup", "Elevator/Lift",
            "Telephone", "Refrigerator", "Housekeeping", "Newspaper",
            "Washing Machine", "Umbrellas", "Smoke Detector (In Room,Lobby)",
            "Parking (Free)", "Laundry Service (Paid)",
            "Air Conditioning (Centralized)", "Kitchenette",
            "Wi-Fi (Free - Speed Suitable for working)",
        ],
        "General Services": [
            "Concierge", "Wheelchair", "Multilingual Staff", "Luggage Assistance",
            "Doctor on Call", "Wheelchair accessible (Wheelchair)",
        ],
        "Health and wellness": ["Gym", "Meditation Room", "First-aid Services", "Activity Centre"],
        "Transfers": ["Airport Transfers (Paid)", "Shuttle Service (Paid)"],
        "Room Amenities": [
            "Coffee Machine (Available in some rooms)", "Hairdryer", "Air Conditioning",
            "Dental Kit", "Iron/Ironing Board", "Work Desk",
            "Mineral Water - additional charge", "Minibar (Available in some rooms)",
            "Balcony (Private)",
            "Toiletries (Comb,Conditioner,Moisturiser,Premium,Shampoo,Shower Gel,Soap)",
        ],
        "Food and Drinks": ["Restaurant", "Bar", "Dining Area", "Kid's Menu"],
        "Payment Services": ["Currency Exchange"],
        "Safety and Security": ["CCTV", "Fire Extinguishers", "Security alarms", "Security Guard"],
        "Media and technology": ["TV (Cable,Flat screen)"],
        "Common Area": ["Lounge (Shared)", "Living Room", "Reception", "Balcony/Terrace"],
        "Business Center and Conferences": [
            "Printer", "Photocopying", "Business Centre", "Conference Room", "Banquet", "Fax Service"
        ],
        "Other Facilities": ["Cloak Room"],
    }

    saved = {}
    for category in category_order:
        values = [x for x in amenities_catalog[category] if x in selected]
        if values:
            saved[category] = values

    property_obj.amenities_data = json.dumps(saved, ensure_ascii=False)
    db.session.commit()

    flash("Amenities saved successfully. Continue to Terms & Conditions.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


# ==================================================
# ADMIN SAVE TERMS & CONDITIONS
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/terms",
    methods=["POST"]
)
@login_required
def save_property_terms(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    property_obj = db.session.get(Property, property_id)

    if not property_obj:
        return "Property not found", 404

    terms = request.form.get("terms_conditions", "").strip()

    if not terms:
        flash("Terms & Conditions cannot be empty.", "danger")
        return redirect(url_for("property_steps", property_id=property_id))

    property_obj.terms_conditions = terms[:20000]
    db.session.commit()

    flash("Terms & Conditions saved successfully. Continue to Availability & Pricing.", "success")
    return redirect(url_for("property_steps", property_id=property_id))


# ==================================================
# EDIT APPROVED PROPERTY AMENITIES
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/edit-amenities",
    methods=["POST"]
)
@login_required
def edit_approved_property_amenities(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    property_obj = db.session.get(Property, property_id)

    if not property_obj:
        return "Property not found", 404

    if property_obj.status != "approved":
        flash("Only approved properties can be edited from this section.", "danger")
        return redirect(url_for("admin_dashboard", tab="approved-properties"))

    selected = set(request.form.getlist("amenities"))

    category_order = [
        "Highlighted Amenities",
        "Basic Facilities",
        "General Services",
        "Health and wellness",
        "Transfers",
        "Room Amenities",
        "Food and Drinks",
        "Payment Services",
        "Safety and Security",
        "Media and technology",
        "Common Area",
        "Business Center and Conferences",
        "Other Facilities",
    ]

    amenities_catalog = {
        "Highlighted Amenities": ["Gym", "Restaurant", "Lounge (Shared)", "Bar"],
        "Basic Facilities": [
            "Smoking Rooms", "Room Service", "Power Backup", "Elevator/Lift",
            "Telephone", "Refrigerator", "Housekeeping", "Newspaper",
            "Washing Machine", "Umbrellas", "Smoke Detector (In Room,Lobby)",
            "Parking (Free)", "Laundry Service (Paid)",
            "Air Conditioning (Centralized)", "Kitchenette",
            "Wi-Fi (Free - Speed Suitable for working)",
        ],
        "General Services": [
            "Concierge", "Wheelchair", "Multilingual Staff", "Luggage Assistance",
            "Doctor on Call", "Wheelchair accessible (Wheelchair)",
        ],
        "Health and wellness": ["Gym", "Meditation Room", "First-aid Services", "Activity Centre"],
        "Transfers": ["Airport Transfers (Paid)", "Shuttle Service (Paid)"],
        "Room Amenities": [
            "Coffee Machine (Available in some rooms)", "Hairdryer", "Air Conditioning",
            "Dental Kit", "Iron/Ironing Board", "Work Desk",
            "Mineral Water - additional charge", "Minibar (Available in some rooms)",
            "Balcony (Private)",
            "Toiletries (Comb,Conditioner,Moisturiser,Premium,Shampoo,Shower Gel,Soap)",
        ],
        "Food and Drinks": ["Restaurant", "Bar", "Dining Area", "Kid's Menu"],
        "Payment Services": ["Currency Exchange"],
        "Safety and Security": ["CCTV", "Fire Extinguishers", "Security alarms", "Security Guard"],
        "Media and technology": ["TV (Cable,Flat screen)"],
        "Common Area": ["Lounge (Shared)", "Living Room", "Reception", "Balcony/Terrace"],
        "Business Center and Conferences": [
            "Printer", "Photocopying", "Business Centre", "Conference Room", "Banquet", "Fax Service"
        ],
        "Other Facilities": ["Cloak Room"],
    }

    saved = {}
    for category in category_order:
        values = [item for item in amenities_catalog[category] if item in selected]
        if values:
            saved[category] = values

    property_obj.amenities_data = json.dumps(saved, ensure_ascii=False)
    db.session.commit()

    flash("Amenities updated successfully.", "success")
    return redirect(url_for("admin_dashboard", tab="approved-properties"))


# ==================================================
# EDIT APPROVED PROPERTY TERMS & CONDITIONS
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/edit-terms",
    methods=["POST"]
)
@login_required
def edit_approved_property_terms(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    property_obj = db.session.get(Property, property_id)

    if not property_obj:
        return "Property not found", 404

    if property_obj.status != "approved":
        flash("Only approved properties can be edited from this section.", "danger")
        return redirect(url_for("admin_dashboard", tab="approved-properties"))

    terms = request.form.get("terms_conditions", "").strip()

    if not terms:
        flash("Terms & Conditions cannot be empty.", "danger")
        return redirect(url_for("admin_dashboard", tab="approved-properties"))

    property_obj.terms_conditions = terms[:20000]
    db.session.commit()

    flash("Terms & Conditions updated successfully.", "success")
    return redirect(url_for("admin_dashboard", tab="approved-properties"))


# ==================================================
# DELETE APPROVED PROPERTY
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/delete",
    methods=["POST"]
)
@login_required
def delete_approved_property(property_id):

    if not current_user.is_admin:
        return "Unauthorized", 403

    property_obj = db.session.get(Property, property_id)

    if not property_obj:
        flash("Property not found.", "danger")
        return redirect(url_for("admin_dashboard", tab="approved-properties"))

    if property_obj.status != "approved":
        flash("Only approved properties can be deleted from Approved Properties.", "danger")
        return redirect(url_for("admin_dashboard", tab="approved-properties"))

    property_name = property_obj.property_name

    try:
        # Remove all bookings associated with this property.
        Booking.query.filter_by(
            property_id=property_obj.id
        ).delete(synchronize_session=False)

        # Remove owner/Goinn/booking blocked dates.
        PropertyBlockedDate.query.filter_by(
            property_id=property_obj.id
        ).delete(synchronize_session=False)

        # Remove all stored property images.
        PropertyImage.query.filter_by(
            property_id=property_obj.id
        ).delete(synchronize_session=False)

        db.session.delete(property_obj)
        db.session.commit()

        flash(
            f"Property '{property_name}' was deleted successfully.",
            "success"
        )

    except Exception as error:
        db.session.rollback()
        print("DELETE APPROVED PROPERTY ERROR:", error)
        flash(
            "Unable to delete the property. Please check the application logs.",
            "danger"
        )

    return redirect(
        url_for("admin_dashboard", tab="approved-properties")
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

    if not property_obj.amenities_data:
        return "Amenities must be saved before availability and pricing.", 400

    if not property_obj.terms_conditions:
        return "Terms & Conditions must be saved before availability and pricing.", 400

    pricing_method = request.form.get(
        "pricing_method",
        ""
    ).strip().lower()

    availability_type = request.form.get(
        "availability_type",
        "type1"
    ).strip().lower()

    workflow = request.form.get("workflow", "").strip().lower()

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
        flash(
            "Please select Individual or Group pricing.",
            "danger"
        )
        return redirect(
            url_for(
                "property_steps",
                property_id=property_id
            )
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

    # --------------------------------------------------
    # CHECK-IN / CHECK-OUT TIMINGS
    # --------------------------------------------------
    check_in_time = request.form.get("check_in_time", "").strip()
    check_out_time = request.form.get("check_out_time", "").strip()

    import re
    time_pattern = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    if not time_pattern.match(check_in_time) or not time_pattern.match(check_out_time):
        flash(
            "Please select valid check-in and check-out timings.",
            "danger"
        )
        return redirect(
            url_for(
                "property_steps",
                property_id=property_id
            )
        )

    step_details = get_property_step_details(property_obj)
    step_details["check_in_time"] = check_in_time
    step_details["check_out_time"] = check_out_time
    property_obj.property_details_data = json.dumps(step_details)

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

    if workflow == "steps":
        db.session.commit()
        flash("Guesthouse/Farmhouse pricing saved. Continue to the final approval step.", "success")
        return redirect(url_for("property_steps", property_id=property_id))

    if approved_image_count < 1:
        property_obj.status = "pending"
        db.session.commit()
        flash(
            "Pricing saved, but the property remains Pending. Admin must approve at least one property image before the property can go live.",
            "info"
        )
        return redirect(
            url_for(
                "admin_dashboard",
                tab="pending-properties"
            )
        )

    property_obj.status = "approved"
    property_obj.rejection_reason = None

    db.session.commit()

    flash("Pricing saved and property approved successfully.", "success")

    return redirect(
        url_for(
            "admin_dashboard",
            tab="approved-properties"
        )
    )


# ==================================================
# ADMIN EDIT PROPERTY DETAILS
# ==================================================

@app.route(
    "/admin/property/<int:property_id>/edit-details",
    methods=["POST"]
)
@login_required
def admin_edit_property_details(property_id):

    if current_user.role != "admin":
        return "Access denied", 403

    property_obj = db.session.get(
        Property,
        property_id
    )

    if not property_obj:
        return "Property not found", 404

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
        return "Property name is required.", 400

    if not property_address:
        return "Property address is required.", 400

    if not location:
        return "Location is required.", 400

    property_obj.property_name = property_name
    property_obj.property_address = property_address
    property_obj.location = location

    db.session.commit()

    flash(
        "Property details updated successfully.",
        "success"
    )

    return redirect(
        url_for(
            "admin_dashboard",
            tab="approved-properties"
        )
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

    if not property_obj.amenities_data:
        return "Amenities must be saved before approval.", 400

    if not property_obj.terms_conditions:
        return "Terms & Conditions must be saved before approval.", 400

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

    approved_image_count = PropertyImage.query.filter_by(
        property_id=property_obj.id,
        status="approved"
    ).count()

    if approved_image_count < 1:
        return (
            "At least one property image must be approved "
            "before the property can be approved.",
            400
        )

    property_obj.status = "approved"
    property_obj.rejection_reason = None

    db.session.commit()

    return redirect(
        url_for(
            "admin_dashboard",
            tab="approved-properties"
        )
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

    reason = request.form.get(
        "reason",
        ""
    ).strip()

    if not reason:
        return (
            "A rejection reason is required.",
            400
        )

    property_obj.status = "rejected"
    property_obj.rejection_reason = reason[:2000]

    db.session.commit()

    flash(
        "Property rejected and the reason was saved.",
        "info"
    )

    return redirect(
        url_for(
            "admin_dashboard",
            tab="rejected-properties"
        )
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

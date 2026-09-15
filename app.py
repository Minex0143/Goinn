from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "development-secret"
)

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


class Test(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )


@app.route("/")
def home():

    return """
    <h1>Goinn</h1>

    <p>Goinn property booking platform is running.</p>

    <p>Database connection is configured.</p>
    """


@app.route("/health")
def health():

    return {
        "status": "ok",
        "application": "Goinn"
    }


@app.route("/database-test")
def database_test():

    try:

        with app.app_context():

            db.create_all()

            test = Test(
                name="Goinn Database Test"
            )

            db.session.add(test)

            db.session.commit()

            count = Test.query.count()

        return {
            "status": "success",
            "database": "connected",
            "records": count
        }

    except Exception as error:

        return {
            "status": "error",
            "message": str(error)
        }, 500


if __name__ == "__main__":

    app.run()

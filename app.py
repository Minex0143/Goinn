from flask import Flask

app = Flask(__name__)

app.config["SECRET_KEY"] = "change-this-later"


@app.route("/")
def home():
    return """
    <h1>Welcome to Goinn</h1>
    <p>Goinn property booking platform is running.</p>
    """


@app.route("/health")
def health():
    return {
        "status": "ok",
        "application": "Goinn"
    }


if __name__ == "__main__":
    app.run()

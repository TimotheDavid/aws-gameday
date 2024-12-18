import datetime
import os
import platform
import subprocess
from io import BytesIO

import boto3
from botocore.exceptions import ClientError
from flask import Flask, abort, request, send_file
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func, text
from util import configure_logger, get_db_endpoint, run_migrations

arch = platform.uname().machine
if arch == "x86_64":
    binary_name = "secret_sauce_amd64"
elif arch == "aarch64":
    binary_name = "secret_sauce_arm64"
else:
    print(f"Unsupported architecture: {arch}")
    exit(1)

SECRET_SAUCE_BINARY = os.path.join(
    os.path.abspath(os.path.dirname(__file__)), binary_name
)

environment = os.getenv("ENVIRONMENT", "prod")

postgres_user = os.environ["POSTGRES_USER"]
postgres_password = os.environ["POSTGRES_PASSWORD"]
postgres_port = os.environ["POSTGRES_PORT"]
postgres_db_name = os.environ["POSTGRES_DB_NAME"]
postgres_host = os.getenv("POSTGRES_HOST") or get_db_endpoint()

s3_bucket = os.environ["IMAGES_BUCKET"]
s3_prefix = os.environ["IMAGES_BUCKET_PREFIX"]

s3_client = boto3.client("s3")

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db_name}"
)
db = SQLAlchemy(app)
migrate = Migrate(app, db)

configure_logger(app, environment)
run_migrations(app)


@app.route("/unicorn", methods=["POST"])
def hire_unicorn():
    try:
        request_data = request.get_json(force=True)
        app.logger.info(f"Processing request with request data: {request_data}")
        request_id = request_data["request_id"]
        args = (SECRET_SAUCE_BINARY, request_id)
        popen = subprocess.Popen(args, stdout=subprocess.PIPE)
        popen.wait()
        raw_output = popen.stdout.read()
        signed_request_id = raw_output.decode().strip()
    except Exception as e:
        app.logger.error(f"Failed to process request: {e}")
        return abort(400)

    try:
        app.logger.debug("Saving request data to DB")
        req = Request(id=request_id, received_at=datetime.datetime.now())
        db.session.add(req)
        db.session.commit()
    except IntegrityError:
        app.logger.info(f"Duplicate request received: {request_id}")
        return abort(400)
    except Exception as e:
        app.logger.error(f"Failed to process request: {e}")
        return abort(500)

    return {
        "message": "Successfully hired unicorn",
        "request_id": request_id,
        "signature": signed_request_id,
    }, 200


@app.route("/gallery", methods=["GET"])
def serve_unicorn_image():
    unicorn_name = request.args.get("unicorn_name")
    if not unicorn_name:
        return {"message": "Provide the `unicorn_name` querystring"}, 400

    prefix = f"{s3_prefix}{unicorn_name}.png"
    app.logger.info(f"Retrieving unicorn image from {prefix}")
    try:
        s3_object = s3_client.get_object(Bucket=s3_bucket, Key=prefix)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return {"message": "Provide a valid unicorn name"}, 400
        else:
            app.logger.error(f"Failed to serve unicorn image: {e}")
            return abort(500)
    else:
        data = BytesIO(s3_object["Body"].read())

    return send_file(data, mimetype="image/jpeg")


@app.route("/healthcheck", methods=["GET"])
def healthcheck():
    app.logger.debug(f"Responding to healthcheck")
    db.session.execute(text("SELECT 1"))
    return "ok", "200"


class Request(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    received_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

import logging

import boto3
from flask_migrate import upgrade

ssm = boto3.client("ssm")
DEFAULT_LOG_LEVEL = logging.DEBUG


def get_db_endpoint():
    response = ssm.get_parameter(Name="/webserver/db_endpoint", WithDecryption=True)
    db_endpoint = response["Parameter"]["Value"]
    return db_endpoint


def configure_logger(app, environment):
    try:
        response = ssm.get_parameter(Name="/webserver/log_level", WithDecryption=True)
        log_level = response["Parameter"]["Value"]
    except Exception as e:
        app.logger.error(
            f"Failed to set log_level, setting to default: {logging.getLevelName(DEFAULT_LOG_LEVEL)}",
            e,
        )
        log_level = DEFAULT_LOG_LEVEL

    if environment == "local":
        handler = logging.StreamHandler()
    else:
        handler = logging.FileHandler("/var/log/flask_app.log")

    formatter = logging.Formatter(
        '{"time":"%(asctime)s", "name": "%(name)s", "level": "%(levelname)s", "message": "%(message)s"}'
    )
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

    try:
        app.logger.setLevel(log_level)
    except ValueError as e:
        app.logger.error(f"Failed to set log level to '{log_level}':", e)
        app.logger.setLevel(DEFAULT_LOG_LEVEL)

    app.logger.info(f"Configured log level to {logging.getLevelName(app.logger.level)}")


def run_migrations(app):
    app.logger.info("Applying DB migrations")
    with app.app_context():
        upgrade()

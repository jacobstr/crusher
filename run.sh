#!/bin/bash

# This should export your SLACK_API_KEY.
. ~/.private/slack

# Generic flask app startup.
. venv/bin/activate
export FLASK_APP=app.py
python -m flask run

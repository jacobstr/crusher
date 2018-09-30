#!/bin/bash

# This should export your SLACK_API_KEY.
source ~/.private/slack

# Generic flask app startup.
source venv/bin/activate
export FLASK_APP=app.py
python -m flask run

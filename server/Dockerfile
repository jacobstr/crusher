FROM python:2.7-stretch

COPY requirements.txt /tmp/

RUN pip install -r /tmp/requirements.txt

WORKDIR /home/crusher

COPY app.py .
ENV FLASK_APP=/home/crusher/app.py
CMD [ "python", "-m", "flask", "run", "--host",  "0.0.0.0"]

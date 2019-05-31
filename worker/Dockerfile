FROM python:3.7.3-stretch

COPY requirements.txt /tmp/

RUN pip install -r /tmp/requirements.txt

RUN useradd --create-home reserver
WORKDIR /home/reserver
USER reserver

COPY app.py .

CMD [ "python", "/home/reserver/app.py" ]

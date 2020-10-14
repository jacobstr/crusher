FROM python:3.7

COPY requirements.txt /tmp/

RUN pip install -r /tmp/requirements.txt

WORKDIR /home/crusher

COPY app.py .

CMD [ "python", "/home/crusher/app.py" ]

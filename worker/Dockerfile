FROM python:2.7

COPY requirements.txt /tmp/

RUN pip install -r /tmp/requirements.txt

RUN useradd --create-home crusher
WORKDIR /home/crusher
USER crusher

COPY app.py .

CMD [ "python", "/home/crusher/app.py" ]

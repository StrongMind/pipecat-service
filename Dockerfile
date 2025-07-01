FROM python:3.12-slim
WORKDIR /app
RUN apt update && apt install -y libopenblas-dev libresample1 libresample-dev && apt clean
COPY ./base_requirements.txt /app/base_requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/base_requirements.txt
COPY ./app.py ./waiting_server.py /app/
ARG VERSION
ENV IMAGE_VERSION=$VERSION
CMD ["sh", "-c", "if [ -f /app/pre-app.sh ]; then sh /app/pre-app.sh; fi && exec python app.py"]

RUN python --version

COPY ./requirements.txt requirements.txt

RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY ./bot.py bot.py
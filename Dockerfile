FROM dailyco/pipecat-base:latest

COPY ./requirements.txt requirements.txt
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY ./bot.py bot.py
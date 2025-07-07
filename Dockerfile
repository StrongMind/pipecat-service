FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt update && apt install -y \
    libopenblas-dev \
    libresample1 \
    libresample-dev \
    git \
    && apt clean

# Copy and install base requirements
COPY ./base_requirements.txt /app/base_requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/base_requirements.txt

# Copy and install project requirements
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

# Copy all necessary Python files
COPY ./server.py ./runner.py ./waiting_server.py ./bot-nova.py /app/

# Copy assets directory (needed for robot animations)
COPY ./assets /app/assets

# Set version environment variable
ARG VERSION
ENV IMAGE_VERSION=$VERSION

# Start the server
CMD ["sh", "-c", "if [ -f /app/pre-app.sh ]; then sh /app/pre-app.sh; fi && exec python server.py"]
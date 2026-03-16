ARG BUILD_FROM="ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21"
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    mariadb-connector-c \
    mariadb-connector-c-dev \
    libffi-dev \
    openssl-dev \
    curl \
    python3-dev

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir greenlet==3.1.1 \
 && pip3 install --no-cache-dir -r requirements.txt

COPY app/      ./app/
COPY alembic/  ./alembic/
COPY alembic.ini .

COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8080
CMD ["/run.sh"]

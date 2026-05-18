FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema para lxml y cryptography
RUN apt-get update && apt-get install -y --no-install-recommends libxml2 libxslt1.1 libssl3 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
# Habilita el proveedor legacy de OpenSSL 3.x para certificados SII
# (RC2-40, 3DES+SHA1 usados por E-CertChile y ACEPTA)
ENV OPENSSL_CONF=/app/openssl_legacy.cnf

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]

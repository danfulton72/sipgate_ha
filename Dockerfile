FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py .

RUN useradd -u 10001 -r -s /usr/sbin/nologin bridge
USER bridge

EXPOSE 8080
# One worker is plenty; the handlers are async and do almost no work.
CMD ["uvicorn", "bridge:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

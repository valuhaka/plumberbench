FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pillow==12.3.0 fastmcp==4.2.0

ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY server.py .
EXPOSE 8000
CMD ["python", "server.py"]

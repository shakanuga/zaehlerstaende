FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Europe/Berlin
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY zaehler ./zaehler
COPY static ./static
COPY run.py .
RUN useradd -u 99 -g 100 -M -s /usr/sbin/nologin zaehler || true
USER 99:100
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8080/api/state',timeout=4)"
CMD ["python", "run.py"]

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 4000

# Run with a production WSGI server (expects HOMEBOX_* env vars at runtime).
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:4000", "homebox_labels_web:create_app_from_env()"]

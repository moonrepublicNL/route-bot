# Gebruik een lichte Python image
FROM python:3.11-slim

# Werkdirectory in de container
WORKDIR /app

# Dependencies installeren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code kopiëren
COPY . .

ENV PYTHONUNBUFFERED=1

# --- FIX: WERKERS NAAR 1 (OOM FIX) en TIMEOUT NAAR 120s ---
CMD gunicorn -w 1 --timeout 120 -b 0.0.0.0:$PORT server:app
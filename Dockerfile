FROM python:3.11-slim

# Werkdirectory in de container
WORKDIR /app

# Dependencies installeren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code kopiëren
COPY . .

ENV PYTHONUNBUFFERED=1

CMD gunicorn -w 2 -b 0.0.0.0:$PORT server:app
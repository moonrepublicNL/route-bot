FROM python:3.11-slim

# Werkdirectory in de container
WORKDIR /app

# Dependencies installeren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code kopiëren
COPY . .

ENV PYTHONUNBUFFERED=1

# Start de Flask-app (server.py gebruikt zelf de PORT env var)
CMD ["python", "server.py"]

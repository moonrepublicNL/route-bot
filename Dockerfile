# Gebruik een lichte Python image
FROM python:3.9-slim

# Zet de werkmap in de container
WORKDIR /app

# Kopieer eerst requirements (voor caching snelheid)
COPY requirements.txt .

# Installeer dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer nu pas de rest van je code
COPY . .

# Timeout verhogen naar 120 seconden voor OpenAI requests
CMD gunicorn -w 2 --timeout 120 -b 0.0.0.0:$PORT server:app
```

#### Stap 2: Uploaden naar GitHub

Voer deze commando's uit in je terminal:

```bash
git add Dockerfile
git commit -m "Increase Gunicorn timeout to 120s because AI is slow"
git push origin main
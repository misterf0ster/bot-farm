FROM python:3.11-slim

RUN apt-get update && apt-get install -y wget curl gnupg libnss3 libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libxss1 libpangocairo-1.0-0 libgtk-3-0 libxshmfence1 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright asyncpg
RUN playwright install chromium

WORKDIR /app

COPY . .

RUN mkdir -p logs sessions

CMD ["python3", "bot.py"]

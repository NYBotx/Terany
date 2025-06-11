FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

ENV BOT_TOKEN=7735683292:AAFWqSYDi45wPOlRxoh7h9s9eACaCslIwD0

CMD ["python", "main.py"]

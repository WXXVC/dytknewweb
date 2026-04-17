FROM python:3.12-slim

WORKDIR /app/NEWWEB/backend

COPY requirements.txt /app/requirements.txt
COPY NEWWEB/backend/requirements.txt /app/NEWWEB/backend/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

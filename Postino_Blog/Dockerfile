# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 1) Install Python deps only
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2) Copy your code in
COPY ./src ./src

# 3) Make sure uvicorn can find your app
ENV PYTHONPATH=/app/src

# 4) Run the app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

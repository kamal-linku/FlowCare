FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/ ./
COPY ml/ /app/ml/
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

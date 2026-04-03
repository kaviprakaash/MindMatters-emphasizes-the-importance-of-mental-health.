# Run with docker compose (see docker-compose.yml) so Ollama and this app share a network.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV OLLAMA_BASE_URL=http://ollama:11434
EXPOSE 8000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "1"]

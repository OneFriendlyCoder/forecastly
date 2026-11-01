FROM python:3.11-slim
COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd app
USER app
COPY services/api/main.py .
ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

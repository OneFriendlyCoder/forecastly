FROM python:3.11-slim
WORKDIR /app
COPY services/deal-state/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd app
USER app
COPY schemas schemas
COPY services/deal-state services/deal-state
ENTRYPOINT ["python", "-u", "services/deal-state/main.py"]

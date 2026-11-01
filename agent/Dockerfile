FROM python:3.11-slim
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd app
USER app
COPY agent.py llm.py tools.py server.py index_playbook.py ./
COPY playbook playbook
ENTRYPOINT ["python", "-u", "server.py"]

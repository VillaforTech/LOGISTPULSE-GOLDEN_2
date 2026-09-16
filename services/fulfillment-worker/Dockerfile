FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py command_loop.py ./
COPY domain ./domain
CMD ["python","app.py"]

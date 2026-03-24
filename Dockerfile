FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY newspaper_report.py .

CMD ["python", "newspaper_report.py"]

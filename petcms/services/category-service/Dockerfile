FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5007
CMD ["gunicorn", "-b", "0.0.0.0:5007", "-w", "2", "app:app"]

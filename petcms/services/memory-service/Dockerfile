FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5009
CMD ["gunicorn", "-b", "0.0.0.0:5009", "-w", "2", "app:app"]

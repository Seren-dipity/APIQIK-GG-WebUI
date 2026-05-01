FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p output && chmod 777 output
EXPOSE 7860
CMD ["python", "main.py"]

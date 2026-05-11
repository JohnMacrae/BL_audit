FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python deps
RUN pip install --no-cache-dir playwright && \
    playwright install chromium

COPY audit.py .

CMD ["python", "audit.py"]

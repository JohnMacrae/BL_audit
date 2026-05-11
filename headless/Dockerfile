FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

RUN pip install --no-cache-dir playwright google-auth google-auth-oauthlib google-api-python-client && \
    playwright install chromium

COPY audit_logic.py .
COPY audit.py .

CMD ["python", "audit.py"]

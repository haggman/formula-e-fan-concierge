FROM python:3.12-slim

WORKDIR /app

# Install Python deps first (better layer caching)
COPY state_writer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared models package (needed by main.py)
COPY shared/ ./shared/

# Copy the service
COPY state_writer/main.py ./main.py

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

# Cloud Run sets PORT; uvicorn binds to it
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}

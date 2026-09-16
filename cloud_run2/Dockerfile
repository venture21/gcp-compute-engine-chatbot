FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 chatbot

COPY --chown=chatbot:chatbot server.py ./
COPY --chown=chatbot:chatbot public ./public
USER chatbot

EXPOSE 8080
CMD ["python", "server.py"]

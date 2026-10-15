FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . .

RUN python -m pip install --no-cache-dir --requirement requirements.lock
RUN python -m compileall -q app tests

CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

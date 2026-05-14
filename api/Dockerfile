FROM python:3.11-slim

# OpenCV 런타임 의존성 (Debian trixie 호환)
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

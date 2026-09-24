FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Taipei

# Install system dependencies for Pillow, Git, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    gcc \
    g++ \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-c"]

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    if grep -q "avx2" /proc/cpuinfo 2>/dev/null; then \
        echo "✔ 檢測到主機支援 AVX2 向量加速，安裝官方預編譯優化版本..." && \
        pip install --no-cache-dir --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu -r requirements.txt ; \
    else \
        echo "⚠️ 檢測到主機 CPU 未具備 AVX2 指令集，啟動相容性原始碼編譯 (關閉 AVX2/AVX/FMA)..." && \
        grep -v "llama-cpp-python" requirements.txt > /tmp/req_base.txt && \
        pip install --no-cache-dir -r /tmp/req_base.txt && \
        rm -f /tmp/req_base.txt && \
        CMAKE_ARGS="-DGGML_AVX2=OFF -DGGML_AVX=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF" \
        pip install --no-cache-dir --no-binary llama-cpp-python "llama-cpp-python>=0.2.89" ; \
    fi

COPY . .

CMD ["python", "-m", "zeronexus.main"]

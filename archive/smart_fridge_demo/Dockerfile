# 食光冰箱 Smart Fridge Demo —— 云端 / 任意 Linux 主机镜像
# 构建:  docker build -t smart-fridge .
# 运行:  docker run -p 8000:8000 -v fridge-data:/data -e DEEPSEEK_API_KEY=sk-xxx smart-fridge
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # 所有运行数据（数据库、上传图、备份）都放在 /data，挂载持久卷即可保留
    SMART_FRIDGE_STORAGE_DIR=/data/storage \
    # 云端没有 USB 摄像头和 GPIO，显式关闭实体按钮
    SMART_FRIDGE_GPIO_BUTTON_ENABLED=false \
    PORT=8000

WORKDIR /app

# 容器内用无界面 OpenCV（不依赖 libGL），其余依赖与 requirements.txt 完全一致
COPY requirements.txt ./
RUN sed 's/^opencv-python>/opencv-python-headless>/' requirements.txt > /tmp/requirements.docker.txt \
    && pip install --upgrade pip \
    && pip install -r /tmp/requirements.docker.txt

COPY app ./app
COPY frontend ./frontend
COPY yolo ./yolo
COPY config/api_settings.example.json ./config/api_settings.example.json
COPY app.py receipt.jpg ./

RUN useradd --create-home --uid 1000 fridge \
    && mkdir -p /data/storage \
    && chown -R fridge:fridge /app /data
USER fridge
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=4)" || exit 1

# PORT 由平台注入（Railway / Render / Fly 等），默认 8000
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

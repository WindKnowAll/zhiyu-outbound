FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# onnxruntime 需要 libgomp。其余音视频库用官方 wheel，不再装编译器。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY prompts ./prompts
COPY zhiyu ./zhiyu

# 构建时确认依赖能导入，并且 Silero 的 onnx 文件在镜像里。
RUN python -c "from zhiyu.config import load_persona; from zhiyu.server import _preload_silero; load_persona(); _preload_silero()"

EXPOSE 7860

CMD ["python", "-m", "zhiyu.server", "--host", "0.0.0.0", "--port", "7860"]

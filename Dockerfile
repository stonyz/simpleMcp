# ---------- Stage 1: Build frontend ----------
    FROM node:20 AS frontend-builder

    # 设置工作目录
    WORKDIR /web
    
    # 复制前端代码（未来使用，现在会是空目录）
    COPY web/ .
    
    # 如果有 package.json 就安装依赖并打包
    RUN if [ -f package.json ]; then npm install && npm run build; fi
    
    
    # ---------- Stage 2: Build backend ----------
    FROM python:3.12-slim AS backend
    
    # 环境变量（避免 pyc、强制 utf-8）
    ENV PYTHONDONTWRITEBYTECODE=1 \
        PYTHONUNBUFFERED=1 \
        POETRY_VIRTUALENVS_CREATE=false \
        POETRY_NO_INTERACTION=1 \
        POETRY_NO_ANSI=1 \
        DEBIAN_FRONTEND=noninteractive \
        TERM=xterm
        

    # RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        vim-tiny \
        curl \
        htop \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/vim.tiny /usr/bin/vi

    # 设置工作目录
    WORKDIR /app
    
    # 安装 Poetry
    RUN pip install --no-cache-dir --progress-bar off  poetry

    
    # 复制 Poetry 文件
    COPY pyproject.toml poetry.lock* ./

    # 安装依赖（只安装 main，不要 dev）
    RUN poetry install --no-interaction --no-root
    
    # 复制后端代码
    COPY app/ ./app/
    
    # 复制日志目录（实际会在运行时挂载）
    RUN mkdir -p logs
    
    # 如果前端构建成功，把静态文件复制到 app/static
    #COPY --from=frontend-builder /web/build ./app/static
    
    # 暴露端口
    EXPOSE 8000
    
    # 使用 uvicorn 作为启动命令
    CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    
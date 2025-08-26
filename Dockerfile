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
    
    # 设置工作目录
    WORKDIR /app
    
    # 环境变量（避免 pyc、强制 utf-8）
    ENV PYTHONDONTWRITEBYTECODE=1
    ENV PYTHONUNBUFFERED=1
    
    # 安装 Poetry
    RUN pip install --no-cache-dir poetry
    
    # 复制 Poetry 文件
    COPY pyproject.toml poetry.lock* ./
    
    # 安装依赖（只安装 main，不要 dev）
    RUN poetry install --no-dev --no-root
    
    # 复制后端代码
    COPY app/ ./app/
    
    # 复制日志目录（实际会在运行时挂载）
    RUN mkdir -p logs
    
    # 如果前端构建成功，把静态文件复制到 app/static
    COPY --from=frontend-builder /web/build ./app/static
    
    # 暴露端口
    EXPOSE 8000
    
    # 使用 uvicorn 作为启动命令
    CMD ["poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    
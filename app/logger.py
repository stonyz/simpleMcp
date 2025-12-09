import logging
import os
import re
import glob
import time
from datetime import datetime, timedelta
from typing import Optional
from app.config import settings

# ========= 配置 =========
LOG_LEVEL = settings.log_level.upper()
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 单文件大小（字节），例如 10MB： 10 * 1024 * 1024
LOG_FILE_SIZE = getattr(settings, "log_file_size", 10 * 1024 * 1024)

# 控制台开关（开发 True，线上 False）
ENABLE_CONSOLE = getattr(settings, "enable_console", True)

# 日期格式
DATE_FMT = "%Y-%m-%d"

# 默认保留最近 N 天（归档清理），不需要可设为 0
BACKUP_DAYS = getattr(settings, "log_backup_days", 7)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
formatter = logging.Formatter(LOG_FORMAT)

loggers = {}  # 缓存已创建的 logger


class DailySizeDatedFileHandler(logging.Handler):
    def __init__(self, base_path: str, max_bytes: int, date_fmt: str = "%Y-%m-%d", backup_days: int = 0, encoding: str = "utf-8", level: int = logging.INFO):
        super().__init__(level=level)
        self.base_dir = os.path.dirname(base_path)
        self.base_name, self.base_ext = os.path.splitext(os.path.basename(base_path))
        self.max_bytes = max_bytes
        self.date_fmt = date_fmt
        self.backup_days = backup_days
        self.encoding = encoding

        self.current_date = self._today_str()
        self.stream = None
        # 在初始化时也进行一次清理，确保即使应用重启也能清理旧文件
        self._cleanup_old_files()
        self._open()

    def _today_str(self):
        return datetime.now().strftime(self.date_fmt)

    def _build_filename(self, date_str: str, part: int = None) -> str:
        if part is None:
            # 最新文件无后缀
            filename = f"{self.base_name}-{date_str}{self.base_ext}"
        else:
            # 老文件带序号
            filename = f"{self.base_name}-{date_str}-{part}{self.base_ext}"
        return os.path.join(self.base_dir, filename)

    def _open(self):
        os.makedirs(self.base_dir, exist_ok=True)
        filename = self._build_filename(self.current_date)
        self.stream = open(filename, mode="a", encoding=self.encoding)

    def _should_rollover(self) -> bool:
        today = self._today_str()
        if today != self.current_date:
            return True
        if self.max_bytes > 0 and self.stream:
            self.stream.flush()
            if self.stream.tell() >= self.max_bytes:
                return True
        return False

    def _do_rollover(self):
        self._close()

        today = self._today_str()
        if today != self.current_date:
            # 新的一天，从最新文件开始
            self.current_date = today
            self._cleanup_old_files()
        else:
            # 同一天 -> 把当前无后缀文件改名为 -1, -2 ...
            self._rotate_existing_files(today)

        self._open()

    def _rotate_existing_files(self, date_str: str):
        # 找出已存在的 -n 文件
        pattern = os.path.join(self.base_dir, f"{self.base_name}-{date_str}-*{self.base_ext}")
        existing = glob.glob(pattern)

        # 依次往后挪：-1 -> -2, -2 -> -3 ...
        def extract_num(path):
            m = re.search(rf"{self.base_name}-{date_str}-(\d+){self.base_ext}$", os.path.basename(path))
            return int(m.group(1)) if m else None

        for path in sorted(existing, key=extract_num, reverse=True):
            num = extract_num(path)
            if num is not None:
                os.rename(path, self._build_filename(date_str, num + 1))

        # 把当前无后缀文件改名为 -1
        cur_file = self._build_filename(date_str)
        if os.path.exists(cur_file):
            os.rename(cur_file, self._build_filename(date_str, 1))

    def _cleanup_old_files(self):
        """清理超过 backup_days 的旧日志文件"""
        if self.backup_days <= 0:
            return
            
        # 计算应该保留的最早日期
        cutoff_date = datetime.now() - timedelta(days=self.backup_days)
        
        # 查找所有匹配的日志文件
        pattern = os.path.join(self.base_dir, f"{self.base_name}-*{self.base_ext}")
        all_files = glob.glob(pattern)
        
        # 提取日期并删除过期文件
        date_pattern = re.compile(rf"{self.base_name}-(\d{{4}}-\d{{2}}-\d{{2}})(?:-(\d+))?{self.base_ext}$")
        
        for file_path in all_files:
            filename = os.path.basename(file_path)
            match = date_pattern.search(filename)
            if match:
                try:
                    file_date_str = match.group(1)
                    file_date = datetime.strptime(file_date_str, self.date_fmt)
                    # 如果文件日期早于截止日期，则删除文件
                    if file_date < cutoff_date:
                        os.remove(file_path)
                except (ValueError, OSError):
                    # 解析日期失败或删除文件失败，跳过该文件
                    continue

    def emit(self, record: logging.LogRecord):
        try:
            if self._should_rollover():
                self._do_rollover()
            msg = self.format(record)
            if self.stream is None:
                self._open()
            self.stream.write(msg + "\n")
            self.stream.flush()
        except Exception:
            self.handleError(record)

    def _close(self):
        if self.stream:
            try:
                self.stream.close()
            finally:
                self.stream = None


# ========= Handler 工厂 =========

def _make_dated_handler(filename: str, level: int) -> DailySizeDatedFileHandler:
    handler = DailySizeDatedFileHandler(
        base_path=filename,
        max_bytes=LOG_FILE_SIZE,
        date_fmt=DATE_FMT,
        backup_days=BACKUP_DAYS,
        level=level,
    )
    handler.setFormatter(formatter)
    return handler

_error_handler: DailySizeDatedFileHandler | None = None

def get_error_handler() -> DailySizeDatedFileHandler:
    global _error_handler
    if _error_handler is None:
        _error_handler = _make_dated_handler(os.path.join(LOG_DIR, "error.log"), level=logging.ERROR)
    return _error_handler

# ========= 根日志（兜底） =========

def setup_logging():
    """
    根日志策略：
      - app-YYYY-MM-DD[-n].log：所有“无专属文件”的日志
      - error-YYYY-MM-DD[-n].log：所有 ERROR+（来自根 logger）
      - console：可开关
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    root_logger.propagate = False

    if not root_logger.handlers:
        # app 日志（带日期 + 按大小）
        app_handler = _make_dated_handler(os.path.join(LOG_DIR, "app.log"), level=getattr(logging, LOG_LEVEL))
        root_logger.addHandler(app_handler)

        # error 日志（带日期 + 按大小）
        root_logger.addHandler(get_error_handler())
        # 控制台（可选）
        if ENABLE_CONSOLE:
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            root_logger.addHandler(ch)

    # 常见第三方日志级别
    logging.getLogger("uvicorn").setLevel(LOG_LEVEL)
    logging.getLogger("uvicorn.error").setLevel(LOG_LEVEL)
    logging.getLogger("uvicorn.access").setLevel(LOG_LEVEL)


# ========= 获取 logger =========

def get_logger(name: str, log_file: str = None):
    """
    - 未指定 log_file：返回 root（写 app-*.log + error-*.log [+ console]）
    - 指定 log_file：创建专属 logger（只写自己的文件 + 附加 error-*.log），不冒泡
    """
    if name in loggers:
        return loggers[name]

    if not log_file:
        # 用根 logger
        logger = logging.getLogger()
    else:
        logger = logging.getLogger(name)
        logger.setLevel(LOG_LEVEL)
        logger.propagate = False

        # 专属文件（带日期 + 按大小）
        file_handler = _make_dated_handler(os.path.join(LOG_DIR, log_file), level=getattr(logging, LOG_LEVEL))
        logger.addHandler(file_handler)

        # 确保 ERROR 永远写入全局 error-*.log
        logger.addHandler(get_error_handler())

    loggers[name] = logger
    return logger

request_logger = get_logger("request", "request.log")
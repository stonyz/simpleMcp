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
    """
    当前文件名也带日期的 Handler。
    - 跨天或超大小 -> 新文件
    - 同一天内超大小 -> 生成 -1, -2 分片
    - 可按天清理历史文件
    说明：不适用于多进程并发写同一日志文件的场景（需要额外并发安全方案）。
    """

    def __init__(
        self,
        base_path: str,
        max_bytes: int,
        date_fmt: str = DATE_FMT,
        backup_days: int = 0,
        encoding: Optional[str] = "utf-8",
        level: int = logging.INFO,
    ):
        super().__init__(level=level)
        self.base_dir = os.path.dirname(base_path)
        self.base_name, self.base_ext = os.path.splitext(os.path.basename(base_path))
        self.max_bytes = max_bytes
        self.date_fmt = date_fmt
        self.backup_days = backup_days
        self.encoding = encoding

        self.current_date = self._today_str()
        self.part_index = self._get_initial_part_index()
        self.stream = None
        self._open()  # 打开当前日期的文件

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # 每次写入前判断是否需要切割
            if self._should_rollover():
                self._do_rollover()

            msg = self.format(record)
            # 确保 stream 存在
            if self.stream is None:
                self._open()
            self.stream.write(msg + "\n")
            self.stream.flush()
        except Exception:
            self.handleError(record)

    # ---------- 私有方法 ----------

    def _today_str(self) -> str:
        return datetime.now().strftime(self.date_fmt)

    def _build_filename(self, date_str: str, part: int) -> str:
        # logs/app-2025-08-26.log 或 logs/app-2025-08-26-1.log
        suffix = f"-{part}" if part > 0 else ""
        filename = f"{self.base_name}-{date_str}{suffix}{self.base_ext}"
        return os.path.join(self.base_dir, filename)

    def _get_initial_part_index(self) -> int:
        """
        应对进程重启：扫描已存在的该日文件，找到最大的分片序号 + 1
        """
        date_str = self._today_str()
        pattern = os.path.join(self.base_dir, f"{self.base_name}-{date_str}*{self.base_ext}")
        existing = glob.glob(pattern)
        if not existing:
            return 0

        # 匹配 ...-YYYY-MM-DD(-n)?.ext
        rx = re.compile(rf"{re.escape(self.base_name)}-{re.escape(date_str)}(?:-(\d+))?{re.escape(self.base_ext)}$")
        max_part = -1
        for path in existing:
            m = rx.search(os.path.basename(path))
            if m:
                if m.group(1) is None:
                    max_part = max(max_part, 0)
                else:
                    max_part = max(max_part, int(m.group(1)))
        return max_part + 1

    def _open(self):
        os.makedirs(self.base_dir, exist_ok=True)
        filename = self._build_filename(self.current_date, self.part_index)
        # 以追加方式打开
        self.stream = open(filename, mode="a", encoding=self.encoding)

    def _close(self):
        if self.stream:
            try:
                self.stream.close()
            finally:
                self.stream = None

    def _should_rollover(self) -> bool:
        # 跨天
        today = self._today_str()
        if today != self.current_date:
            return True

        # 超大小
        if self.max_bytes > 0 and self.stream:
            try:
                self.stream.flush()
                size = self.stream.tell()
                if size >= self.max_bytes:
                    return True
            except Exception:
                # 保险：获取大小失败也尝试切割，避免卡死
                return True
        return False

    def _do_rollover(self):
        self._close()

        today = self._today_str()
        if today != self.current_date:
            # 新的一天，分片从 0 开始
            self.current_date = today
            self.part_index = 0
            self._cleanup_old_files()
        else:
            # 同一天内大小分片
            self.part_index += 1

        self._open()

    def _cleanup_old_files(self):
        """
        清理过期文件：只按天保留（比如最近 7 天），不区分分片。
        """
        if self.backup_days and self.backup_days > 0:
            cutoff_date = (datetime.now() - timedelta(days=self.backup_days)).strftime(self.date_fmt)
            # 删除严格早于 cutoff_date 的文件
            pattern = os.path.join(self.base_dir, f"{self.base_name}-*{self.base_ext}")
            for path in glob.glob(pattern):
                # 提取日期字符串
                m = re.search(rf"{re.escape(self.base_name)}-(\d{{4}}-\d{{2}}-\d{{2}})", os.path.basename(path))
                if not m:
                    continue
                file_date = m.group(1)
                if file_date < cutoff_date:
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    def close(self):
        self._close()
        super().close()

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

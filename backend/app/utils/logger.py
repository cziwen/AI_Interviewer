import logging
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

def setup_logger():
    """
    配置全局日志模组，每次启动生成独立的日志文件。
    """
    # 1. 确保日志目录存在
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # 确保面试日志目录存在
    interview_log_dir = log_dir / "interviews"
    interview_log_dir.mkdir(exist_ok=True)

    # 2. 生成带时间戳的文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"server_{timestamp}.log"

    # 3. 配置 logging
    logger = logging.getLogger("ai_interview")
    logger.setLevel(logging.INFO)

    # 防止重复添加 handler
    if not logger.handlers:
        # 文件处理器（Server Log）
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger

# 创建全局 logger 实例
logger = setup_logger()

def log_interview_event(
    event_name: str,
    interview_id: Optional[int] = None,
    interview_token: Optional[str] = None,
    level: int = logging.INFO,
    source: str = "unknown",
    stage: Optional[str] = None,
    turn_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    **kwargs
):
    """
    记录面试会话日志（Interview Log）。
    支持结构化输出到专用的面试日志文件。
    """
    timestamp = datetime.now().isoformat() + "Z"
    
    # 构建基础 Schema
    log_entry = {
        "timestamp": timestamp,
        "level": logging.getLevelName(level),
        "event_name": event_name,
        "source": source,
        "interview_id": interview_id,
        "interview_token": interview_token,
        "stage": stage,
        "turn_id": turn_id,
        "details": details or {},
    }
    
    # 合并其他可选字段
    log_entry.update(kwargs)
    
    # 序列化为 JSON 字符串
    log_line = json.dumps(log_entry, ensure_ascii=False)
    
    # 1. 记录到全局 Server Log (作为摘要)
    summary = f"InterviewEvent[{event_name}] - ID: {interview_id}, Token: {interview_token}"
    if level >= logging.ERROR:
        logger.error(f"{summary} - Error: {kwargs.get('error_message') or 'Unknown'}")
    else:
        logger.info(summary)
        
    # 2. 记录到专用的面试日志文件
    if interview_token:
        date_str = datetime.now().strftime("%Y%m%d")
        interview_file = Path("logs/interviews") / f"interview_token_{interview_token}_{date_str}.log"
        
        try:
            with open(interview_file, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception as e:
            logger.error(f"Failed to write interview log to {interview_file}: {e}")

def log_dialogue_line(
    interview_token: str,
    role: str,
    text: str,
    timestamp: Optional[str] = None
):
    """
    记录面试对话日志（Dialogue Log）。
    格式：{timestamp}  {role}  {text}
    """
    if not timestamp:
        timestamp = datetime.now().isoformat() + "Z"
    
    # 确保文本中没有换行，保持一行一条记录
    clean_text = text.replace("\n", " ").replace("\r", "")
    
    log_line = f"{timestamp}  {role}  {clean_text}"
    
    date_str = datetime.now().strftime("%Y%m%d")
    dialogue_file = Path("logs/interviews") / f"interview_token_{interview_token}_{date_str}_dialogue.log"
    
    try:
        with open(dialogue_file, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception as e:
        logger.error(f"Failed to write dialogue log to {dialogue_file}: {e}")

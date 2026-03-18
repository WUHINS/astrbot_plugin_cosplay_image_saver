import json
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, StarTools


class WebuiConfig(BaseModel):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 9191
    auth_enabled: bool = True
    password: str = ""
    session_timeout: int = 3600


class SMTPConfig(BaseModel):
    """SMTP 邮件配置"""
    enabled: bool = False  # 是否启用邮件推送
    smtp_server: str = ""  # SMTP 服务器地址
    smtp_port: int = 587  # SMTP 端口（默认 587）
    sender_email: str = ""  # 发件人邮箱
    sender_password: str = ""  # 邮箱授权码/密码
    receiver_email: str = ""  # 收件人邮箱
    use_tls: bool = True  # 是否使用 TLS 加密
    send_time: str = "08:00"  # 每日发送时间（24 小时制）


class PluginConfig(BaseModel):
    # === 女装图片保存 ===
    save_cosplay_images: bool = True  # 开启女装图片保存
    cosplay_vision_provider_id: str = ""  # 女装识别专用模型（留空使用默认视觉模型）
    cosplay_detection_threshold: float = 0.6  # 女装识别阈值（宽松判断）
    ignore_gif: bool = False  # 是否忽略 GIF 图片（不检测不保存）

    # === 模型配置 ===
    vision_provider_id: str = ""

    # === WebUI 管理界面 ===
    webui: WebuiConfig = Field(default_factory=WebuiConfig)

    # === SMTP 邮件推送 ===
    smtp: SMTPConfig = Field(default_factory=SMTPConfig)

    # === 内部常量/高级配置 ===
    max_reg_num: int = 100
    content_filtration: bool = False  # 内容审核开关
    image_processing_cooldown: int = 10

    # === 内化常量（不再暴露给用户） ===
    DO_REPLACE: ClassVar[bool] = True  # 达到上限始终替换旧文件
    ENABLE_RAW_CLEANUP: ClassVar[bool] = True  # raw 始终自动清理
    RAW_CLEANUP_INTERVAL: ClassVar[int] = 30  # 清理周期 (分钟)，固定
    ENABLE_CAPACITY_CONTROL: ClassVar[bool] = True  # 始终启用容量控制
    CAPACITY_CONTROL_INTERVAL: ClassVar[int] = 60  # 容量检查周期 (分钟)，固定
    RAW_RETENTION_MINUTES: ClassVar[int] = 60  # 原始图片保留时间 (分钟)，固定

    # === 表情包分类管理 ===
    categories: list[str] = Field(default_factory=list)
    category_info: dict[str, dict[str, str]] = Field(default_factory=dict)

    # === 内部状态 (不作为 Pydantic 字段) ===
    # 使用 PrivateAttr 或在 __init__ 中设置且不包含在 __annotations__ 中
    # 但 Pydantic v1/v2 处理方式不同。这里使用 __private_attributes__ 机制或直接忽略

    # 忽略额外字段 (Pydantic v1/v2 配置)
    model_config = {
        "extra": "ignore",
        "arbitrary_types_allowed": True
    }

    def __init__(self, config: AstrBotConfig | None, context: Context | None = None):
        # 1. 初始化 Pydantic 模型
        # config 可能是 AstrBotConfig (dict-like) 或 None
        initial_data = config if config else {}
        super().__init__(**initial_data)

        # 2. 保存 AstrBotConfig 引用以便回写
        # 使用 object.__setattr__ 绕过 Pydantic 的 setattr 检查
        object.__setattr__(self, "_data", config)
        object.__setattr__(self, "_plugin_name", "astrbot_plugin_cosplay_saver")

        # 3. 初始化路径和目录
        data_dir = StarTools.get_data_dir(self._plugin_name)
        object.__setattr__(self, "data_dir", data_dir)
        object.__setattr__(self, "categories_path", data_dir / "categories.json")
        object.__setattr__(self, "raw_dir", data_dir / "raw")
        object.__setattr__(self, "categories_dir", data_dir / "categories")
        object.__setattr__(self, "cache_dir", data_dir / "cache")
        object.__setattr__(self, "category_info_path", data_dir / "category_info.json")
        object.__setattr__(self, "cosplay_dir", data_dir / "cosplay")  # 女装图片保存目录
        object.__setattr__(self, "database_path", data_dir / "image_records.db")  # 数据库文件

        # 确保目录存在
        self.ensure_base_dirs()
        
        # 初始化数据库
        from .database import Database
        object.__setattr__(self, "db", Database(self.database_path))

    def _read_json_file(self, path: Path):
        try:
            if not path.exists():
                return None
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"[Config] JSON 解析失败 {path}: {e}")
            return None
        except Exception as e:
            logger.debug(f"[Config] 读取文件失败 {path}: {e}")
            return None

    def _write_json_file(self, path: Path, data: Any) -> bool:
        """写入 JSON 文件。

        Args:
            path: 文件路径
            data: 要写入的数据

        Returns:
            bool: 是否写入成功
        """
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except PermissionError as e:
            logger.error(f"[Config] 权限不足，无法写入文件 {path}: {e}")
            return False
        except OSError as e:
            logger.error(f"[Config] 写入文件失败 {path}: {e}")
            return False
        except Exception as e:
            logger.error(f"[Config] 写入 JSON 文件时发生未知错误 {path}: {e}")
            return False

    def save_webui_config(self) -> None:
        """保存 WebUI 配置。"""
        if hasattr(self, "_data") and hasattr(self._data, "save_config"):
            self._data.save_config({"webui": self.webui.model_dump()})

    def __setattr__(self, key: str, value: Any):
        # 更新 Pydantic 模型
        super().__setattr__(key, value)

        # 如果是私有属性或路径属性，跳过回写
        if key.startswith("_") or key in (
            "data_dir",
            "cosplay_dir",
            "raw_dir",
            "cache_dir",
        ):
            return

        # 回写到 AstrBotConfig
        if hasattr(self, "_data") and self._data is not None:
            if hasattr(self._data, "save_config"):
                try:
                    if key == "webui" and isinstance(value, WebuiConfig):
                        self._data.save_config({key: value.model_dump()})
                    else:
                        self._data.save_config({key: value})
                except Exception as e:
                    logger.error(f"[Config] 保存配置失败 {key}: {e}")
            elif isinstance(self._data, dict):
                self._data[key] = value

    def update_config(self, updates: dict) -> bool:
        """批量更新配置项。

        Args:
            updates: 配置更新字典

        Returns:
            bool: 是否更新成功
        """
        try:
            for key, value in updates.items():
                setattr(self, key, value)

            # 回写到 AstrBotConfig
            if hasattr(self, "_data") and self._data is not None:
                if hasattr(self._data, "save_config"):
                    self._data.save_config(updates)
                elif isinstance(self._data, dict):
                    self._data.update(updates)
            return True
        except Exception as e:
            logger.error(f"更新配置失败: {e}")
            return False

    def save_categories(self) -> None:
        """保存分类配置（兼容方法，实际已不使用）。"""
        pass

    def save_category_info(self) -> None:
        """保存分类信息（兼容方法，实际已不使用）。"""
        pass

    def ensure_raw_dir(self) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        return self.raw_dir

    def ensure_cache_dir(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir

    def ensure_base_dirs(self) -> None:
        """确保基础目录存在（带异常处理）。"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.cosplay_dir.mkdir(parents=True, exist_ok=True)  # 女装图片保存目录
        except PermissionError as e:
            logger.error(f"[Config] 创建目录失败（权限不足）：{e}")
            raise
        except Exception as e:
            logger.error(f"[Config] 创建目录失败：{e}")
            raise

    async def add_image_record(self, record: dict) -> bool:
        """添加图片保存记录（使用数据库，异步）。
        
        Args:
            record: 记录字典，包含 save_path, group_id, user_id, user_name, timestamp, hash 等字段
            
        Returns:
            bool: 是否添加成功
        """
        try:
            if not hasattr(self, "db"):
                logger.error("[Config] 数据库未初始化")
                return False
            
            return await self.db.add_record(record)
        except Exception as e:
            logger.error(f"[Config] 添加图片记录失败：{e}")
            return False

    async def get_image_records_by_date(self, target_date: datetime.date, use_local_time: bool = True) -> list[dict]:
        """获取指定日期的图片记录（从数据库，异步）。
        
        Args:
            target_date: 目标日期
            use_local_time: 是否使用本地时间查询（默认 True，跨日统计更准确）
            
        Returns:
            list[dict]: 图片记录列表
        """
        try:
            if not hasattr(self, "db"):
                logger.error("[Config] 数据库未初始化")
                return []
            
            return await self.db.get_records_by_date(target_date, use_local_time=use_local_time)
        except Exception as e:
            logger.error(f"[Config] 获取图片记录失败：{e}")
            return []

    async def get_all_image_records(self, order_by_utc: bool = True) -> list[dict]:
        """获取所有图片记录（从数据库，异步）。
        
        Args:
            order_by_utc: 是否按 UTC 时间排序（默认 True）
            
        Returns:
            list[dict]: 所有图片记录
        """
        try:
            if not hasattr(self, "db"):
                logger.error("[Config] 数据库未初始化")
                return []
            
            return await self.db.get_all_records(order_by_utc=order_by_utc)
        except Exception as e:
            logger.error(f"[Config] 获取所有图片记录失败：{e}")
            return []

    async def cleanup_old_records(self, retention_days: int = 7, use_utc: bool = False) -> int:
        """清理旧记录（异步）。
        
        Args:
            retention_days: 保留天数，默认 7 天
            use_utc: 是否使用 UTC 时间计算（默认 False，使用本地时间更符合用户感知）
            
        Returns:
            int: 删除的记录数
        """
        try:
            if not hasattr(self, "db"):
                logger.error("[Config] 数据库未初始化")
                return 0
            
            return await self.db.cleanup_old_records(retention_days, use_utc=use_utc)
        except Exception as e:
            logger.error(f"[Config] 清理旧记录失败：{e}")
            return 0

    def get_group_id(self, event: AstrMessageEvent) -> str:
        """获取群号。"""
        try:
            return event.get_group_id()
        except Exception:
            return ""

    def get_user_id(self, event: AstrMessageEvent) -> str:
        """获取用户 ID。"""
        try:
            user_id = event.get_sender_id()
            if user_id:
                return str(user_id).strip()
        except (AttributeError, KeyError, TypeError) as e:
            logger.debug(f"[Config] get_sender_id 失败：{e}")
        except Exception as e:
            logger.debug(f"[Config] 获取用户 ID 意外错误：{e}")

        for attr in ("sender_id", "user_id"):
            try:
                value = getattr(event, attr, None)
            except (AttributeError, KeyError, TypeError) as e:
                logger.debug(f"[Config] getattr {attr} 失败：{e}")
                value = None
            if value:
                return str(value).strip()

        try:
            message_obj = getattr(event, "message_obj", None)
            sender = getattr(message_obj, "sender", None) if message_obj else None
            user_id = getattr(sender, "user_id", None) if sender is not None else None
            if user_id:
                return str(user_id).strip()
        except (AttributeError, KeyError, TypeError) as e:
            logger.debug(f"[Config] 从 message_obj 获取用户 ID 失败：{e}")
        except Exception as e:
            logger.debug(f"[Config] 获取用户 ID 意外错误：{e}")

        return ""

    def get_event_target(self, event: AstrMessageEvent) -> tuple[str, str]:
        group_id = self.get_group_id(event)
        if group_id:
            return "group", str(group_id).strip()

        user_id = self.get_user_id(event)
        if user_id:
            return "user", str(user_id).strip()

        return "", ""

    @staticmethod
    def normalize_target_entry(value: object, default_scope: str = "group") -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""

        lowered = raw.lower()
        for prefix, scope in (
            ("group:", "group"),
            ("g:", "group"),
            ("群:", "group"),
            ("user:", "user"),
            ("u:", "user"),
            ("qq:", "user"),
            ("好友:", "user"),
            ("私聊:", "user"),
        ):
            if lowered.startswith(prefix):
                target_id = raw[len(prefix) :].strip()
                return f"{scope}:{target_id}" if target_id else ""

        if ":" in raw:
            scope, target_id = raw.split(":", 1)
            scope = scope.strip().lower()
            target_id = target_id.strip()
            if scope in {"group", "user"} and target_id:
                return f"{scope}:{target_id}"

        return f"{default_scope}:{raw}" if raw else ""

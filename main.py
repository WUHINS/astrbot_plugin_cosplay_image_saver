import asyncio
import os
from datetime import datetime
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import (
    EventMessageType,
    PlatformAdapterType,
    event_message_type,
    platform_adapter_type,
)
from astrbot.api.star import Context, Star

from .core.config import PluginConfig
from .core.event_handler import EventHandler
from .core.image_processor_service import ImageProcessorService
from .core.smtp_service import SMTPService
from .core.task_scheduler import TaskScheduler


class Main(Star):
    """女装图片保存插件。

    功能：
    - 监听消息中的图片并使用视觉模型检测是否为女装图片
    - 自动保存女装图片到对应目录（群号/群员 QQ 号_QQ 名）
    """

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)

        # 初始化插件配置
        self.plugin_config = PluginConfig(config, context)

        self.base_dir: Path = self.plugin_config.data_dir
        self.raw_dir: Path = self.plugin_config.raw_dir
        self.categories_dir: Path = self.plugin_config.categories_dir
        self.cache_dir: Path = self.plugin_config.cache_dir

        # 同步配置到实例属性
        self._sync_all_config()

        # 初始化核心服务类
        self.event_handler = EventHandler(self)
        self.image_processor_service = ImageProcessorService(self)
        self.smtp_service = SMTPService(self)
        self.task_scheduler = TaskScheduler(self)

        # 运行时属性
        self._terminated: bool = False

    def _sync_all_config(self):
        """同步所有配置到实例属性。"""
        self.vision_provider_id = getattr(self.plugin_config, "vision_provider_id", "")
        self.save_cosplay_images = getattr(
            self.plugin_config, "save_cosplay_images", True
        )
        self.cosplay_detection_threshold = getattr(
            self.plugin_config, "cosplay_detection_threshold", 0.6
        )
        self.ignore_gif = getattr(self.plugin_config, "ignore_gif", False)

    async def initialize(self):
        """插件初始化。"""
        try:
            # 确保目录存在
            for dir_path in [
                self.base_dir,
                self.raw_dir,
                self.categories_dir,
                self.cache_dir,
            ]:
                await asyncio.to_thread(dir_path.mkdir, parents=True, exist_ok=True)

            # 注意：不再在初始化时扫描目录迁移历史数据
            # 原因：会造成巨大的 IO 开销和 CPU 占用
            # 新保存的图片会自动写入数据库，历史数据无需强制迁移

            # 启动定时任务调度器（如果启用了邮件推送）
            if self.plugin_config.smtp.enabled:
                try:
                    await self.task_scheduler.start()
                    logger.info("[CosplaySaver] 邮件推送服务已启动")
                except Exception as e:
                    logger.error(f"[CosplaySaver] 邮件推送服务启动失败：{e}")

            logger.info("[CosplaySaver] 女装图片保存插件初始化完成")

        except Exception as e:
            logger.error(f"[CosplaySaver] 初始化失败：{e}", exc_info=True)
            raise

    async def _safe_remove_file(self, file_path: str) -> bool:
        """安全删除文件。

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否删除成功
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"已删除文件：{file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除文件失败 {file_path}: {e}")
            return False

    async def terminate(self):
        """插件终止。"""
        if self._terminated:
            return

        self._terminated = True
        logger.info("[CosplaySaver] 正在终止插件...")

        try:
            # 停止定时任务调度器
            if self.task_scheduler:
                await self.task_scheduler.stop()
            
            # 清理资源
            if self.image_processor_service:
                self.image_processor_service.cleanup()
            if self.event_handler:
                await self.event_handler.cleanup()
            
            # 关闭数据库连接池（重要！）
            if hasattr(self.plugin_config, "db") and self.plugin_config.db:
                await self.plugin_config.db.close()
                logger.info("[CosplaySaver] 数据库连接池已关闭")

            logger.info("[CosplaySaver] 插件已安全终止")
        except Exception as e:
            logger.error(f"[CosplaySaver] 终止时发生错误：{e}", exc_info=True)

    @event_message_type(EventMessageType.ALL)
    @platform_adapter_type(PlatformAdapterType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """消息监听：检测并保存女装图片。"""
        try:
            if self._terminated:
                logger.debug("[CosplaySaver] 插件已终止，跳过消息处理")
                return

            if not self.event_handler:
                logger.debug("[CosplaySaver] event_handler 未初始化，跳过消息处理")
                return

            # 委托给 EventHandler 处理
            await self.event_handler.on_message(event)

        except Exception as e:
            logger.error(f"[CosplaySaver] 处理消息时发生错误：{e}", exc_info=True)

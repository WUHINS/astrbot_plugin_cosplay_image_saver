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

            # 迁移旧数据到数据库
            try:
                await self._migrate_existing_images()
            except Exception as e:
                logger.error(f"[CosplaySaver] 数据迁移失败：{e}")

            # 清理 7 天前的旧记录（异步）
            try:
                deleted_count = await self.plugin_config.cleanup_old_records(7)
                if deleted_count > 0:
                    logger.info(f"[CosplaySaver] 已自动清理 {deleted_count} 条 7 天前的记录")
            except Exception as e:
                logger.error(f"[CosplaySaver] 清理旧记录失败：{e}")

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

    async def _migrate_existing_images(self):
        """迁移已存在的图片到持久化记录（仅迁移未记录的）。"""
        try:
            # 使用 self.plugin_config.cosplay_dir 而不是 self.cosplay_dir
            cosplay_dir = self.plugin_config.cosplay_dir
            if not cosplay_dir or not cosplay_dir.exists():
                return
            
            # 获取所有已有记录
            existing_records = await self.plugin_config.get_all_image_records()
            existing_paths = {record['save_path'] for record in existing_records}
            
            migrated_count = 0
            
            # 遍历所有已保存的图片
            for group_dir in cosplay_dir.iterdir():
                if not group_dir.is_dir():
                    continue
                
                group_id = group_dir.name
                
                for user_dir in group_dir.iterdir():
                    if not user_dir.is_dir():
                        continue
                    
                    # 解析用户信息
                    user_parts = user_dir.name.split('_', 1)
                    user_id = user_parts[0] if user_parts else ''
                    user_name = user_parts[1] if len(user_parts) > 1 else ''
                    
                    for img_file in user_dir.iterdir():
                        if not img_file.is_file():
                            continue
                        
                        img_path_str = str(img_file)
                        
                        # 如果已经有记录，跳过
                        if img_path_str in existing_paths:
                            continue
                        
                        # 计算哈希
                        try:
                            import hashlib
                            hasher = hashlib.sha256()
                            with open(img_file, 'rb') as f:
                                hasher.update(f.read())
                            img_hash = hasher.hexdigest()
                        except Exception as e:
                            logger.warning(f"计算哈希失败 {img_file}: {e}")
                            img_hash = ""
                        
                        # 创建记录
                        record = {
                            "save_path": img_path_str,
                            "group_id": group_id,
                            "user_id": user_id,
                            "user_name": user_name,
                            "hash": img_hash,
                            "timestamp": datetime.fromtimestamp(img_file.stat().st_mtime).isoformat(),
                            "file_size": img_file.stat().st_size
                        }
                        
                        # 写入记录（异步）
                        if await self.plugin_config.add_image_record(record):
                            migrated_count += 1
                            logger.debug(f"已迁移图片记录：{img_path_str}")
            
            if migrated_count > 0:
                logger.info(f"[CosplaySaver] 已迁移 {migrated_count} 张历史图片到持久化记录")
            else:
                logger.debug("[CosplaySaver] 无需迁移历史图片")
                
        except Exception as e:
            logger.error(f"[CosplaySaver] 迁移历史图片失败：{e}", exc_info=True)

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

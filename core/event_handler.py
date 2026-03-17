import asyncio
import os
import tempfile
from typing import Any

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image


class EventHandler:
    """事件处理服务类，负责处理所有与插件相关的事件操作。"""

    # 类级别的 Session 管理器
    _session: aiohttp.ClientSession | None = None
    _session_lock: asyncio.Lock = asyncio.Lock()  # 异步锁，防止竞态条件

    def __init__(self, plugin_instance: Any):
        """初始化事件处理服务。

        Args:
            plugin_instance: Main 实例，用于访问插件的配置和服务
        """
        self.plugin = plugin_instance
        self._cleaned = False  # 清理标志位

    @classmethod
    async def _get_session(cls) -> aiohttp.ClientSession:
        """获取或创建共享的 ClientSession（线程安全）。"""
        # 使用异步锁防止多协程竞态条件
        async with cls._session_lock:
            if cls._session is None or cls._session.closed:
                cls._session = aiohttp.ClientSession()
            return cls._session

    @classmethod
    async def _close_session(cls):
        """关闭共享的 ClientSession。"""
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None

    def _normalize_str(self, value: object) -> str:
        """规范化字符串值。"""
        if value is None:
            return ""
        try:
            s = str(value)
        except Exception:
            return ""
        s = s.strip()
        if s.startswith("`") and s.endswith("`") and len(s) >= 2:
            s = s[1:-1].strip()
        return s

    async def _download_original_image(self, img: Image) -> tuple[str | None, bool]:
        """下载原始图片文件。

        Args:
            img: 图片组件

        Returns:
            tuple[str | None, bool]: (临时文件路径，是否为 GIF 动图)，失败返回 (None, False)
        """
        url = self._normalize_str(getattr(img, "url", ""))
        if not url:
            return None, False

        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning(f"下载图片失败：HTTP {resp.status}")
                    return None, False

                content_type = resp.headers.get("Content-Type", "").lower()
                content = await resp.read()

                # 根据 Content-Type 确定扩展名和是否为 GIF
                is_gif = "gif" in content_type
                if is_gif:
                    ext = ".gif"
                elif "png" in content_type:
                    ext = ".png"
                elif "webp" in content_type:
                    ext = ".webp"
                elif "jpeg" in content_type or "jpg" in content_type:
                    ext = ".jpg"
                else:
                    # 尝试从文件头判断
                    if content[:6] == b'GIF89a' or content[:6] == b'GIF87a':
                        ext = ".gif"
                        is_gif = True
                    elif content[:8] == b'\x89PNG\r\n\x1a\n':
                        ext = ".png"
                    elif content[:4] == b'RIFF' and content[8:12] == b'WEBP':
                        ext = ".webp"
                    else:
                        ext = ".jpg"

                # 保存到临时文件
                temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
                try:
                    os.write(temp_fd, content)
                    logger.debug(
                        f"已下载原始图片：{temp_path} ({len(content)} bytes, "
                        f"type={content_type}, is_gif={is_gif})"
                    )
                    return temp_path, is_gif
                finally:
                    os.close(temp_fd)

        except asyncio.TimeoutError:
            logger.warning("下载图片超时")
            return None, False
        except Exception as e:
            logger.warning(f"下载图片失败：{e}")
            return None, False

    # 注意：这个方法不需要装饰器，因为在 Main 类中已经使用了装饰器
    # @event_message_type(EventMessageType.ALL)
    # @platform_adapter_type(PlatformAdapterType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """消息监听：检测并保存女装图片。"""
        # 检查是否已清理
        if self._cleaned or self.plugin is None:
            return

        # 调试信息
        logger.debug(f"EventHandler.on_message called with event type: {type(event)}")

        # 检查 event 对象是否正确
        if not hasattr(event, "get_messages"):
            logger.error(
                f"Event object does not have get_messages method. Type: {type(event)}"
            )
            logger.error(f"Event attributes: {dir(event)}")
            return

        plugin_instance = self.plugin

        # 检查女装图片保存功能是否启用
        if not getattr(plugin_instance, "plugin_config", None):
            return

        if not getattr(plugin_instance.plugin_config, "save_cosplay_images", False):
            logger.debug("女装图片保存功能未启用，跳过检测")
            return

        logger.debug("女装图片保存功能已启用，开始检测图片")

        # 收集所有图片组件
        imgs: list[Image] = [
            comp for comp in event.get_messages() if isinstance(comp, Image)
        ]

        # 如果没有图片，直接返回
        if not imgs:
            logger.debug("消息中没有图片组件")
            return

        # 处理每张图片
        for i, img in enumerate(imgs):
            try:
                logger.debug(f"开始检测第 {i+1}/{len(imgs)} 张图片")

                # 下载图片用于检测
                temp_path_for_detect, is_gif = await self._download_original_image(img)
                
                # 如果下载失败，尝试使用 convert_to_file_path
                if not temp_path_for_detect:
                    temp_path_for_detect = await img.convert_to_file_path()
                    # 重新检测是否为 GIF（因为 download 失败时 is_gif 可能不准确）
                    if temp_path_for_detect and os.path.exists(temp_path_for_detect):
                        is_gif = temp_path_for_detect.lower().endswith(".gif")

                if not temp_path_for_detect or not os.path.exists(temp_path_for_detect):
                    logger.warning("女装检测：图片文件不存在")
                    continue

                # 检查是否忽略 GIF（在下载后检查，确保准确）
                if getattr(plugin_instance.plugin_config, "ignore_gif", False):
                    if is_gif or temp_path_for_detect.lower().endswith(".gif"):
                        logger.debug(f"已忽略 GIF 图片：{temp_path_for_detect}")
                        await self._safe_remove_file(temp_path_for_detect)
                        continue

                # 使用 ImageProcessorService 检测女装图片
                is_cosplay, reason = await plugin_instance.image_processor_service.detect_cosplay_image(
                    event, temp_path_for_detect
                )

                if is_cosplay:
                    logger.info(f"检测到女装图片：{reason}")
                    # 保存女装图片到对应目录
                    success, save_path = await plugin_instance.image_processor_service.save_cosplay_image(
                        event, temp_path_for_detect, is_temp=True
                    )
                    if success:
                        logger.debug(f"女装图片已保存：{save_path}")
                    else:
                        logger.warning(f"女装图片保存失败：{save_path}")
                else:
                    logger.debug(f"非女装图片：{reason}")

            except FileNotFoundError as e:
                logger.error(f"图片文件不存在：{e}")
            except PermissionError as e:
                logger.error(f"图片文件权限错误：{e}")
            except asyncio.TimeoutError as e:
                logger.error(f"图片处理超时：{e}")
            except ValueError as e:
                logger.error(f"图片处理参数错误：{e}")
            except Exception as e:
                logger.error(f"处理图片失败：{e}", exc_info=True)

    async def _clean_raw_directory(self) -> int:
        """清理 raw 目录中的所有原始图片文件。"""
        # 检查是否已清理
        if self._cleaned or self.plugin is None:
            return 0

        try:
            total_deleted = 0

            # 清理 raw 目录中的所有文件
            if self.plugin.base_dir:
                raw_dir = self.plugin.base_dir / "raw"
                if raw_dir.exists():
                    logger.debug(f"开始清理 raw 目录：{raw_dir}")

                    # 获取 raw 目录中的所有文件
                    files = list(raw_dir.iterdir())
                    if not files:
                        logger.debug(f"raw 目录已空：{raw_dir}")
                    else:
                        # 清理所有文件
                        deleted_count = 0
                        for file_path in files:
                            try:
                                if file_path.is_file():
                                    if await self.plugin._safe_remove_file(
                                        str(file_path)
                                    ):
                                        deleted_count += 1
                                        logger.debug(f"已删除 raw 文件：{file_path}")
                                    else:
                                        logger.error(f"删除 raw 文件失败：{file_path}")
                            except Exception as e:
                                logger.error(f"删除 raw 文件失败：{file_path}, 错误：{e}")

                        total_deleted += deleted_count
                        logger.info(f"已清理 raw 目录，删除 {deleted_count} 个文件")

            return total_deleted

        except Exception as e:
            logger.error(f"清理 raw 目录失败：{e}")
            return 0

    async def _safe_remove_file(self, file_path: str) -> bool:
        """安全删除文件。
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否删除成功
        """
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"已删除文件：{file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除文件失败 {file_path}: {e}")
            return False

    async def cleanup(self):
        """清理资源。"""
        if self._cleaned:
            return

        self._cleaned = True
        
        # 关闭共享的 Session
        await self._close_session()
        
        logger.debug("EventHandler 资源已清理")

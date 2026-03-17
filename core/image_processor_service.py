import asyncio
import hashlib
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

try:
    from PIL import Image as PILImage

    try:
        LANCZOS = PILImage.Resampling.LANCZOS
    except AttributeError:
        LANCZOS = PILImage.LANCZOS
except Exception:
    PILImage = None
    LANCZOS = None

try:
    import numpy as np
except Exception:
    np = None


class ImageProcessorService:
    """图片处理服务类，负责处理所有与图片相关的操作。"""

    # 缓存常量
    CACHE_EXPIRE_TIME = 3600  # 缓存过期时间（秒）
    IMAGE_CACHE_MAX_SIZE = 500  # 最大缓存条目数

    def __init__(self, plugin_instance):
        """初始化图片处理服务。

        Args:
            plugin_instance: StealerPlugin 实例，用于访问插件的配置和服务
        """
        self.plugin = plugin_instance
        self.plugin_config = plugin_instance.plugin_config

        self.cosplay_dir = self.plugin_config.cosplay_dir if self.plugin_config else None

        # 图片检测缓存
        self._image_cache: dict[str, dict] = {}
        self._image_cache_max_size = self.IMAGE_CACHE_MAX_SIZE
        self._cache_expire_time = self.CACHE_EXPIRE_TIME

    async def detect_cosplay_image(
        self,
        event: AstrMessageEvent | None,
        file_path: str,
    ) -> tuple[bool, str]:
        """检测图片是否为女装图片。

        Args:
            event: 消息事件
            file_path: 图片路径

        Returns:
            tuple[bool, str]: (是否为女装图片，检测理由)
        """
        # 检查配置是否启用
        if not getattr(self.plugin_config, "save_cosplay_images", False):
            return False, ""

        base_path = Path(file_path)
        if not base_path.exists():
            logger.warning(f"图片文件不存在：{file_path}")
            return False, ""

        # 计算哈希用于缓存
        hash_val = await self._compute_hash(file_path)
        
        # 如果哈希计算失败，跳过缓存
        if not hash_val:
            logger.warning(f"无法计算图片哈希，跳过缓存：{file_path}")
            hash_val = f"fallback_{time.time()}"
        
        cache_key = f"cosplay_{hash_val}"

        # 检查缓存
        if cache_key in self._image_cache:
            cached = self._image_cache[cache_key]
            if time.time() - cached.get("timestamp", 0) < self._cache_expire_time:
                logger.debug(f"女装检测缓存命中：{hash_val[:8]}")
                return cached.get("is_cosplay", False), cached.get("reason", "")

        # 使用视觉模型检测
        try:
            # 获取女装识别专用模型，如果未配置则使用默认视觉模型
            cosplay_provider = getattr(
                self.plugin_config, "cosplay_vision_provider_id", ""
            ) or getattr(self.plugin_config, "vision_provider_id", "")

            # 调用 VLM 时使用专用 provider
            result = await self._call_vision_model(
                event=event,
                img_path=file_path,
                prompt=self._get_cosplay_detection_prompt(),
                provider_id=cosplay_provider or None,  # 传递 provider_id
            )

            # 解析结果
            is_cosplay, reason = self._parse_cosplay_result(result)

            # 缓存结果（仅在哈希有效时）
            if hash_val and not hash_val.startswith("fallback_"):
                self._image_cache[cache_key] = {
                    "is_cosplay": is_cosplay,
                    "reason": reason,
                    "timestamp": time.time(),
                }
                self._evict_image_cache()

            logger.info(f"女装检测结果：{file_path} -> {is_cosplay} ({reason})")
            return is_cosplay, reason

        except Exception as e:
            logger.error(f"女装检测失败 [{file_path}]: {e}")
            return False, f"检测失败：{str(e)}"

    def _get_cosplay_detection_prompt(self) -> str:
        """获取女装图片检测提示词。

        使用宽松的识别策略，宁可误判也不要漏掉。
        """
        return """请判断这张图片中的人物是否穿着女性化服装或进行女装 cos。

识别标准（满足任一条件即可）：
1. 穿着明显的女性服装（裙子、女仆装、洛丽塔、JK 制服、旗袍等）
2. 穿着暴露的服装（比基尼、泳装、透视装等）
3. 穿着可爱的女性化服装（可爱系、萌系服装）
4. 化着女性妆容或戴着女性假发
5. 摆出女性化姿势或动作

注意：
- 请宽松判断，宁可误判也不要漏掉
- 不要求 100% 确定，只要有女性化特征即可
- 包括男性穿女装的情况

请按以下格式回答：
判断结果 (是/否)|理由 (简短描述服装特征)

示例：
是 | 穿着黑色丝袜和短裙，女性化特征明显
是 | 穿着白色蕾丝女仆装，典型女装打扮
否 | 穿着普通男装 T 恤牛仔裤
是 | 虽然可能是男性，但穿着粉色洛丽塔裙装"""

    def _parse_cosplay_result(self, result: str) -> tuple[bool, str]:
        """解析女装检测结果。

        Args:
            result: 模型返回的文本

        Returns:
            tuple[bool, str]: (是否为女装，理由)
        """
        try:
            # 清理结果
            result = result.strip()
            lines = [line.strip() for line in result.split("\n") if line.strip()]

            if not lines:
                return False, "无有效响应"

            # 尝试解析格式：判断结果 | 理由
            first_line = lines[0]
            if "|" in first_line:
                parts = first_line.split("|", 1)
                judgment = parts[0].strip().lower()
                reason = parts[1].strip() if len(parts) > 1 else ""

                # 判断是否为女装
                is_cosplay = any(
                    keyword in judgment
                    for keyword in ["是", "yes", "true", "有", "穿着"]
                )

                # 如果没有明确理由，从全文提取
                if not reason:
                    reason = result[:100]

                return is_cosplay, reason
            else:
                # 没有分隔符，检查是否包含肯定关键词
                is_cosplay = any(
                    keyword in result
                    for keyword in ["是", "yes", "穿着", "女装", "女性", "裙子"]
                )
                return is_cosplay, result[:100]

        except Exception as e:
            logger.error(f"解析女装检测结果失败：{e}")
            return False, f"解析失败：{str(e)}"

    def _sanitize_filename(self, name: str) -> str:
        """净化文件名，移除危险字符。

        Args:
            name: 原始文件名

        Returns:
            str: 净化后的文件名
        """
        # 移除或替换危险字符
        dangerous_chars = ['/', '\\', '..', ':', '*', '?', '"', '<', '>', '|']
        sanitized = name
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, '_')
        
        # 限制长度
        return sanitized[:50] if len(sanitized) > 50 else sanitized

    async def save_cosplay_image(
        self,
        event: AstrMessageEvent,
        file_path: str,
        is_temp: bool = False,
    ) -> tuple[bool, str]:
        """保存女装图片到对应目录。

        目录结构：cosplay/群号/群员 QQ 号_QQ 名/图片文件

        Args:
            event: 消息事件
            file_path: 图片路径
            is_temp: 是否为临时文件

        Returns:
            tuple[bool, str]: (是否成功，保存路径或错误信息)
        """
        try:
            # 获取群号和群员信息
            group_id = self.plugin_config.get_group_id(event)
            if not group_id:
                return False, "无法获取群号"

            # 获取发送者信息（直接使用 event 的方法）
            sender_id = event.get_sender_id() or ""
            sender_name = event.get_sender_name() or sender_id

            if not sender_id:
                return False, "无法获取发送者 ID"

            # 净化文件名，防止路径注入
            sender_name = self._sanitize_filename(sender_name)

            # 构建保存目录：cosplay/群号/群员 QQ 号_QQ 名
            user_dir = self.plugin_config.cosplay_dir / group_id / f"{sender_id}_{sender_name}"

            try:
                await asyncio.to_thread(user_dir.mkdir, parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"创建目录失败 {user_dir}: {e}")
                return False, f"创建目录失败：{str(e)}"

            # 计算待保存图片的哈希值
            new_image_hash = await self._compute_hash(file_path)
            if not new_image_hash:
                logger.warning("无法计算图片哈希值")
                return False, "无法计算图片哈希值"

            # 检查目标目录中是否已存在相同图片（通过哈希对比）
            is_duplicate, existing_file = await self._check_duplicate_by_hash(
                user_dir, new_image_hash
            )
            if is_duplicate:
                logger.info(f"检测到重复图片（哈希相同），已跳过保存：{existing_file}")
                # 如果是临时文件，需要删除
                if is_temp and os.path.exists(file_path):
                    await asyncio.to_thread(os.remove, file_path)
                return True, f"跳过重复图片：{existing_file}"

            # 生成文件名（包含哈希值前 8 位，便于识别重复）
            base_path = Path(file_path)
            ext = base_path.suffix.lower() or ".jpg"
            timestamp = int(time.time())
            filename = f"{timestamp}_{new_image_hash[:8]}{ext}"
            save_path = user_dir / filename

            # 复制文件到目标目录
            try:
                if is_temp:
                    await asyncio.to_thread(shutil.move, file_path, save_path)
                else:
                    await asyncio.to_thread(shutil.copy2, file_path, save_path)
            except FileNotFoundError:
                logger.warning(f"保存女装图片时发现文件已被删除：{file_path}")
                return False, "文件已被删除"

            logger.info(f"已保存女装图片：{save_path}")
            
            # 写入持久化记录（异步）
            try:
                record = {
                    "save_path": str(save_path),
                    "group_id": group_id,
                    "user_id": sender_id,
                    "user_name": sender_name,
                    "hash": new_image_hash,
                    "timestamp": datetime.now().isoformat(),
                    "file_size": save_path.stat().st_size if save_path.exists() else 0
                }
                await self.plugin_config.add_image_record(record)
                logger.debug(f"已写入图片记录：{record['save_path']}")
            except Exception as e:
                logger.error(f"写入图片记录失败：{e}")
            
            return True, str(save_path)

        except Exception as e:
            logger.error(f"保存女装图片失败：{e}")
            return False, f"保存失败：{str(e)}"

    async def _call_vision_model(
        self, event: AstrMessageEvent | None, img_path: str, prompt: str, provider_id: str | None = None
    ) -> str:
        """调用视觉模型分析图片。

        Args:
            event: 消息事件（用于 provider 解析）
            img_path: 图片绝对路径
            prompt: 提示词
            provider_id: 指定的 provider ID（可选）

        Returns:
            str: 模型响应文本

        Raises:
            ValueError: 未配置视觉模型
            FileNotFoundError: 图片文件不存在
            Exception: 模型调用失败
        """
        # 路径规范化
        img_path_obj = Path(img_path)
        if not img_path_obj.is_absolute():
            data_dir = getattr(self.plugin_config, "data_dir", None)
            img_path_obj = (
                (Path(data_dir) / img_path).absolute()
                if data_dir
                else img_path_obj.absolute()
            )
        img_path = str(img_path_obj)

        if not os.path.exists(img_path):
            raise FileNotFoundError(f"图片文件不存在：{img_path}")

        # 解析 provider
        if not provider_id:
            provider_id = await self._resolve_vision_provider(event)
        if not provider_id:
            raise ValueError(
                "未配置视觉模型，无法进行图片分析。"
                "请在插件配置中设置 vision_provider_id。"
            )

        # 处理 GIF 动图：提取多帧拼接
        temp_file = None
        try:
            actual_img_path, is_animated = await self._prepare_image_for_vlm(img_path)
            if actual_img_path != img_path:
                temp_file = actual_img_path

            # 构建图片 URL（file:// 协议）
            file_url = f"file:///{actual_img_path.replace(chr(92), '/')}"

            result = await self._do_vlm_call(provider_id, prompt, file_url)
            return result
        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    logger.debug(f"已清理临时拼接图：{temp_file}")
                except Exception as e:
                    logger.warning(f"清理临时文件失败：{e}")

    async def _prepare_image_for_vlm(self, img_path: str) -> tuple[str, bool]:
        """为 VLM 分析准备图片，对动图提取多帧拼接。

        Args:
            img_path: 原始图片路径

        Returns:
            tuple[str, bool]: (准备好的图片路径，是否为动图拼接)
        """
        # 只处理 GIF 文件
        if not img_path.lower().endswith(".gif"):
            return img_path, False

        if PILImage is None or np is None:
            return img_path, False

        try:
            # 检测是否为动图
            def _check_animated(fp: str) -> tuple[bool, int, int, int]:
                with PILImage.open(fp) as im:
                    is_animated = bool(getattr(im, "is_animated", False))
                    n_frames = int(getattr(im, "n_frames", 1) or 1)
                    width, height = im.size
                    return is_animated, n_frames, width, height

            is_animated, n_frames, width, height = await asyncio.to_thread(
                _check_animated, img_path
            )

            # 非动图或帧数太少，直接返回原路径
            if not is_animated or n_frames <= 1:
                return img_path, False

            # 动图处理：提取关键帧并横向拼接
            MAX_FRAMES = 12
            TARGET_HEIGHT = 256
            SIMILARITY_THRESHOLD = 1000.0

            # 计算缩放比例
            scale = TARGET_HEIGHT / height if height > TARGET_HEIGHT else 1.0
            frame_width = int(width * scale)
            frame_height = TARGET_HEIGHT

            def _extract_and_combine(fp: str) -> tuple[str, int]:
                frames = []
                last_selected_np = None

                with PILImage.open(fp) as im:
                    all_frames = []
                    for idx in range(n_frames):
                        im.seek(idx)
                        frame = im.convert("RGBA")
                        if scale < 1.0:
                            frame = frame.resize((frame_width, frame_height), LANCZOS)
                        all_frames.append(frame)

                # 相似帧过滤
                for frame in all_frames:
                    frame_np = np.array(frame, dtype=np.float32)

                    if last_selected_np is None:
                        frames.append(frame)
                        last_selected_np = frame_np
                    else:
                        mse = np.mean((frame_np - last_selected_np) ** 2)
                        if mse > SIMILARITY_THRESHOLD:
                            frames.append(frame)
                            last_selected_np = frame_np

                # 如果过滤后帧数太少，保留更多帧
                if len(frames) < 3 and len(all_frames) >= 3:
                    step = max(1, len(all_frames) // 6)
                    frames = [all_frames[i] for i in range(0, len(all_frames), step)][:6]

                # 限制最大帧数
                if len(frames) > MAX_FRAMES:
                    step = len(frames) / MAX_FRAMES
                    frames = [frames[int(i * step)] for i in range(MAX_FRAMES)]

                # 横向拼接所有帧
                total_width = frame_width * len(frames)
                combined = PILImage.new("RGBA", (total_width, frame_height), (0, 0, 0, 255))

                for i, frame in enumerate(frames):
                    combined.paste(frame, (i * frame_width, 0), frame)

                # 保存临时文件
                import tempfile

                temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                os.close(temp_fd)
                combined_rgb = PILImage.new("RGB", combined.size, (0, 0, 0))
                if combined.mode == "RGBA":
                    combined_rgb.paste(combined, mask=combined.split()[3])
                else:
                    combined_rgb.paste(combined)
                combined_rgb.save(temp_path, "JPEG", quality=90)

                return temp_path, len(frames)

            temp_path, actual_frames = await asyncio.to_thread(
                _extract_and_combine, img_path
            )
            logger.debug(
                f"GIF 动图拼接完成：{n_frames} 帧 -> {actual_frames} 帧，"
                f"输出尺寸：{frame_width * actual_frames}x{frame_height}"
            )
            return temp_path, True

        except Exception as e:
            logger.warning(f"GIF 动图帧提取失败，使用原图：{e}")
            return img_path, False

    async def _do_vlm_call(self, provider_id: str, prompt: str, file_url: str) -> str:
        """执行 VLM 调用（带重试）。

        Args:
            provider_id: 提供商 ID
            prompt: 提示词
            file_url: 文件 URL

        Returns:
            str: 模型响应文本
        """
        # 重试配置
        max_retries = 3
        retry_delay = 1.0
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                logger.debug(
                    f"调用 VLM (尝试 {attempt + 1}/{max_retries}), "
                    f"provider={provider_id}, 图片={file_url}"
                )
                result = await self.plugin.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    image_urls=[file_url],
                )

                text = (result.completion_text or "").strip() if result else ""
                if text:
                    logger.debug(f"VLM 响应：{text[:200]}")
                    return text

                logger.warning("VLM 返回空响应")
                last_error = Exception("VLM 返回空响应")

            except Exception as e:
                last_error = e
                logger.error(f"VLM 调用失败 ({attempt + 1}/{max_retries}): {e}")

            # 指数退避
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2**attempt))

        raise Exception(
            f"视觉模型调用失败（已重试{max_retries}次）: {last_error}"
        ) from last_error

    async def _compute_hash(self, file_path: str) -> str:
        """计算文件的 SHA256 哈希值。

        Args:
            file_path: 文件路径

        Returns:
            str: SHA256 哈希值
        """

        def _sync_hash(fp: str) -> str:
            hasher = hashlib.sha256()
            with open(fp, "rb") as f:
                hasher.update(f.read())
            return hasher.hexdigest()

        try:
            return await asyncio.to_thread(_sync_hash, file_path)
        except FileNotFoundError as e:
            logger.error(f"文件不存在：{e}")
            return ""
        except PermissionError as e:
            logger.error(f"文件权限错误：{e}")
            return ""
        except Exception as e:
            logger.error(f"计算哈希值失败：{e}")
            return ""

    async def _check_duplicate_by_hash(
        self, target_dir: Path, new_hash: str
    ) -> tuple[bool, str | None]:
        """通过哈希值检查目录中是否已存在重复图片。

        Args:
            target_dir: 目标目录
            new_hash: 新图片的哈希值

        Returns:
            tuple[bool, str | None]: (是否重复，已存在的文件路径)
        """
        if not target_dir.exists():
            return False, None

        try:
            # 遍历目录中的所有文件
            for existing_file in target_dir.iterdir():
                if not existing_file.is_file():
                    continue

                # 只检查图片文件
                if existing_file.suffix.lower() not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                    continue

                # 计算已存在文件的哈希值
                existing_hash = await self._compute_hash(str(existing_file))
                if existing_hash and existing_hash == new_hash:
                    logger.debug(f"发现重复图片：{existing_file} (哈希：{new_hash[:8]})")
                    return True, str(existing_file)

            return False, None

        except Exception as e:
            logger.error(f"检查重复图片失败：{e}")
            return False, None

    def _evict_image_cache(self) -> None:
        """淘汰 _image_cache 中最旧的条目，保持在最大容量以内。"""
        if len(self._image_cache) <= self._image_cache_max_size:
            return
        # 按 timestamp 排序，保留最新的一半
        sorted_items = sorted(
            self._image_cache.items(),
            key=lambda kv: kv[1].get("timestamp", 0),
        )
        keep = sorted_items[len(sorted_items) // 2 :]
        self._image_cache.clear()
        self._image_cache.update(keep)
        logger.debug(f"_image_cache 淘汰完成，当前 {len(self._image_cache)} 条")

    def cleanup(self):
        """清理资源。"""
        self._image_cache.clear()
        logger.debug("ImageProcessorService 资源已清理")

    async def _resolve_vision_provider(self, event=None) -> str | None:
        """解析视觉模型 provider ID。

        Returns:
            str | None: provider ID，如果未配置则返回 None
        """
        # 优先使用插件配置的 vision_provider_id
        provider_id = getattr(self.plugin_config, "vision_provider_id", "")
        if provider_id:
            return provider_id

        # 尝试从框架获取默认图片描述模型
        try:
            from astrbot.api import all_config_helper

            if all_config_helper:
                default_vlm = getattr(
                    all_config_helper.config, "default_image_caption_provider_id", ""
                )
                if default_vlm:
                    return default_vlm
        except Exception:
            pass

        return None

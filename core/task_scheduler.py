import asyncio
from datetime import datetime, timedelta
from typing import Any

from astrbot.api import logger


class TaskScheduler:
    """定时任务调度器，负责定时执行任务。"""

    def __init__(self, plugin_instance: Any):
        """初始化任务调度器。

        Args:
            plugin_instance: Main 实例，用于访问插件配置和服务
        """
        self.plugin = plugin_instance
        self.smtp_config = plugin_instance.plugin_config.smtp
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """启动定时任务调度器。"""
        if self._running:
            logger.warning("[调度器] 已经在运行中")
            return

        if not self.smtp_config.enabled:
            logger.info("[调度器] 邮件推送未启用，跳过启动")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_scheduler())
        logger.info(f"[调度器] 已启动，将在每天 {self.smtp_config.send_time} 发送日报")

    async def stop(self):
        """停止定时任务调度器。"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("[调度器] 已停止")

    async def _run_scheduler(self):
        """运行调度器主循环。"""
        try:
            while self._running:
                try:
                    # 解析发送时间（带异常处理）
                    try:
                        time_str = self.smtp_config.send_time
                        # 验证格式
                        if not time_str or ':' not in time_str:
                            raise ValueError(f"时间格式错误：{time_str}")
                        
                        parts = time_str.split(':')
                        if len(parts) != 2:
                            raise ValueError(f"时间格式错误：{time_str}")
                        
                        hour, minute = map(int, parts)
                        # 验证时间范围
                        if not (0 <= hour <= 23 and 0 <= minute <= 59):
                            raise ValueError(f"时间超出范围：{hour}:{minute}")
                    except (ValueError, AttributeError) as e:
                        logger.error(f"[调度器] 发送时间配置非法：{self.smtp_config.send_time}（UTC 时间）, 使用默认值 08:00")
                        hour, minute = 8, 0
                    
                    now = datetime.utcnow()
                    scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                    # 如果当前时间已经过了今天的发送时间，则设置为明天
                    if now >= scheduled_time:
                        scheduled_time += timedelta(days=1)

                    # 计算等待时间
                    wait_seconds = (scheduled_time - now).total_seconds()
                    logger.info(f"[调度器] 下次发送时间（UTC）：{scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}, "
                               f"等待 {wait_seconds:.0f} 秒")

                    # 等待到发送时间
                    await asyncio.sleep(wait_seconds)

                    if not self._running:
                        break

                    # 执行发送任务
                    logger.info("[调度器] 开始发送每日日报")
                    await self._send_daily_report()

                except asyncio.CancelledError:
                    logger.info("[调度器] 任务被取消")
                    break
                except Exception as e:
                    logger.error(f"[调度器] 执行任务失败：{e}", exc_info=True)
                    # 等待 1 分钟后重试
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("[调度器] 调度器被取消")
        except Exception as e:
            logger.error(f"[调度器] 调度器异常：{e}", exc_info=True)

    async def _send_daily_report(self):
        """发送每日日报。"""
        try:
            # 获取日报服务
            from .daily_report_service import DailyReportService
            from .smtp_service import SMTPService

            daily_report = DailyReportService(self.plugin)
            smtp_service = SMTPService(self.plugin)

            # 获取昨日统计（异步）
            stats = await daily_report.get_yesterday_stats()

            # 生成 HTML 报告
            html_content = daily_report.generate_html_report(stats)

            # 发送邮件
            subject = f"🌟 女装图片统计日报 - {stats['date']}"
            success, error = await smtp_service.send_email(subject, html_content, html=True)

            if success:
                logger.info(f"[调度器] 日报发送成功：{stats['date']}")
            else:
                logger.error(f"[调度器] 日报发送失败：{error}")

        except Exception as e:
            logger.error(f"[调度器] 生成或发送日报失败：{e}", exc_info=True)

    async def send_daily_report_now(self) -> tuple[bool, str]:
        """立即发送每日日报（异步）。

        Returns:
            tuple[bool, str]: (是否成功，错误信息)
        """
        try:
            from .daily_report_service import DailyReportService
            from .smtp_service import SMTPService

            daily_report = DailyReportService(self.plugin)
            smtp_service = SMTPService(self.plugin)

            # 验证 SMTP 配置
            is_valid, error = smtp_service.validate_config()
            if not is_valid:
                return False, f"SMTP 配置错误：{error}"

            # 获取今日统计（异步）
            stats = await daily_report.get_today_stats()

            # 生成报告
            html_content = daily_report.generate_html_report(stats)

            # 发送邮件
            subject = f"🌟 女装图片统计日报 - {stats['date']}"
            success, error = await smtp_service.send_email(subject, html_content, html=True)

            if success:
                return True, "日报发送成功"
            else:
                return False, f"发送失败：{error}"

        except Exception as e:
            logger.error(f"[调度器] 立即发送日报失败：{e}", exc_info=True)
            return False, f"异常：{str(e)}"

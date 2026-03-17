from datetime import datetime, timedelta
from collections import defaultdict
import html
from typing import Any

from astrbot.api import logger


class DailyReportService:
    """日报生成服务类，负责生成每日统计报告。"""

    def __init__(self, plugin_instance: Any):
        """初始化日报服务。

        Args:
            plugin_instance: Main 实例，用于访问插件配置和数据
        """
        self.plugin = plugin_instance
        self.cosplay_dir = plugin_instance.plugin_config.cosplay_dir

    async def _get_stats_by_date(self, target_date: datetime) -> dict:
        """获取指定日期的统计数据（从持久化记录读取，异步）。

        Args:
            target_date: 目标日期

        Returns:
            dict: 统计数据
        """
        stats = {
            'date': target_date.strftime('%Y-%m-%d'),
            'total_images': 0,
            'total_groups': 0,
            'total_users': 0,
            'groups': defaultdict(lambda: {'users': set(), 'images': 0}),
        }

        try:
            # 从持久化记录获取指定日期的图片（异步）
            # 使用 self.plugin.plugin_config 而不是 self.plugin_config
            records = await self.plugin.plugin_config.get_image_records_by_date(target_date)
            
            for record in records:
                group_id = record.get('group_id', '')
                user_id = record.get('user_id', '')
                user_name = record.get('user_name', '')
                
                if not group_id or not user_id:
                    continue
                
                stats['total_images'] += 1
                stats['groups'][group_id]['users'].add(f"{user_id}_{user_name}")
                stats['groups'][group_id]['images'] += 1

            # 计算总数
            stats['total_groups'] = len([g for g in stats['groups'].values() if g['images'] > 0])
            stats['total_users'] = sum(len(g['users']) for g in stats['groups'].values())

            # 转换 set 为 list 以便 JSON 序列化
            for group_id in stats['groups']:
                stats['groups'][group_id]['users'] = list(stats['groups'][group_id]['users'])

        except Exception as e:
            logger.error(f"[日报] 统计 {target_date} 数据失败：{e}", exc_info=True)

        return stats

    async def get_today_stats(self) -> dict:
        """获取今日统计数据（异步）。

        Returns:
            dict: 统计数据
        """
        today = datetime.now().date()
        return await self._get_stats_by_date(today)

    async def get_yesterday_stats(self) -> dict:
        """获取昨日统计数据（异步）。

        Returns:
            dict: 统计数据
        """
        yesterday = datetime.now().date() - timedelta(days=1)
        return await self._get_stats_by_date(yesterday)

    def generate_html_report(self, stats: dict, is_test: bool = False) -> str:
        """生成 HTML 格式的日报。

        Args:
            stats: 统计数据
            is_test: 是否为测试报告

        Returns:
            str: HTML 内容
        """
        date_str = stats['date']
        if is_test:
            date_str = "测试报告"

        html_content = f"""
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #2c3e50; }}
        h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        .stat-box {{ 
            background: #ecf0f1; 
            padding: 15px; 
            margin: 10px 0; 
            border-radius: 5px;
            display: inline-block;
            margin-right: 20px;
        }}
        .stat-number {{ 
            font-size: 24px; 
            font-weight: bold; 
            color: #e74c3c;
        }}
        .stat-label {{ 
            font-size: 14px; 
            color: #7f8c8d;
        }}
        table {{ 
            border-collapse: collapse; 
            width: 100%; 
            margin: 20px 0;
        }}
        th, td {{ 
            border: 1px solid #bdc3c7; 
            padding: 10px; 
            text-align: left;
        }}
        th {{ 
            background: #3498db; 
            color: white;
        }}
        tr:nth-child(even) {{ 
            background: #ecf0f1;
        }}
        .footer {{ 
            margin-top: 30px; 
            padding-top: 20px; 
            border-top: 1px solid #bdc3c7;
            color: #7f8c8d;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <h1>🌟 女装图片保存助手 - 每日统计日报</h1>
    <p><strong>统计日期：</strong>{date_str}</p>
    
    <h2>📊 总体统计</h2>
    <div class="stat-box">
        <div class="stat-number">{stats['total_images']}</div>
        <div class="stat-label">保存图片总数</div>
    </div>
    <div class="stat-box">
        <div class="stat-number">{stats['total_groups']}</div>
        <div class="stat-label">活跃群组数</div>
    </div>
    <div class="stat-box">
        <div class="stat-number">{stats['total_users']}</div>
        <div class="stat-label">活跃用户数</div>
    </div>
    
    <h2>📈 群组详情</h2>
"""

        if stats['groups']:
            html_content += """
    <table>
        <tr>
            <th>群号</th>
            <th>活跃用户数</th>
            <th>保存图片数</th>
            <th>用户列表</th>
        </tr>
"""
            for group_id, group_data in sorted(stats['groups'].items()):
                if group_data['images'] > 0:
                    # HTML 转义，防止注入
                    safe_group_id = html.escape(group_id)
                    users = ', '.join([html.escape(u) for u in group_data['users'][:5]])
                    if len(group_data['users']) > 5:
                        users += f" 等{len(group_data['users'])}人"
                    
                    html_content += f"""
        <tr>
            <td>{safe_group_id}</td>
            <td>{len(group_data['users'])}</td>
            <td>{group_data['images']}</td>
            <td>{users}</td>
        </tr>
"""
        else:
            html_content += "<p>今日暂无保存图片</p>"

        html_content += """
    <div class="footer">
        <p>此报告由 AstrBot 女装图片保存助手自动生成</p>
        <p>报告生成时间：""" + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</p>
    </div>
</body>
</html>
"""
        return html_content

    def generate_text_report(self, stats: dict, is_test: bool = False) -> str:
        """生成纯文本格式的日报。

        Args:
            stats: 统计数据
            is_test: 是否为测试报告

        Returns:
            str: 文本内容
        """
        date_str = stats['date']
        if is_test:
            date_str = "测试报告"

        text = f"""🌟 女装图片保存助手 - 每日统计日报

📅 统计日期：{date_str}

📊 总体统计：
  • 保存图片总数：{stats['total_images']} 张
  • 活跃群组数：{stats['total_groups']} 个
  • 活跃用户数：{stats['total_users']} 人

📈 群组详情：
"""

        if stats['groups']:
            for group_id, group_data in sorted(stats['groups'].items()):
                if group_data['images'] > 0:
                    text += f"""
【群 {group_id}】
  - 保存图片：{group_data['images']} 张
  - 活跃用户：{len(group_data['users'])} 人
  - 用户列表：{', '.join(group_data['users'][:10])}{'...' if len(group_data['users']) > 10 else ''}
"""
        else:
            text += "\n今日暂无保存图片\n"

        text += f"\n报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        text += "\n此报告由 AstrBot 女装图片保存助手自动生成\n"

        return text

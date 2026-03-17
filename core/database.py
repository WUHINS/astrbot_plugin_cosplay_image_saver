"""
SQLite 数据库管理模块（异步版本）
负责图片记录的存储、查询和自动清理
使用连接池优化性能
"""
import sqlite3
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager

from astrbot.api import logger


class Database:
    """SQLite 数据库管理类（异步版本）"""
    
    def __init__(self, db_path: Path):
        """初始化数据库
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        # 连接池配置（使用 asyncio.Lock）
        self._pool_size = 5  # 连接池大小
        self._pool: list[sqlite3.Connection] = []
        self._pool_lock = asyncio.Lock()  # 使用 asyncio.Lock
        
        # 同步初始化数据库（使用同步方法）
        self._init_db_sync()
    
    def _init_db_sync(self):
        """同步初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            # 创建图片记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS image_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    save_path TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_name TEXT,
                    hash TEXT NOT NULL,
                    file_size INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(save_path)
                )
            """)
            
            # 创建索引，加速查询
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON image_records(created_at)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_user 
                ON image_records(group_id, user_id)
            """)
            
            conn.commit()
            logger.debug(f"[Database] 数据库初始化完成：{self.db_path}")
        finally:
            conn.close()
    
    @asynccontextmanager
    async def get_connection(self):
        """异步获取数据库连接（带连接池）"""
        conn = None
        try:
            # 尝试从连接池获取
            async with self._pool_lock:
                if self._pool:
                    conn = self._pool.pop()
                else:
                    # 创建新连接
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    conn.row_factory = sqlite3.Row
            
            yield conn
        finally:
            # 归还连接到连接池
            if conn:
                async with self._pool_lock:
                    if len(self._pool) < self._pool_size:
                        self._pool.append(conn)
                    else:
                        conn.close()
    
    @asynccontextmanager
    async def get_cursor(self):
        """异步获取数据库游标（上下文管理器）"""
        async with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
    
    async def add_record(self, record: dict) -> bool:
        """添加图片记录（异步）
        
        Args:
            record: 记录字典，包含 save_path, group_id, user_id, user_name, hash, file_size
            
        Returns:
            bool: 是否添加成功
        """
        try:
            async with self.get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO image_records 
                    (save_path, group_id, user_id, user_name, hash, file_size, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    record['save_path'],
                    record['group_id'],
                    record['user_id'],
                    record.get('user_name', ''),
                    record['hash'],
                    record.get('file_size', 0),
                    record.get('timestamp', datetime.now().isoformat())
                ))
            logger.debug(f"[Database] 添加记录成功：{record['save_path']}")
            return True
        except Exception as e:
            logger.error(f"[Database] 添加记录失败：{e}")
            return False
    
    async def get_records_by_date(self, target_date: datetime.date) -> list[dict]:
        """获取指定日期的图片记录（异步）
        
        Args:
            target_date: 目标日期
            
        Returns:
            list[dict]: 图片记录列表
        """
        try:
            # 计算日期范围
            start_datetime = datetime.combine(target_date, datetime.min.time())
            end_datetime = start_datetime + timedelta(days=1)
            
            async with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM image_records
                    WHERE created_at >= ? AND created_at < ?
                    ORDER BY created_at ASC
                """, (start_datetime.isoformat(), end_datetime.isoformat()))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[Database] 查询记录失败：{e}")
            return []
    
    async def get_all_records(self) -> list[dict]:
        """获取所有图片记录（异步）
        
        Returns:
            list[dict]: 所有图片记录
        """
        try:
            async with self.get_cursor() as cursor:
                cursor.execute("SELECT * FROM image_records ORDER BY created_at DESC")
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[Database] 获取所有记录失败：{e}")
            return []
    
    async def cleanup_old_records(self, retention_days: int = 7) -> int:
        """清理旧记录（异步）
        
        Args:
            retention_days: 保留天数，默认 7 天
            
        Returns:
            int: 删除的记录数
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            async with self.get_cursor() as cursor:
                cursor.execute("""
                    DELETE FROM image_records
                    WHERE created_at < ?
                """, (cutoff_date.isoformat(),))
                
                deleted_count = cursor.rowcount
                logger.info(f"[Database] 已清理 {deleted_count} 条 {retention_days} 天前的记录")
                return deleted_count
        except Exception as e:
            logger.error(f"[Database] 清理旧记录失败：{e}")
            return 0
    
    async def get_record_count(self) -> int:
        """获取记录总数（异步）
        
        Returns:
            int: 记录总数
        """
        try:
            async with self.get_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM image_records")
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"[Database] 获取记录总数失败：{e}")
            return 0
    
    async def get_stats_summary(self, start_date: datetime, end_date: datetime) -> dict:
        """获取统计摘要（异步）
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            dict: 统计摘要
        """
        try:
            async with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_images,
                        COUNT(DISTINCT group_id) as total_groups,
                        COUNT(DISTINCT user_id) as total_users
                    FROM image_records
                    WHERE created_at >= ? AND created_at < ?
                """, (start_date.isoformat(), end_date.isoformat()))
                
                row = cursor.fetchone()
                return dict(row) if row else {
                    'total_images': 0,
                    'total_groups': 0,
                    'total_users': 0
                }
        except Exception as e:
            logger.error(f"[Database] 获取统计摘要失败：{e}")
            return {
                'total_images': 0,
                'total_groups': 0,
                'total_users': 0
            }

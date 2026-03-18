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
        self._closed = False  # 连接池关闭标志
        
        # 同步初始化数据库（使用同步方法）
        self._init_db_sync()
    
    def _init_db_sync(self):
        """同步初始化数据库表结构（含迁移逻辑）"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='image_records'
            """)
            table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                # 新数据库，直接创建双时间戳表
                self._create_new_table(cursor)
                logger.info(f"[Database] 创建新数据库：{self.db_path}")
            else:
                # 旧数据库，检查是否需要迁移
                migrated = self._migrate_legacy_table(cursor)
                if migrated:
                    logger.info(f"[Database] 数据库已迁移到双时间戳格式：{self.db_path}")
                else:
                    logger.debug(f"[Database] 数据库已是最新格式：{self.db_path}")
            
            conn.commit()
            logger.debug(f"[Database] 数据库初始化完成：{self.db_path}")
        finally:
            conn.close()
    
    def _create_new_table(self, cursor):
        """创建新的双时间戳表结构"""
        cursor.execute("""
            CREATE TABLE image_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                save_path TEXT NOT NULL,
                group_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                hash TEXT NOT NULL,
                file_size INTEGER,
                created_at_utc TIMESTAMP NOT NULL,
                created_at_local TIMESTAMP NOT NULL,
                UNIQUE(save_path)
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at_utc 
            ON image_records(created_at_utc)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at_local 
            ON image_records(created_at_local)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_user 
            ON image_records(group_id, user_id)
        """)
    
    def _migrate_legacy_table(self, cursor) -> bool:
        """迁移旧数据库表结构（如果有必要）
        
        Returns:
            bool: 是否执行了迁移
        """
        # 检查现有表的列
        cursor.execute("PRAGMA table_info(image_records)")
        columns = {row[1] for row in cursor.fetchall()}
        
        # 检查是否已经是双时间戳格式
        if 'created_at_utc' in columns and 'created_at_local' in columns:
            return False  # 已是最新格式，无需迁移
        
        # 检查是否有旧的 created_at 字段
        if 'created_at' not in columns:
            logger.warning(f"[Database] 表结构异常，缺少时间字段")
            return False
        
        # 获取当前时区偏移（用于转换旧数据）
        now = datetime.now()
        local_tz = now.astimezone().tzinfo
        utc_offset = local_tz.utcoffset(now).total_seconds() / 3600  # 小时数
        utc_offset_str = f"{int(utc_offset)} hours"
        
        # 执行迁移：重命名表 -> 创建新表 -> 复制数据 -> 删除旧表
        logger.info(f"[Database] 开始迁移旧数据库表结构（当前时区：UTC{utc_offset:+.0f}）...")
        
        # 1. 重命名旧表
        cursor.execute("ALTER TABLE image_records RENAME TO image_records_old")
        
        # 2. 创建新表
        self._create_new_table(cursor)
        
        # 3. 复制数据（将旧时间字段转换为双时间戳）
        # 假设旧数据是当前时区的本地时间，转换为 UTC
        if utc_offset >= 0:
            # 东时区：UTC = 本地时间 - 偏移
            utc_conversion = f"datetime(created_at, '-{int(utc_offset)} hours')"
        else:
            # 西时区：UTC = 本地时间 + |偏移|
            utc_conversion = f"datetime(created_at, '+{abs(int(utc_offset))} hours')"
        
        cursor.execute(f"""
            INSERT INTO image_records (
                id, save_path, group_id, user_id, user_name, hash, file_size,
                created_at_utc, created_at_local
            )
            SELECT 
                id, save_path, group_id, user_id, user_name, hash, file_size,
                -- 转换为 UTC 时间
                {utc_conversion} as created_at_utc,
                -- 转换为 ISO 8601 本地时间带时区
                strftime('%Y-%m-%dT%H:%M:%S', datetime(created_at, 'localtime')) || 
                printf('%+03d:00', {int(utc_offset)}) as created_at_local
            FROM image_records_old
        """)
        
        migrated_count = cursor.rowcount
        
        # 4. 删除旧表
        cursor.execute("DROP TABLE image_records_old")
        
        logger.info(f"[Database] 迁移完成，共迁移 {migrated_count} 条记录（时区：UTC{utc_offset:+.0f}）")
        return True
    
    @asynccontextmanager
    async def get_connection(self):
        """异步获取数据库连接（带连接池）"""
        conn = None
        pool_size_before = len(self._pool)
        try:
            # 尝试从连接池获取
            async with self._pool_lock:
                if self._pool:
                    conn = self._pool.pop()
                    logger.debug(f"[Database] 从连接池获取连接，池大小：{pool_size_before-1} → {len(self._pool)}")
                else:
                    # 创建新连接
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    conn.row_factory = sqlite3.Row
                    logger.debug(f"[Database] 创建新数据库连接，池大小：0")
            
            yield conn
        finally:
            # 归还连接到连接池
            if conn:
                async with self._pool_lock:
                    if len(self._pool) < self._pool_size:
                        self._pool.append(conn)
                        logger.debug(f"[Database] 连接归还到池，池大小：{len(self._pool)}")
                    else:
                        conn.close()
                        logger.debug(f"[Database] 连接池已满 ({self._pool_size})，关闭连接")
    
    @asynccontextmanager
    async def get_cursor(self):
        """异步获取数据库游标（上下文管理器）"""
        async with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                await asyncio.to_thread(conn.commit)
            except Exception:
                await asyncio.to_thread(conn.rollback)
                raise  # 使用裸 raise 保留完整 traceback
    
    async def close(self):
        """关闭数据库连接池，释放所有资源"""
        if self._closed:
            return
        
        self._closed = True
        async with self._pool_lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"[Database] 关闭连接失败：{e}")
            self._pool.clear()
        logger.info(f"[Database] 数据库连接池已关闭")
    
    async def add_record(self, record: dict) -> bool:
        """添加图片记录（异步）
        
        Args:
            record: 记录字典，包含 save_path, group_id, user_id, user_name, hash, file_size
            
        Returns:
            bool: 是否添加成功
        """
        try:
            async with self.get_cursor() as cursor:
                await asyncio.to_thread(
                    cursor.execute,
                    """
                    INSERT OR REPLACE INTO image_records 
                    (save_path, group_id, user_id, user_name, hash, file_size, created_at_utc, created_at_local)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record['save_path'],
                        record['group_id'],
                        record['user_id'],
                        record.get('user_name', ''),
                        record['hash'],
                        record.get('file_size', 0),
                        datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),  # ISO 8601 UTC 格式
                        datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')  # ISO 8601 本地时间带时区
                    )
                )
            logger.debug(f"[Database] 添加记录成功：{record['save_path']}")
            return True
        except Exception as e:
            logger.error(f"[Database] 添加记录失败：{e}")
            return False
    
    async def get_records_by_date(self, target_date: datetime.date, use_local_time: bool = True) -> list[dict]:
        """获取指定日期的图片记录（异步）
        
        Args:
            target_date: 目标日期
            use_local_time: 是否使用本地时间查询（默认 True，跨日统计更准确）
            
        Returns:
            list[dict]: 图片记录列表
        """
        try:
            # 计算日期范围（使用 ISO 8601 格式）
            start_datetime = datetime.combine(target_date, datetime.min.time())
            end_datetime = start_datetime + timedelta(days=1)
            
            # 选择时间字段和格式化方式
            time_field = "created_at_local" if use_local_time else "created_at_utc"
            time_format = "本地时间" if use_local_time else "UTC 时间"
            
            # ISO 8601 格式比较（字符串比较即可）
            start_str = start_datetime.strftime('%Y-%m-%dT00:00:00')
            end_str = end_datetime.strftime('%Y-%m-%dT00:00:00')
            
            async with self.get_cursor() as cursor:
                await asyncio.to_thread(
                    cursor.execute,
                    f"""
                    SELECT * FROM image_records
                    WHERE {time_field} >= ? AND {time_field} < ?
                    ORDER BY {time_field} ASC
                    """,
                    (start_str, end_str)
                )
                
                rows = await asyncio.to_thread(cursor.fetchall)
                logger.debug(f"[Database] 按{time_format}查询 {target_date} 的记录，返回 {len(rows)} 条")
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[Database] 查询记录失败：{e}")
            return []
    
    async def get_all_records(self, order_by_utc: bool = True) -> list[dict]:
        """获取所有图片记录（异步）
        
        Args:
            order_by_utc: 是否按 UTC 时间排序（默认 True）
            
        Returns:
            list[dict]: 所有图片记录
        """
        try:
            order_field = "created_at_utc" if order_by_utc else "created_at_local"
            
            async with self.get_cursor() as cursor:
                await asyncio.to_thread(
                    cursor.execute,
                    f"SELECT * FROM image_records ORDER BY {order_field} DESC"
                )
                rows = await asyncio.to_thread(cursor.fetchall)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[Database] 获取所有记录失败：{e}")
            return []
    
    async def cleanup_old_records(self, retention_days: int = 7, use_utc: bool = False) -> int:
        """清理旧记录（异步）
        
        Args:
            retention_days: 保留天数，默认 7 天
            use_utc: 是否使用 UTC 时间计算（默认 False，使用本地时间更符合用户感知）
            
        Returns:
            int: 删除的记录数
        """
        try:
            # 根据时区选择计算方式
            cutoff_dt = datetime.utcnow() if use_utc else datetime.now()
            cutoff_dt = cutoff_dt - timedelta(days=retention_days)
            
            time_field = "created_at_utc" if use_utc else "created_at_local"
            cutoff_str = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ') if use_utc else cutoff_dt.strftime('%Y-%m-%dT%H:%M:%S%z')
            
            async with self.get_cursor() as cursor:
                await asyncio.to_thread(
                    cursor.execute,
                    f"""
                    DELETE FROM image_records
                    WHERE {time_field} < ?
                    """,
                    (cutoff_str,)
                )
                
                deleted_count = cursor.rowcount
                logger.info(f"[Database] 已清理 {deleted_count} 条 {retention_days} 天前的记录（使用{'UTC' if use_utc else '本地'}时间）")
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
                await asyncio.to_thread(
                    cursor.execute,
                    "SELECT COUNT(*) as count FROM image_records"
                )
                result = await asyncio.to_thread(cursor.fetchone)
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"[Database] 获取记录总数失败：{e}")
            return 0
    
    async def check_duplicate_by_hash(self, group_id: str, user_id: str, hash_value: str, retention_days: int = 7, use_utc: bool = True) -> tuple[bool, str | None]:
        """通过哈希值检查是否存在重复图片（基于数据库查询）。
        
        Args:
            group_id: 群号
            user_id: 用户 ID
            hash_value: 图片哈希值
            retention_days: 检查最近 N 天的记录，默认 7 天
            use_utc: 是否使用 UTC 时间计算（默认 True，全球一致）
            
        Returns:
            tuple[bool, str | None]: (是否重复，已存在的文件路径)
        """
        try:
            # 根据时区选择计算方式
            cutoff_dt = datetime.utcnow() if use_utc else datetime.now()
            cutoff_dt = cutoff_dt - timedelta(days=retention_days)
            
            time_field = "created_at_utc" if use_utc else "created_at_local"
            cutoff_str = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ') if use_utc else cutoff_dt.strftime('%Y-%m-%dT%H:%M:%S%z')
            
            async with self.get_cursor() as cursor:
                await asyncio.to_thread(
                    cursor.execute,
                    f"""
                    SELECT save_path FROM image_records
                    WHERE group_id = ? AND user_id = ? AND hash = ?
                    AND {time_field} >= ?
                    ORDER BY {time_field} DESC
                    LIMIT 1
                    """,
                    (group_id, user_id, hash_value, cutoff_str)
                )
                
                result = await asyncio.to_thread(cursor.fetchone)
                if result:
                    save_path = result['save_path']
                    logger.debug(f"[Database] 发现重复图片（数据库）：{save_path} (哈希：{hash_value[:8]})")
                    return True, save_path
                
                return False, None
        except Exception as e:
            logger.error(f"[Database] 检查重复图片失败：{e}")
            return False, None
    
    async def get_stats_summary(self, start_date: datetime, end_date: datetime, use_local_time: bool = True) -> dict:
        """获取统计摘要（异步）
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            use_local_time: 是否使用本地时间统计（默认 True，跨日统计更准确）
            
        Returns:
            dict: 统计摘要
        """
        try:
            time_field = "created_at_local" if use_local_time else "created_at_utc"
            
            # ISO 8601 格式比较
            start_str = start_date.strftime('%Y-%m-%dT%H:%M:%SZ') if start_date.tzinfo else start_date.strftime('%Y-%m-%dT%H:%M:%S%z')
            end_str = end_date.strftime('%Y-%m-%dT%H:%M:%SZ') if end_date.tzinfo else end_date.strftime('%Y-%m-%dT%H:%M:%S%z')
            
            async with self.get_cursor() as cursor:
                await asyncio.to_thread(
                    cursor.execute,
                    f"""
                    SELECT 
                        COUNT(*) as total_images,
                        COUNT(DISTINCT group_id) as total_groups,
                        COUNT(DISTINCT user_id) as total_users
                    FROM image_records
                    WHERE {time_field} >= ? AND {time_field} < ?
                    """,
                    (start_str, end_str)
                )
                
                row = await asyncio.to_thread(cursor.fetchone)
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

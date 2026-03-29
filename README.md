# 🌟 女装图片保存助手 (astrbot_plugin_cosplay_image_saver)

> AstrBot 插件 - 基于 AI 视觉模型的群聊图片智能保存工具

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-1.1.0-orange.svg)](https://github.com/WUHINS/astrbot_plugin_cosplay_image_saver)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📖 简介

基于 AI 视觉模型的群聊图片智能保存插件。自动识别特定类型图片并分类存储，支持数据库持久化记录、自动去重、7 天数据清理。内置 SMTP 邮件推送和每日统计日报功能，支持多平台部署。

**核心特性**：
- ✅ AI 智能识别 - 使用 VLM 视觉语言模型
- ✅ 数据库持久化 - SQLite 记录，支持自动清理
- ✅ 智能去重 - SHA256 哈希对比
- ✅ SMTP 邮件推送 - 每日统计日报
- ✅ 全异步架构 - 连接池优化，高性能

---

## 🚀 快速开始

### 安装要求

- Python 3.10+
- AstrBot 4.10.4+
- 支持平台：aiocqhttp、aiotoucan、qq_official、gewechat

### 安装方式

#### 方式一：插件市场（推荐）

在 AstrBot 插件管理界面搜索 `astrbot_plugin_cosplay_image_saver` 并安装。

#### 方式二：手动安装

```bash
# 克隆插件到 AstrBot 插件目录
cd /path/to/AstrBot/data/plugins
git clone https://github.com/WUHINS/astrbot_plugin_cosplay_image_saver.git

# 安装依赖
cd astrbot_plugin_cosplay_image_saver
pip install -r requirements.txt

# 重启 AstrBot 并在管理界面启用插件
```

### 依赖安装

```bash
pip install -r requirements.txt
```

**依赖列表**：
- Pillow >= 10.0.0 - 图像处理
- numpy >= 1.24.0 - GIF 帧分析

---

## ⚙️ 配置说明

### 基础配置

```json
{
  "save_cosplay_images": true,
  "cosplay_detection_threshold": 0.6,
  "cosplay_vision_provider_id": "",
  "vision_provider_id": "",
  "ignore_gif": false,
  "log_full_path": false,
  "smtp": {
    "enabled": false,
    "smtp_server": "smtp.qq.com",
    "smtp_port": 587,
    "sender_email": "your_email@qq.com",
    "sender_password": "your_auth_code",
    "receiver_email": "receiver@qq.com",
    "use_tls": true,
    "send_time": "08:00"
  }
}
```

### 配置项详解

#### 图片识别配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `save_cosplay_images` | bool | `true` | 是否启用图片保存 |
| `cosplay_detection_threshold` | float | `0.6` | 识别阈值（0.3-0.9） |
| `cosplay_vision_provider_id` | string | `""` | 专用识别模型（留空使用默认） |
| `vision_provider_id` | string | `""` | 视觉模型（留空使用全局默认） |
| `ignore_gif` | bool | `false` | 是否忽略 GIF 图片 |
| `log_full_path` | bool | `false` | 是否记录完整文件路径（隐私保护） |

**识别阈值建议**：
- **0.5-0.6**（推荐）- 平衡误判和漏判
- **0.3-0.5** - 宽松模式，几乎不漏判
- **0.7-0.9** - 严格模式，只保存明显图片

**日志路径建议**：
- **false**（推荐）- 仅记录文件名，保护隐私
- **true** - 记录完整路径，便于调试

#### SMTP 邮件配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用邮件推送 |
| `smtp_server` | string | `""` | SMTP 服务器地址 |
| `smtp_port` | int | `587` | SMTP 端口 |
| `sender_email` | string | `""` | 发件人邮箱 |
| `sender_password` | string | `""` | 邮箱授权码 |
| `receiver_email` | string | `""` | 收件人邮箱 |
| `use_tls` | bool | `true` | 是否使用 TLS 加密 |
| `send_time` | string | `"08:00"` | 发送时间（24 小时制） |

**常用邮箱 SMTP 配置**：

| 邮箱 | SMTP 服务器 | 端口 | 加密 |
|------|------------|------|------|
| QQ 邮箱 | smtp.qq.com | 587 | TLS |
| 163 邮箱 | smtp.163.com | 587 | TLS |
| Gmail | smtp.gmail.com | 587 | TLS |
| Outlook | smtp-mail.outlook.com | 587 | TLS |

---

## 📧 SMTP 配置教程

### 获取邮箱授权码（以 QQ 邮箱为例）

1. 登录 QQ 邮箱网页版（mail.qq.com）
2. 进入 **设置** → **账户**
3. 开启 **POP3/SMTP 服务**
4. 点击 **生成授权码**
5. 复制授权码（不是登录密码！）

### 配置示例

```json
{
  "smtp": {
    "enabled": true,
    "smtp_server": "smtp.qq.com",
    "smtp_port": 587,
    "sender_email": "123456@qq.com",
    "sender_password": "abcdefghijklmnop",
    "receiver_email": "654321@qq.com",
    "use_tls": true,
    "send_time": "08:00"
  }
}
```

### 日报示例

**邮件主题**：🌟 女装图片统计日报 - 2026-03-17

**邮件内容**：
```
📊 总体统计
- 保存图片总数：156 张
- 活跃群组数：8 个
- 活跃用户数：45 人

📈 群组详情
- 群号 123456: 10 用户，56 张图片
- 群号 789012: 8 用户，42 张图片
...
```

---

## 🎯 使用说明

### 自动保存

插件会自动监听群聊图片，识别后保存到：

```
/AstrBot/data/plugin_data/astrbot_plugin_cosplay_image_saver/cosplay/QID [QQ 号]/时间戳_哈希值.jpg
```

### 目录结构

```
astrbot_plugin_cosplay_image_saver/
├── cosplay/
│   ├── QID 111111/
│   │   ├── 1773752809_5b644ad7.jpg
│   │   ├── 1773752810_abc12345.png
│   │   └── 1773752811_def67890.jpg
│   └── QID 222222/
│       ├── 1773752812_ghi11111.gif
│       └── 1773752813_jkl22222.jpg
├── image_records.db  # SQLite 数据库记录
└── ...
```

**说明**：
- 图片按用户 QQ 号分类存储，目录格式为 `QID [QQ 号]`
- 统计功能仍然按群聊分组，在日报中显示各群聊的活跃用户和保存图片数
- 数据库记录包含完整的群号、用户 ID 和用户名信息

### GIF 处理

- **ignore_gif = false**（默认）：处理 GIF，提取关键帧识别
- **ignore_gif = true**：跳过所有 GIF

**建议**：
- GIF 较多时建议开启 `ignore_gif`，节省识别费用
- 需要保存所有图片时关闭

---

## 🔧 技术架构

### 核心模块

```
main.py (入口)
├── EventHandler (事件处理)
│   ├── 消息监听
│   ├── 图片下载
│   └── GIF 检测
├── ImageProcessorService (图片处理)
│   ├── AI 识别
│   ├── 哈希去重
│   └── 文件保存
├── Database (数据库)
│   ├── 连接池
│   ├── 记录管理
│   └── 自动清理
├── DailyReportService (日报生成)
│   ├── 统计查询
│   └── HTML 报告
└── SMTPService (邮件推送)
    ├── TLS 加密
    └── 定时发送
```

### 数据流程

```
消息监听
  ↓
图片下载 + GIF 检测
  ↓
AI 识别（VLM）
  ↓
哈希去重检查
  ↓
保存文件 + 写入数据库
  ↓
定时统计（每日）
  ↓
SMTP 推送日报
```

### 性能优化

- ✅ **全异步架构** - 不阻塞事件循环
- ✅ **连接池管理** - 5 个数据库连接复用
- ✅ **智能去重** - SHA256 哈希对比
- ✅ **自动清理** - 7 天前记录自动删除
- ✅ **资源管理** - 完善的异常处理和日志

---

## 🛡️ 隐私与安全

- ✅ **本地存储** - 所有数据存储在本地
- ✅ **数据库加密** - SQLite 持久化记录
- ✅ **TLS 加密** - SMTP 连接加密传输
- ✅ **自动清理** - 7 天数据自动删除
- ✅ **权限控制** - 完善的异常处理

---

## ⚠️ 注意事项

### 模型费用

- 使用付费 VLM 模型会产生费用
- 建议配置 `image_processing_cooldown` 控制频率
- GIF 会提取多帧，增加识别次数

### 存储管理

- 图片会持续累积，建议定期清理
- 数据库自动保留 7 天记录
- 重要图片建议备份

### 合规使用

- 请确保在合适的群聊中使用
- 尊重他人隐私，不要滥用
- 遵守相关法律法规

---

## 📊 插件结构

```
astrbot_plugin_cosplay_image_saver/
├── core/
│   ├── config.py                  # 配置管理
│   ├── database.py                # 数据库服务
│   ├── event_handler.py           # 事件处理
│   ├── image_processor_service.py # 图片处理
│   ├── smtp_service.py            # SMTP 服务
│   ├── daily_report_service.py    # 日报生成
│   └── task_scheduler.py          # 任务调度
├── main.py                        # 插件入口
├── _conf_schema.json             # 配置 Schema
├── requirements.txt              # 依赖列表
├── metadata.yaml                 # 元数据
├── README.md                     # 文档
└── LICENSE                       # 许可证
```

---

## 📝 更新日志

### v1.1.0 (2026-03-17)

**🎉 重大更新**

- ✨ **新增 SQLite 数据库支持**
  - 持久化记录所有保存图片
  - 自动清理 7 天前数据
  - 连接池优化性能
- ✨ **新增智能去重**
  - SHA256 哈希对比
  - 避免重复保存
- ✨ **全面异步化**
  - 所有 I/O 操作异步
  - 消除事件循环阻塞
- 🐛 **修复已知问题**
  - GIF 检测逻辑优化
  - 时间解析异常处理
  - 属性访问错误修复
- 📚 **文档更新**
  - 完善配置说明
  - 新增技术架构文档

### v1.0.0 (2026-03-12)

- 🎉 初始版本发布
- ✨ AI 识别和自动保存
- ✨ 宽松判断策略
- ✨ SMTP 邮件推送

---

## 🐛 问题反馈

遇到问题或有建议？欢迎：

- 📝 提 [Issue](https://github.com/WUHINS/astrbot_plugin_cosplay_image_saver/issues)
- 💬 加入 AstrBot 交流群
- ⭐ 给项目一个 Star

---

## 📄 许可证

MIT License

Copyright (c) 2026 WUHINS

---

## 👥 作者

**WUHINS**

- GitHub: [@WUHINS](https://github.com/WUHINS)
- 项目：[astrbot_plugin_cosplay_image_saver](https://github.com/WUHINS/astrbot_plugin_cosplay_image_saver)

---

## 🙏 致谢

- [AstrBot](https://github.com/Soulter/AstrBot) - 强大的聊天机器人框架
- [Pillow](https://python-pillow.org/) - Python 图像处理库
- 所有贡献者和使用者

---

<div align="center">

**⚠️ 免责声明**

本插件仅供学习和娱乐使用。

请合理使用并遵守相关法律法规。

尊重他人隐私，不要滥用此插件。

---

Made with ❤️ by WUHINS

</div>

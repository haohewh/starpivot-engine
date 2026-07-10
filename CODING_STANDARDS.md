# 编码规范 (Coding Standards)

> 星枢引擎 (StarPivot Engine) 项目编码铁律 — 防止技术债累积

---

## 一、文件大小限制

| 文件类型 | 上限 | 超了怎么办 |
|:---------|:----:|:----------|
| 单文件 | **500 行** | 拆成模块 |
| 单个类 | **300 行** | 拆成 Mixin |
| 单个函数 | **80 行** | 提取子函数 |

> **原因：** 之前 db.py 堆到 2867 行，tools.py 堆到 1670 行。拆的时候发现 158 个方法揉在一起，
> 根本分不清依赖关系。从今天起，新代码从一开始就按此规范组织。

---

## 二、目录结构规范

```
starpivot/
├── db/                    # 数据库层
│   ├── __init__.py
│   ├── database.py        # Database 类（仅组装 + pass）
│   ├── schema.py          # DDL 建表语句
│   └── mixins/            # 按业务域拆分
│       ├── core.py        # 连接、初始化、基础工具方法
│       ├── users.py       # 用户 CRUD
│       ├── agents.py      # AI 分身 CRUD + 技能 + SOUL
│       ├── marketplace.py # 工具市场 + 星火鉴评分
│       ├── finance.py     # 交易、余额、拍卖、股票
│       ├── services.py    # 服务管理
│       ├── tasks.py       # 任务管理
│       ├── content.py     # 书籍、二手、租赁、展示
│       ├── memory.py      # 星忆（记忆 + 关系图谱）
│       ├── conversations.py # 对话 + 消息
│       ├── audit.py       # 审计日志
│       └── invitations.py # 邀请码
│
├── tools/                 # 工具集（已拆分）
│   ├── __init__.py
│   ├── file_ops.py        # 文件读写
│   ├── web_ops.py         # 网络搜索
│   ├── media_ops.py       # 音视频
│   ├── image_ops.py       # 图片生成 + 海报
│   ├── data_ops.py        # 数据清洗 + PDF
│   ├── agent_ops.py       # Agent 调用 + 技能
│   └── registry.py        # 工具注册 + 统一入口
│
├── loop/                  # Agent 循环（已拆分）
│   ├── __init__.py
│   ├── core.py            # 基础工具函数（提示词、记忆、API配置）
│   └── agent.py           # 主循环（搜索/工具/对话三路径）
│
├── mcp_servers/           # MCP Server（一个 JSON + 一个 Python）
├── engine.py
├── registry.py
└── ...
```

---

## 三、新增代码流程

### 新增数据库方法

1. 确定属于哪个业务域 → 找到对应的 `mixins/xxx.py`
2. 在该 mixin 类中添加方法
3. 不要新建 mixin 文件（除非是全新的业务域）

```python
# ✅ 正确：在已有 mixin 中添加
# starpivot/db/mixins/users.py
class UsersMixin:
    def update_user_avatar(self, user_id: str, avatar_url: str) -> bool:
        """更新用户头像"""
        ...

# ❌ 错误：新建一个 800 行的文件
```

### 新增 MCP Server

1. 创建 `mcp_servers/xxx.json`（配置）
2. 创建 `mcp_servers/xxx_server.py`（实现）
3. 工具描述必须**中英双语**：`"English description / 中文描述"`
4. 参数描述同样双语

### 新增工具函数

1. 确定函数类别 → 放到 `tools/` 对应的文件中
2. 如果全新类别，创建新文件并在 `__init__.py` 中导入

---

## 四、命名规范

| 类型 | 规范 | 示例 |
|:-----|:-----|:-----|
| 文件名 | 小写+下划线 | `file_ops.py` |
| 类名 | 大驼峰 | `UsersMixin` |
| 函数名 | 小写+下划线 | `create_user()` |
| 常量 | 全大写下划线 | `MAX_TIMEOUT` |
| 私有方法 | 前缀下划线 | `_generate_id()` |

---

## 五、文档要求

| 文件 | 要求 |
|:-----|:-----|
| README.md | 英文默认 + 中文 README_CN.md |
| 每个 .py | 文件头 docstring 说明用途 |
| 每个公开函数 | 参数 + 返回值 docstring |
| 新增 API | 更新 API_REFERENCE.md |
| 新增部署步骤 | 更新 DEPLOY.md |

---

## 六、禁止事项

- ❌ 单文件超过 500 行
- ❌ 工具描述只有中文（必须双语）
- ❌ 硬编码路径、密钥、IP
- ❌ 新建数据库表不拆 mixin
- ❌ 跳过 __init__.py 直接 import 内部模块

---

**记住：每次偷懒省下的 5 分钟，以后要用半天来还。**

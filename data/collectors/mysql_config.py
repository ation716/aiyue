"""
本文件提供 MySQL 连接配置。

默认配置兼容当前仓库里的 `skl_predict/mysql_demo.py`：
- 主机：127.0.0.1
- 端口：3306
- 用户：root
- 密码：mysql
- 数据库：security

如果你的本地 MySQL 配置不同，可以通过环境变量覆盖：
MYSQL_HOST、MYSQL_PORT、MYSQL_USER、MYSQL_PASSWORD、MYSQL_DATABASE。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MySQLConfig:
    """
    MySQL 连接参数。

    参数示例:
    config = MySQLConfig(
        host="127.0.0.1",
        port=3306,
        user="root",
        password="mysql",
        database="security",
    )

    返回值示例:
    MySQLConfig(host='127.0.0.1', port=3306, user='root', ...)
    """

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = "root"
    database: str = "security"
    charset: str = "utf8mb4"
    connect_timeout: int = 10

    @classmethod
    def from_env(cls, prefix: str = "MYSQL_") -> "MySQLConfig":
        """
        从环境变量读取 MySQL 配置，未设置的字段使用默认值。

        参数示例:
        prefix = "MYSQL_"

        返回值示例:
        MySQLConfig(host='127.0.0.1', port=3306, user='root', ...)
        """
        return cls(
            host=os.getenv(f"{prefix}HOST", cls.host),
            port=int(os.getenv(f"{prefix}PORT", str(cls.port))),
            user=os.getenv(f"{prefix}USER", cls.user),
            password=os.getenv(f"{prefix}PASSWORD", cls.password),
            database=os.getenv(f"{prefix}DATABASE", cls.database),
            charset=os.getenv(f"{prefix}CHARSET", cls.charset),
            connect_timeout=int(os.getenv(f"{prefix}CONNECT_TIMEOUT", str(cls.connect_timeout))),
        )


def make_mysql_config(
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> MySQLConfig:
    """
    创建 MySQL 配置对象；传入的参数优先级高于环境变量。

    参数示例:
    config = make_mysql_config(user="root", password="mysql", database="security")

    返回值示例:
    MySQLConfig(host='127.0.0.1', port=3306, user='root', ...)
    """
    env_config = MySQLConfig.from_env()
    return MySQLConfig(
        host=host or env_config.host,
        port=port or env_config.port,
        user=user or env_config.user,
        password=env_config.password if password is None else password,
        database=database or env_config.database,
        charset=env_config.charset,
        connect_timeout=env_config.connect_timeout,
    )

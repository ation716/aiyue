# -*- coding: utf-8 -*-
"""
fetch_ths_concept_mapper.py

抓取同花顺（10jqka）概念/题材板块的成分股，并落地到 MySQL。

背景与踩坑说明：
- akshare 中同花顺的“成分股接口”(stock_board_concept_cons_ths) 在较新版本里已被移除，
  仅剩列表接口可用。所以这里彻底抛弃 akshare，采用原生态 requests + BeautifulSoup 直接爬官网。
- 同花顺成分股的分页数据通过后台 AJAX 接口返回（URL 形如 .../order/desc/page/1/ajax/1/），
  该接口需要 'v' 反爬 cookie，裸请求会返回 401。但同花顺同时提供了
  .../gn/detail/code/{code}/page/{N}/ 这种“服务端渲染”的静态分页路径，
  不需要任何 cookie，稳定返回 200。本脚本即基于此路径实现，从根本上绕开反爬。

落库表：与东方财富版 fetch_em_concept_mapper.py 保持一致，写入 stock_concept_mapping。
唯一键 (ts_code, concept_name) 保证同一股票同一概念不重复，且天然支持“一只股票多概念”。

运行：
    python fetch_ths_concept_mapper.py                 # 全量抓取
    python fetch_ths_concept_mapper.py --limit 5       # 仅前 5 个概念（自测）
    python fetch_ths_concept_mapper.py --dry-run       # 不写库，仅打印统计
    python fetch_ths_concept_mapper.py --clear-progress  # 清空断点续传记录
"""

import os
import sys
import time
import json
import random
import logging
import argparse
import functools

import requests
from bs4 import BeautifulSoup

# 与 data/connectors/db_connector.py 保持同一 DB_* 环境变量口径。
# 原 mysql_config 模块不在本仓库，不能继续依赖外部项目的导入路径。
def make_mysql_config():
    """读取当前进程配置；不连接数据库，不输出凭据。"""
    from types import SimpleNamespace
    return SimpleNamespace(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "root"),
        database=os.getenv("DB_NAME", "security"),
        charset="utf8mb4", connect_timeout=10, read_timeout=30, write_timeout=30,
    )

import pymysql

# ============================ 配置区 ============================
TABLE_NAME = "stock_concept_mapping"
PROGRESS_FILE = "ths_concept_progress.json"
LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "ths_concept_mapper.log"
)

GN_LIST_URL = "http://q.10jqka.com.cn/gn/"
DETAIL_TMPL = "http://q.10jqka.com.cn/gn/detail/code/{code}/"
PAGE_TMPL = "http://q.10jqka.com.cn/gn/detail/code/{code}/page/{page}/"

# 单次抓取最大翻页数（防止极端情况下死循环）
MAX_PAGES_PER_CONCEPT = 300
# 分页之间的礼貌休眠（秒，随机区间）
SLEEP_PAGE = (0.10, 0.35)
# 概念之间的礼貌休眠（秒，随机区间）
SLEEP_CONCEPT = (0.30, 0.80)

# 随机 UA 池（贴近真实 Chrome）
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


# ============================ 日志 ============================
def setup_logging():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logger = logging.getLogger("ths_concept")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


LOG = setup_logging()


# ============================ 重试装饰器 ============================
def retry(max_attempts=5, base_delay=1.0, max_delay=30.0):
    """指数退避重试，应对网络抖动 / 瞬时限流。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last = e
                    if attempt == max_attempts:
                        break
                    LOG.warning("请求失败(第%d次)，%.1fs 后重试: %s", attempt, delay, e)
                    time.sleep(delay + random.uniform(0, 0.5))
                    delay = min(delay * 2, max_delay)
            raise last
        return wrapper
    return deco


# ============================ 网络会话 ============================
def build_session() -> requests.Session:
    """构建带连接池与自动重试的会话。"""
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter

    s = requests.Session()
    retry_cfg = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        status_forcelist=(429, 500, 502, 503, 504),
        backoff_factor=0.5,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_cfg, pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def _get(session: requests.Session, url: str, referer: str, timeout: int = 15) -> requests.Response:
    """带随机 UA / Referer 的 GET，并对异常与无效响应抛错以触发重试。"""
    session.headers["User-Agent"] = random.choice(UA_POOL)
    session.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    session.headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
    session.headers["Referer"] = referer
    resp = session.get(url, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} @ {url}")
    # 简单 WAF / 频控拦截识别
    if "访问过于频繁" in resp.text or "verify" in resp.text[:200].lower() and "robot" in resp.text[:2000].lower():
        raise RuntimeError(f"疑似被限流/拦截 @ {url}")
    return resp


# ============================ 解析逻辑 ============================
@retry()
def fetch_concept_list(session: requests.Session) -> list:
    """
    抓取全部概念板块（代码 + 名称）。
    返回 [(code, name), ...]
    """
    resp = _get(session, GN_LIST_URL, referer="http://q.10jqka.com.cn/")
    soup = BeautifulSoup(resp.content, "html.parser")
    concepts = []
    seen = set()
    for a in soup.select('a[href*="/gn/detail/code/"]'):
        href = a.get("href", "")
        m = __import__("re").search(r"/gn/detail/code/(\d+)/", href)
        if not m:
            continue
        code = m.group(1)
        name = a.get_text(strip=True)
        if not name or code in seen:
            continue
        seen.add(code)
        concepts.append((code, name))
    if not concepts:
        raise RuntimeError("概念清单解析为空，可能页面结构变化或被拦截")
    return concepts


def _parse_stocks_from_html(html_bytes: bytes) -> list:
    """
    从详情页 HTML 中解析成分股表格。
    表格列：序号 | 代码 | 名称 | 现价 | 涨跌幅 ...
    代码在 td[1]，名称在 td[2]。
    返回 [(code, name), ...]
    """
    soup = BeautifulSoup(html_bytes, "html.parser")
    rows = []
    table = soup.select_one("table.m-table")
    if table is None:
        return rows
    tbody = table.find("tbody")
    if tbody is None:
        # 个别情况下无 tbody 标签，直接遍历 tr
        trs = table.find_all("tr")
    else:
        trs = tbody.find_all("tr")
    for tr in trs:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        code = tds[1].get_text(strip=True)
        name = tds[2].get_text(strip=True)
        if __import__("re").fullmatch(r"\d{6}", code):
            rows.append((code, name))
    return rows


@retry()
def fetch_concept_stocks(session: requests.Session, code: str, name: str) -> list:
    """
    抓取单个概念的全部成分股（跨页合并）。
    使用静态分页路径 /page/{N}/，无需 v cookie。
    """
    base_url = DETAIL_TMPL.format(code=code)
    all_rows = []
    seen_codes = set()
    prev_first = None

    for page in range(1, MAX_PAGES_PER_CONCEPT + 1):
        url = base_url if page == 1 else PAGE_TMPL.format(code=code, page=page)
        resp = _get(session, url, referer=base_url)
        rows = _parse_stocks_from_html(resp.content)

        if not rows:
            # 空页 -> 到底，结束翻页
            break

        # 防死循环：若本页首只与上一页首只相同，认为回卷，结束
        first_code = rows[0][0]
        if prev_first is not None and first_code == prev_first:
            break
        prev_first = first_code

        added = 0
        for code6, sname in rows:
            if code6 in seen_codes:
                continue
            seen_codes.add(code6)
            all_rows.append((code6, sname))
            added += 1

        # 本页新增为 0 也可提前结束
        if added == 0:
            break

        if page >= MAX_PAGES_PER_CONCEPT:
            LOG.warning("概念 %s(%s) 达到最大翻页上限 %d，提前停止", name, code, MAX_PAGES_PER_CONCEPT)
            break

        time.sleep(random.uniform(*SLEEP_PAGE))

    return all_rows


# ============================ 数据库 ============================
def create_mapping_table(conn):
    """建表，结构与东方财富版 stock_concept_mapping 完全一致。"""
    sql = f"""
        CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(16) NOT NULL COMMENT '股票代码，如 300598.SZ',
            symbol VARCHAR(8) NOT NULL COMMENT '6位纯数字代码',
            stock_name VARCHAR(32) NULL COMMENT '股票名称',
            concept_name VARCHAR(64) NOT NULL COMMENT '同花顺概念名称',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_code_concept (ts_code, concept_name),
            KEY idx_ts_code (ts_code),
            KEY idx_concept (concept_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _to_ts_code(raw_code: str) -> str:
    """6位代码 -> ts_code；覆盖沪、深、北三个前缀。"""
    raw_code = str(raw_code).strip()
    if raw_code.startswith("6"):
        return f"{raw_code}.SH"
    if raw_code.startswith(("8", "4", "92")):
        return f"{raw_code}.BJ"
    if raw_code.startswith(("0", "3")):
        return f"{raw_code}.SZ"
    raise ValueError(f"未知代码前缀: {raw_code}")


def batch_insert_to_db(conn, stocks: list, concept_name: str) -> int:
    """将单个概念的成分股批量写入数据库（幂等：唯一键冲突则更新名称）。"""
    if not stocks:
        return 0
    records = []
    for raw_code, sname in stocks:
        raw_code = str(raw_code).strip()
        if not raw_code:
            continue
        ts_code = _to_ts_code(raw_code)
        records.append((ts_code, raw_code, str(sname).strip(), concept_name))

    if not records:
        return 0

    sql = f"""
        INSERT INTO `{TABLE_NAME}` (ts_code, symbol, stock_name, concept_name)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            stock_name=VALUES(stock_name),
            updated_at=CURRENT_TIMESTAMP
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()
    return len(records)


# ============================ 断点续传 ============================
def save_progress(done: set):
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PROGRESS_FILE)


def load_progress() -> set:
    if not os.path.exists(PROGRESS_FILE):
        return set()
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            value = json.load(f)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError("断点格式不是字符串列表")
        return set(value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"断点文件损坏，请人工处理后再运行：{PROGRESS_FILE}") from exc


# ============================ 主流程 ============================
def run_spider(limit: int = None, dry_run: bool = False):
    LOG.info("=== 开始抓取同花顺概念板块成分股 ===")

    session = build_session()
    # 预热会话：先访问列表页，建立正常访问路径（顺便拿概念清单）
    LOG.info("正在拉取概念清单...")
    try:
        concept_list = fetch_concept_list(session)
    except Exception as e:
        LOG.error("获取概念清单失败，终止：%s", e)
        return
    LOG.info("共获取到 %d 个概念板块。", len(concept_list))

    if limit:
        concept_list = concept_list[:limit]
        LOG.info("受 --limit 限制，本次仅处理前 %d 个。", limit)

    done = load_progress()
    LOG.info("断点记录：已完成 %d 个板块。", len(done))

    total_inserted = 0
    total_concepts = 0

    if not dry_run:
        db_cfg = make_mysql_config()
        conn = pymysql.connect(
            host=db_cfg.host, port=db_cfg.port, user=db_cfg.user,
            password=db_cfg.password, database=db_cfg.database,
            charset=getattr(db_cfg, "charset", "utf8mb4"),
            connect_timeout=getattr(db_cfg, "connect_timeout", 10),
        )
        try:
            create_mapping_table(conn)
            for i, (code, name) in enumerate(concept_list, 1):
                if name in done:
                    continue
                LOG.info("[%d/%d] 抓取概念: %s(%s) ...", i, len(concept_list), name, code)
                try:
                    stocks = fetch_concept_stocks(session, code, name)
                    rows = batch_insert_to_db(conn, stocks, name)
                    total_inserted += rows
                    total_concepts += 1
                    LOG.info("  成功，入库 %d 只股票（累计 %d 只）。", rows, len(stocks))
                except Exception as e:
                    LOG.error("  失败，停止本轮：%s", e)
                    # 失败不能记为完成，否则断点会永久跳过未成功项。
                    break
                finally:
                    time.sleep(random.uniform(*SLEEP_CONCEPT))
        finally:
            conn.close()
    else:
        # dry-run：仅统计，不落库
        for i, (code, name) in enumerate(concept_list, 1):
            if name in done:
                continue
            try:
                stocks = fetch_concept_stocks(session, code, name)
                total_inserted += len(stocks)
                total_concepts += 1
                LOG.info("[%d/%d] %s(%s) -> %d 只（dry-run，不入库）",
                         i, len(concept_list), name, code, len(stocks))
            except Exception as e:
                LOG.error("[%d/%d] %s 失败：%s", i, len(concept_list), name, e)
            finally:
                time.sleep(random.uniform(*SLEEP_CONCEPT))

    LOG.info("=== 完成：处理 %d 个概念，累计映射 %d 条 ===", total_concepts, total_inserted)


def main():
    parser = argparse.ArgumentParser(description="同花顺概念板块成分股抓取落库")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 个概念（自测用）")
    parser.add_argument("--dry-run", action="store_true", help="不写库，仅打印统计")
    parser.add_argument("--clear-progress", action="store_true", help="清空断点续传记录后退出")
    args = parser.parse_args()

    if args.clear_progress:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print(f"已清空断点记录：{PROGRESS_FILE}")
        else:
            print("无断点记录可清。")
        return

    run_spider(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
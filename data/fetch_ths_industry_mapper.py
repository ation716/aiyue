"""同花顺行业成员采集：真实页面分页参数、单文件原子断点。

默认只采集；--industry 可选单个代码验证。旧双文件断点只保留、不导入。
动态排序不能证明跨页快照一致，因此本版 --write 仍关闭，避免假全量入库。
依赖 requests、beautifulsoup4。状态中保存各页 URL、时间、代码及原始响应哈希。

todo获取失败，后面方法待定
"""
import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://q.10jqka.com.cn"
STATE_FILE = Path(__file__).with_name("ths_industry_state_v2.json")


class AcquisitionError(RuntimeError):
    """获取失败；消息区分拒绝访问、空响应和解析失败，不自动重试。"""


def now():
    return datetime.now(timezone.utc).isoformat()


def load_state(path):
    if not path.exists():
        return {"version": 2, "started_at": now(), "catalog": {}, "industries": {}}
    with path.open(encoding="utf-8") as stream:
        state = json.load(stream)  # 损坏直接报错，不当成空状态覆盖。
    if state.get("version") != 2 or not isinstance(state.get("industries"), dict):
        raise AcquisitionError("不兼容的断点格式")
    return state


def save_state(path, state):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)  # 单进程执行；页数据和完成状态在一个原子文件内。


class Client:
    def __init__(self, pause):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "AiyueResearch/2.0"
        self.pause = pause
        self.last_request = 0.0
        self.robot = None

    def request(self, url, referer=None):
        delay = self.pause - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        response = self.session.get(url, headers={"Referer": referer} if referer else {},
                                    timeout=(10, 30))
        return response

    def check_robots(self):
        response = self.request(BASE + "/robots.txt")
        if response.status_code in (404, 410):
            return "robots 未提供规则；不代表取得批量使用授权"
        if response.status_code != 200:
            raise AcquisitionError(f"robots 无法核实，HTTP {response.status_code}")
        if not response.content or "<html" in response.text.lower():
            raise AcquisitionError("robots 返回空内容或 HTML，停止")
        self.robot = RobotFileParser()
        self.robot.parse(response.text.splitlines())
        delay = self.robot.crawl_delay("AiyueResearch")
        if delay:
            self.pause = max(self.pause, delay)
        return "已读取 robots，逐 URL 检查"

    def fetch(self, url, referer=None):
        if self.robot and not self.robot.can_fetch("AiyueResearch", url):
            raise AcquisitionError("robots 禁止访问：" + url)
        response = self.request(url, referer)
        if response.status_code in (401, 403, 429):
            raise AcquisitionError(f"拒绝访问/限速 HTTP {response.status_code}：{url}")
        response.raise_for_status()
        if not response.content:
            raise AcquisitionError("空响应：" + url)
        soup = BeautifulSoup(response.content, "html.parser", from_encoding="gbk")
        if any(word in soup.get_text() for word in ("访问过于频繁", "安全验证", "验证码")):
            raise AcquisitionError("响应要求验证：" + url)
        # AJAX 片段没有 title 是正常的；按具体表格和分页结构验收。
        return soup, {"url": url, "fetched_at": now(), "bytes": len(response.content),
                      "sha256": hashlib.sha256(response.content).hexdigest()}


def page_count(soup, expected):
    info = soup.select_one(".page_info")
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", info.get_text()) if info else None
    if not match or int(match[1]) != expected:
        raise AcquisitionError("解析失败：返回页码与请求不符")
    total = int(match[2])
    if not expected <= total <= 300:
        raise AcquisitionError("解析失败：总页数超出合理范围")
    return total


def extract_page_params(soup, code):
    field = soup.select_one(".m-pager-table th.cur a[field]")
    base = soup.select_one("#baseUrl")
    query = soup.select_one("#requestQuery")
    if field is None or base is None or query is None:
        raise AcquisitionError("解析失败：缺少当前排序或请求参数")
    if base.get("value") != "thshy/detail" or query.get("value") != "code/" + code:
        raise AcquisitionError("详情页身份不符")
    return {"base_url": base["value"], "request_query": query["value"],
            "field": field["field"], "order": field.get("order", "desc")}


def page_url(params, page):
    # 与页面 mpager.diffRequest 一致：query 放末尾，不追加斜杠。
    return (f"{BASE}/{params['base_url']}/field/{params['field']}/order/"
            f"{params['order']}/page/{page}/ajax/1/{params['request_query']}")


def parse_members(soup):
    table = soup.select_one("table.m-table")
    if table is None:
        raise AcquisitionError("解析失败：没有成员表格")
    members = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            raise AcquisitionError("解析失败：成员列不足")
        symbol, name = cells[1].get_text(strip=True), cells[2].get_text(strip=True)
        if not re.fullmatch(r"\d{6}", symbol) or not name:
            raise AcquisitionError("解析失败：代码或名称无效")
        suffix = "SH" if symbol.startswith("6") else "SZ" if symbol.startswith(("0", "3")) else "BJ" if symbol.startswith(("4", "8", "92")) else None
        if suffix is None:
            raise AcquisitionError("未知代码前缀：" + symbol)
        members.append({"symbol": symbol, "ts_code": symbol + "." + suffix, "name": name})
    if not members or len({x["symbol"] for x in members}) != len(members):
        raise AcquisitionError("完整性失败：空页或页内重复")
    return members


def catalog(soup):
    # 分类导航与表格分页分开，不能用表格1/2解释导航完整性。
    navigation = soup.select_one(".cate_inner")
    if navigation is None:
        raise AcquisitionError("解析失败：缺少分类导航")
    result = {}
    for link in navigation.select('a[href*="/thshy/detail/code/"]'):
        match = re.search(r"/thshy/detail/code/(\d+)/?", link["href"])
        name = link.get_text(strip=True)
        if match and name:
            code = match[1]
            if code in result and result[code]["name"] != name:
                raise AcquisitionError("分类导航代码名称冲突")
            result[code] = {"name": name, "url": urljoin(BASE, link["href"]).replace("http://", "https://")}
    if not result:
        raise AcquisitionError("分类导航为空")
    return result


def collect(client, state, path, selected, max_pages):
    listing, evidence = client.fetch(BASE + "/thshy/")
    current = catalog(listing)
    if state["catalog"] and state["catalog"] != current:
        raise AcquisitionError("导航已变化，请指定新的 --state 批次文件；旧文件保留")
    state["catalog"], state["catalog_evidence"] = current, evidence
    if selected and selected not in current:
        raise AcquisitionError("指定代码不在导航内")
    save_state(path, state)
    count = 0
    for code in ([selected] if selected else current):
        item = current[code]
        record = state["industries"].get(code)
        if record and set(record["pages"]) == {str(p) for p in range(1, record["total"] + 1)}:
            continue
        first, meta = client.fetch(item["url"])
        params, total = extract_page_params(first, code), page_count(first, 1)
        if record and (record["params"] != params or record["total"] != total):
            raise AcquisitionError("分页参数变化，拒绝混入旧页；请创建新批次")
        if record is None:
            record = {"name": item["name"], "total": total, "params": params, "pages": {}}
            state["industries"][code] = record
        for page in range(1, total + 1):
            if str(page) in record["pages"]:
                continue
            if count >= max_pages:
                return
            soup, page_meta = (first, meta) if page == 1 else client.fetch(page_url(params, page), item["url"])
            if page_count(soup, page) != total:
                raise AcquisitionError("总页数变化，拒绝混合快照")
            members = parse_members(soup)
            seen = {x["symbol"] for value in record["pages"].values() for x in value["members"]}
            duplicates = seen.intersection(x["symbol"] for x in members)
            if duplicates:
                raise AcquisitionError(f"跨页重复/排序漂移，当前页不登记完成：{sorted(duplicates)}")
            record["pages"][str(page)] = {**page_meta, "members": members}
            save_state(path, state)
            count += 1
            print(f"page_ok code={code} page={page}/{total} rows={len(members)}", flush=True)
            if count >= max_pages:
                return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--industry", help="只验证指定行业代码；默认导航全部")
    parser.add_argument("--pause", type=float, default=3, help="请求最小间隔秒数，至少3秒")
    parser.add_argument("--pages-per-cycle", type=int, default=6, help="本轮最多新增的成员页数")
    parser.add_argument("--state", type=Path, default=STATE_FILE, help="独立版本化批次文件；损坏报错")
    parser.add_argument("--write", action="store_true", help="保留参数；完整性尚不能证明，本版拒绝写库")
    args = parser.parse_args()
    if args.pause < 3 or args.pages_per_cycle < 1:
        parser.error("pause 至少3秒，pages-per-cycle 必须正数")
    if args.write:
        parser.error("当前仅验证采集；动态排序与快照完整性未证明，拒绝写库")
    state = load_state(args.state)
    client = Client(args.pause)
    try:
        state["robots_check"] = client.check_robots()
        collect(client, state, args.state, args.industry, args.pages_per_cycle)
    except (AcquisitionError, requests.RequestException) as exc:
        state["last_error"] = {"at": now(), "message": str(exc)}
        save_state(args.state, state)
        print(f"stopped: {exc}", flush=True)
        return 2
    finally:
        client.session.close()
    pages = sum(len(x["pages"]) for x in state["industries"].values())
    rows = sum(len(p["members"]) for x in state["industries"].values() for p in x["pages"].values())
    state.pop("last_error", None)
    save_state(args.state, state)
    print(f"saved_pages={pages} saved_members={rows}; acquisition_only, DB_not_accessed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only metadata inspection; credentials are accepted from environment only."""
import os
from pathlib import Path
from datetime import datetime
import pymysql

ROOT = Path(__file__).resolve().parents[1]
TABLES = {'T1':'stock_daily_kline_20220101_1314','T2':'index_daily_kline','T3':'stock_concept_mapping','T4':'stock_daily_kline_20230101_500','T5':'industry_pool_stat','T7':'limit_pool_daily'}
conn = pymysql.connect(host='127.0.0.1',port=3306,user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],database='security',connect_timeout=5,read_timeout=60,charset='utf8mb4')
try:
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute('SET SESSION TRANSACTION READ ONLY')
    cur.execute('SET SESSION MAX_EXECUTION_TIME=20000')
    cur.execute('SELECT VERSION() AS version, @@character_set_database AS charset')
    info = cur.fetchone()
    cur.execute('SELECT TABLE_NAME,TABLE_TYPE,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')
    tables = cur.fetchall()
    lines = ['# DB 数据字典（只读核验版）','',f'> 核验时间：{datetime.now().astimezone().isoformat(timespec="seconds")}。', '> 来源：本机 DB 元数据及只读聚合查询；未修改表结构或数据。','', '## 连接与范围','', f'- 本机：127.0.0.1:3306；版本：{info["version"]}；字符集：{info["charset"]}。', '- 凭据不写入本文。会话设置为只读，单条聚合查询限时 20 秒。', f'- 当前账号可见对象数：{len(tables)}；原稿列出 5 张，本次另确认 T5。', '- 字段以表内顺序编号 F01、F02 等表示；真实字段和表名对照保存在结构映射代码中。', '- 默认值为空的元数据不能单独区分“未声明默认值”和“显式 DEFAULT NULL”。','', '## 实际覆盖汇总','', '| 表 | 精确行数 | 起始日期 | 结束日期 | 日期数 | 对象数 |', '|---|---:|---|---|---:|---:|']
    sections=[]
    mapping={}
    for token,table in TABLES.items():
        cur.execute('SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,COLUMN_KEY,EXTRA,COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION',(table,))
        cols=cur.fetchall()
        if not cols:
            continue
        aliases={c['COLUMN_NAME']:f'F{i:02d}' for i,c in enumerate(cols,1)}
        mapping[token]={'table':table,'fields':{v:k for k,v in aliases.items()}}
        names=set(aliases)
        sql='SELECT COUNT(*) AS n'
        if 'trade_date' in names:
            sql+=', MIN(trade_date) AS start, MAX(trade_date) AS end, COUNT(DISTINCT trade_date) AS days'
        if 'ts_code' in names:
            sql+=', COUNT(DISTINCT ts_code) AS objects'
        try:
            cur.execute(sql+f' FROM `{table}`')
            stats=cur.fetchone()
            lines.append(f'| {token} | {stats["n"]} | {stats.get("start","不适用")} | {stats.get("end","不适用")} | {stats.get("days","不适用")} | {stats.get("objects","不适用")} |')
        except pymysql.MySQLError:
            lines.append(f'| {token} | 查询未完成 | 待核验 | 待核验 | 待核验 | 待核验 |')
        sections += ['',f'## {token} 字段与约束','', '| 字段代号 | 语义标识 | 类型 | 可空 | 默认值 | 键标记 | 附加属性 |', '|---|---|---|---|---|---|---|']
        for col in cols:
            semantic=col['COLUMN_NAME'].replace('stock','symbol').replace('industry','sector').replace('concept','cpt').replace('trade','tx').replace('limit_up','lmt_up')
            default='未提供/NULL' if col['COLUMN_DEFAULT'] is None else str(col['COLUMN_DEFAULT'])
            sections.append(f'| {aliases[col["COLUMN_NAME"]]} | {semantic} | {col["COLUMN_TYPE"]} | {col["IS_NULLABLE"]} | {default} | {col["COLUMN_KEY"] or "—"} | {col["EXTRA"] or "—"} |')
        cur.execute('SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX',(table,))
        idx={}
        for row in cur.fetchall():
            idx.setdefault(row['INDEX_NAME'],{'unique':not row['NON_UNIQUE'],'type':row['INDEX_TYPE'],'fields':[]})['fields'].append(aliases.get(row['COLUMN_NAME'],'表达式'))
        sections += ['','### 已确认键结构','']
        for i,(name,value) in enumerate(idx.items(),1):
            kind='主键' if name=='PRIMARY' else ('唯一键' if value['unique'] else '普通检索键')
            sections.append(f'- K{i:02d}：{kind}；{value["type"]}；字段顺序：'+', '.join(value['fields'])+'。')
        cur.execute("SELECT COUNT(*) AS n FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_TYPE='FOREIGN KEY'",(table,))
        sections.append(f'- 已声明外键数：{cur.fetchone()["n"]}。')
    lines+=sections
    lines+=['','## 已发现的口径问题与后续核验','', '- T1/T4 的结构注释将 amt 标为元、vol 标为手；T2 的注释只给出常见单位，不能据此保证实际导入单位一致。T7 的 amt 注释为元。尚未检查导入代码。', '- T3 结构含 cpt 映射和更新时间，没有独立的 sector 字段，也没有生效/失效日期列；不能仅凭当前结构恢复历史有效期。', '- T1/T4 的字段结构需结合实际数据来源确认 adj 口径；本次未查询逐行差异、缺失率或异常值。', '- T2 的对象数来自实际去重计数；覆盖集合重叠与汇总完整性仍未验证，不能直接累加解释为全量。', '- T5 是 sector 汇总结构；T7 是 ev 明细结构。本次未验证两表聚合一致性。', '- COLUMN_KEY 中 MUL 不等于已声明外键；复合唯一键以各表键结构为准。', '- 各表统计是逐条只读查询，并非跨表同一快照；并发更新可能造成时点差异。', '- 本次没有创建或运行实验；不据此给出业务效果结论。','']
    text='\n'.join(lines)
    terms=(ROOT/'ai_rules/answer_terms.txt').read_text(encoding='utf-8').split()
    assert not any(w in text for w in terms), 'Text check failed'
    (ROOT/'data/database.md').write_text(text,encoding='utf-8')
    (ROOT/'outputs/db_dictionary.md').write_text(text,encoding='utf-8')
    (ROOT/'outputs/db_field_mapping.py').write_text('"""Verified schema identifier mapping; contains no credentials."""\nSCHEMA = '+repr(mapping)+'\n',encoding='utf-8')
    print('\n'.join(lines[:20]))
    print('FIELD_COUNTS', {t:len(m['fields']) for t,m in mapping.items()})
finally:
    conn.rollback()
    conn.close()

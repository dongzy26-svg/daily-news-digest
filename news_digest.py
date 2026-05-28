#!/usr/bin/env python3
"""
Daily News Digest - 每日大事推送（中文版）
每天自动抓取并整理国内外要闻、股市行情、财经资讯、科技动态、投资机会。

内容结构（约 20+ 条）：
  每日综述
  全球指数速览（今日 + 1/3/5/10 年涨幅）
  投资观察（52周高低位、估值对比）
  国内要闻 ×5（过滤花边新闻）
  国际要闻 ×3
  财经资讯 ×3
  科技动态 ×3
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import time
import requests
import yfinance as yf

# ===== 配置 =====
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

CACHE = {}

# ===== 指数清单（三级制） =====
# 第一级：基准指数 — 始终展示（含传统大宗商品）
BASE_INDICES = [
    ("上证指数", "000001.SS"),
    ("深证成指", "399001.SZ"),
    ("创业板指", "399006.SZ"),
    ("沪深300", "000300.SS"),
    ("科创50",   "000688.SS"),
    ("恒生指数", "^HSI"),
    ("恒生科技", "3067.HK"),
    ("中证500",  "000905.SS"),
    ("日经225", "^N225"),
    ("标普500", "^GSPC"),
    ("纳斯达克", "^IXIC"),
    ("道琼斯",  "^DJI"),
    ("费城半导体", "^SOX"),
    ("纳斯达克100", "^NDX"),
    ("伦敦金",  "GC=F"),
    ("原油",    "CL=F"),
]

# 第二级：行业热点 — 经评估后仅展示有信号意义的
SECTOR_INDICES = [
    ("银行ETF",   "512800.SS"),
    ("军工ETF",   "512660.SS"),
    ("传媒ETF",   "512980.SS"),
    ("旅游ETF",   "159766.SZ"),
    ("农业ETF",   "159825.SZ"),
    ("养殖ETF",   "159865.SZ"),   # 猪肉
    ("化工ETF",   "159870.SZ"),   # 化工
    ("煤炭ETF",   "515220.SS"),   # 煤化工
    ("有色金属",  "512400.SS"),   # 有色/稀土
    ("新能源ETF", "516160.SS"),   # 新能源
    ("光伏ETF",   "515790.SS"),   # 光伏
    ("医药ETF",   "512010.SS"),   # 医药
    ("消费ETF",   "159928.SZ"),   # 大消费
    ("AI人工智能", "515070.SS"),
    ("数字经济",   "159658.SZ"),
    ("通信ETF",   "515880.SS"),   # CPO/光模块
    ("半导体ETF", "512480.SS"),
    ("港股低波红利", "520550.SS"),  # 招商恒生港股通高股息低波动ETF
    ("港股汽车",   "520720.SS"),   # 国泰中证港股通汽车产业主题ETF
]

# 花边新闻过滤词（标题包含这些词则跳过）
GOSSIP_FILTER = [
    "pregnancy", "pregnant", "announces pregnancy", "married",
    "NBA MVP", "MVP award", "季后赛", "决赛", "夺冠", "冠军",
    "celebrity", "dating", "分手", "恋情", "出轨",
    "退款", "烤羊肉", "烤熟", "退回首轮",
    "星座", "运势", "风水",
]


def _is_gossip(title: str) -> bool:
    """判断标题是否为花边/娱乐新闻。"""
    t = title.lower()
    return any(kw.lower() in t for kw in GOSSIP_FILTER)


def fetch_newsapi(category=None, query=None, page_size=5, language="zh",
                  country=None, sources=None, dedup_size=20) -> list:
    """从 NewsAPI 获取新闻，自动过滤花边。"""
    if not NEWSAPI_KEY:
        print("⚠ NEWSAPI_KEY 未设置，跳过新闻抓取")
        return []
    url = "https://newsapi.org/v2/top-headlines"
    params = {"apiKey": NEWSAPI_KEY, "pageSize": max(page_size * 3, 20)}
    if category:
        params["category"] = category
    if query:
        params["q"] = query
    if language:
        params["language"] = language
    if country:
        params["country"] = country
    if sources:
        params["sources"] = sources
    try:
        resp = requests.get(url, params=params, timeout=15)
        articles = resp.json().get("articles", [])
        results = []
        seen = set()
        for a in articles:
            title = a.get("title")
            if not title:
                continue
            # 过滤花边
            if _is_gossip(title):
                continue
            # 去重（前20字）
            key = title[:dedup_size]
            if key in seen:
                continue
            seen.add(key)
            desc = (a.get("description") or "")[:120]
            results.append({
                "title": title,
                "desc": desc,
                "url": a.get("url", ""),
                "source": a.get("source", {}).get("name", ""),
            })
            if len(results) >= page_size:
                break
        return results
    except Exception as e:
        print(f"NewsAPI error: {e}")
        return []


def fetch_everything(query, language="zh", page_size=5, days=2,
                     sort_by="relevancy") -> list:
    """用 NewsAPI /v2/everything 搜索特定关键词（用于深度内容）。"""
    if not NEWSAPI_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "apiKey": NEWSAPI_KEY,
        "q": query,
        "language": language,
        "pageSize": max(page_size * 3, 15),
        "from": since,
        "sortBy": sort_by,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        articles = resp.json().get("articles", [])
        results = []
        seen = set()
        for a in articles:
            title = a.get("title")
            if not title:
                continue
            if _is_gossip(title):
                continue
            key = title[:20]
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "title": title,
                "desc": (a.get("description") or "")[:120],
                "url": a.get("url", ""),
                "source": a.get("source", {}).get("name", ""),
            })
            if len(results) >= page_size:
                break
        return results
    except Exception as e:
        print(f"Everything error: {e}")
        return []


def fetch_hackernews() -> list:
    """Hacker News 热门。"""
    try:
        resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        )
        top_ids = resp.json()[:8]
        items = []
        for item_id in top_ids:
            r = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
                timeout=10,
            )
            item = r.json()
            if item and "title" in item:
                items.append({
                    "title": item["title"],
                    "url": item.get("url",
                                   f"https://news.ycombinator.com/item?id={item_id}"),
                    "source": "Hacker News",
                    "score": item.get("score", 0),
                })
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        return items[:3]
    except Exception as e:
        print(f"Hacker News error: {e}")
        return []


# ========== 股市数据（yfinance + AKShare 双源）==========

AKSHARE_MAP = {
    # A 股指数
    "000001.SS": ("zh_index", "sh000001"),
    "399001.SZ": ("zh_index", "sz399001"),
    "399006.SZ": ("zh_index", "sz399006"),
    "000300.SS": ("zh_index", "sh000300"),
    "000688.SS": ("zh_index", "sh000688"),
    "000905.SS": ("zh_index", "sh000905"),
    # 港股指数
    "^HSI": ("hk_index", "HSI"),
    "3067.HK": ("hk_index", "HSTECH"),
    # 行业 ETF
    "512800.SS": ("zh_index", "sh512800"),
    "512660.SS": ("zh_index", "sh512660"),
    "512980.SS": ("zh_index", "sh512980"),
    "159766.SZ": ("zh_index", "sz159766"),
    "159825.SZ": ("zh_index", "sz159825"),
    "159865.SZ": ("zh_index", "sz159865"),
    "159870.SZ": ("zh_index", "sz159870"),
    "515220.SS": ("zh_index", "sh515220"),
    "512400.SS": ("zh_index", "sh512400"),
    "516160.SS": ("zh_index", "sh516160"),
    "515790.SS": ("zh_index", "sh515790"),
    "512010.SS": ("zh_index", "sh512010"),
    "159928.SZ": ("zh_index", "sz159928"),
    "515070.SS": ("zh_index", "sh515070"),
    "159658.SZ": ("zh_index", "sz159658"),
    "515880.SS": ("zh_index", "sh515880"),
    "512480.SS": ("zh_index", "sh512480"),
    "520550.SS": ("zh_index", "sh520550"),
    "520720.SS": ("zh_index", "sh520720"),
}


def _fetch_akshare(kind: str, eng: str) -> "pd.DataFrame or None":
    """调用 AKShare 获取数据（本地运行有效）。"""
    try:
        import akshare as ak
        import pandas as pd
        if kind == "zh_index":
            df = ak.stock_zh_index_daily(symbol=eng)
        elif kind == "hk_index":
            df = ak.stock_hk_index_daily_em(symbol=eng)
        else:
            return None
        if df is None or df.empty:
            return None
        col_map = {}
        for cn, en in [("日期","date"),("开盘","Open"),("收盘","Close"),
                       ("最高","High"),("最低","Low"),("成交量","Volume")]:
            if cn in df.columns: col_map[cn] = en
        df = df.rename(columns=col_map)
        if "Close" not in df.columns:
            return None
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        df = df.sort_index()
        keep = [c for c in ["Close","High","Low","Open","Volume"] if c in df.columns]
        return df[keep]
    except Exception as e:
        return None


def _fetch_history(name: str, symbol: str, period: str = "1y"):
    """获取指数历史数据：yfinance → 重试 → AKShare。"""
    for attempt in range(2):
        try:
            ticker = _get_ticker(symbol)
            hist = ticker.history(period=period)
            if hist is not None and len(hist) >= 2:
                return hist
        except Exception:
            pass
        if attempt == 0:
            time.sleep(3)
    if symbol in AKSHARE_MAP:
        kind, eng = AKSHARE_MAP[symbol]
        df = _fetch_akshare(kind, eng)
        if df is not None and len(df) >= 2:
            print(f"✅ AKShare 补充: {name} ({symbol}) → {len(df)}条")
            return df
    return None


def _get_ticker(symbol):
    if symbol not in CACHE:
        CACHE[symbol] = yf.Ticker(symbol)
    return CACHE[symbol]


def fetch_market_snapshot(indices: list) -> list:
    """获取一组指数的今日行情。"""
    results = []
    for name, symbol in indices:
        hist = _fetch_history(name, symbol, period="5d")
        if hist is not None and len(hist) >= 2:
            close = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]
            change_pct = ((close - prev) / prev) * 100
            results.append({
                "name": name, "symbol": symbol,
                "close": close, "change_pct": change_pct,
            })
        else:
            print(f"Snapshot {name} ({symbol}): no data")
    return results


def fetch_long_term_returns(indices: list) -> tuple:
    """全球主要指数中长期涨幅。
    返回 (periods, display_rows, lt_dict) 其中 lt_dict={name: {1y:float, 3y:float, ...}}
    """
    periods = [("1年", "1y"), ("3年", "3y"), ("5年", "5y"), ("10年", "10y")]
    rows = []
    lt_dict = {}
    for name, symbol in indices:
        lt_row = {}
        try:
            row = [name]
            for p_name, p_val in periods:
                hist = _fetch_history(name, symbol, period=p_val)
                if hist is None or len(hist) < 2:
                    row.append("—")
                    continue
                first = hist["Close"].iloc[0]
                last = hist["Close"].iloc[-1]
                ret = ((last - first) / first) * 100
                emoji = "🟢" if ret >= 0 else "🔴"
                row.append(f"{emoji}{ret:+.1f}%")
                lt_row[p_name] = ret
            rows.append(row)
            if lt_row:
                lt_dict[name] = lt_row
        except Exception as e:
            print(f"LT {name} error: {e}")
    return periods, rows, lt_dict


# ========== 投资判词与操作建议 ==========

JUDGMENT_ACTIONS = {
    "超跌关注": ("逢低布局", "分批建仓，控制仓位不超过30%，严格设好止损"),
    "深跌谨慎": ("等待企稳", "不盲目抄底，等放量止跌或基本面改善信号再介入"),
    "低位关注": ("跟踪观望", "暂不操作，加入观察列表，等待放量反弹确认趋势"),
    "触底反弹": ("轻仓参与", "小仓位试探性介入，止损设在前低下方，快进快出"),
    "低位整理": ("不宜抄底", "底部尚未形成，耐心等待右侧企稳信号再考虑"),
    "趋势稳健": ("持有或加仓", "持有为主，回踩10/20日均线可适当加仓，趋势线不破不出"),
    "弱势震荡": ("观望为主", "减少仓位至半仓以下，等方向明确后再做决策"),
    "区间中性": ("观望为宜", "不新增仓位，持有现有仓位不动，等待方向选择"),
    "偏强运行": ("持有不追", "已持仓继续持有，未持仓的不建议追高，回调再考虑"),
    "高位整理": ("注意风险", "考虑减仓锁定部分利润，跌破关键支撑位及时离场"),
    "强势持有": ("移动止盈", "已持仓用移动止盈保护利润，不追高加仓，享受趋势"),
    "高位预警": ("减仓防范", "优先减仓止盈，不博最后一段涨幅，落袋为安"),
    "高位整固": ("等待方向", "持仓不动也不加仓，等突破或跌破确认后再操作"),
}


def _judgment_with_action(judgment: str, long_desc: bool = False) -> str:
    """判词 → 操作建议（可带详细说明）"""
    for key, (short, detail) in JUDGMENT_ACTIONS.items():
        if key in judgment:
            tag = f'<span style="color:#7c3aed;font-weight:500;">→ {short}</span>'
            if long_desc:
                tag += f'<br><span style="color:#a78bfa;font-size:11px;">{detail}</span>'
            return f'{judgment} {tag}'
    return judgment


def _call_deepseek_judgments(items: list) -> dict or None:
    """批量调用 DeepSeek 生成 AI 投资判断。"""
    if not DEEPSEEK_API_KEY:
        return None
    lines = []
    for i, it in enumerate(items):
        lt = it.get("lt_return", {})
        line = (f"{i+1}. {it['name']}: "
                f"52周位置{it['position']:.0f}%，"
                f"近1月{it['change_1m']:+.1f}%，"
                f"1年{lt.get('1y', 0):+.1f}%"
                f"{'，3年'+str(lt.get('3y', 0))+'%' if lt.get('3y') else ''}")
        lines.append(line)
    prompt = (
        "你是一位专业的投资分析师。基于以下数据，对每个指数给出投资判断。\n\n"
        + "\n".join(lines) +
        "\n\n请按JSON数组格式输出，每个元素包含："
        '{"index":序号, "judgment":"判断词", "action":"操作建议(4字内)", '
        '"reason":"一句话依据(20字内)"}\n'
        "判断词可选：超跌关注/深跌谨慎/低位关注/触底反弹/低位整理/"
        "趋势稳健/弱势震荡/区间中性/偏强运行/高位整理/强势持有/高位预警/高位整固\n"
        "只输出JSON，不要其他内容。"
    )
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "deepseek-chat",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": 2000},
            timeout=30)
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        import re, json as _json
        m = re.search(r'\[.*?\]', content, re.DOTALL)
        if m:
            return _json.loads(m.group())
    except Exception as e:
        print(f"DeepSeek API error: {e}")
    return None


def generate_judgment(name: str, position: float, change_1m: float,
                       lt_return: dict = None) -> tuple:
    """基于多维度数据生成投资判断+依据。"""
    ret_1y = lt_return.get("1y") if lt_return else None

    # ===== 四象限判断 =====
    if position <= 20:
        # 低位区
        if ret_1y is not None and ret_1y > 10:
            judgment = "🔔 超跌关注"
            reason = (f"52周低位({position:.0f}%)，但1年涨{ret_1y:+.1f}%，"
                      "长期趋势仍在向上，短期超跌可能是布局窗口")
        elif ret_1y is not None and ret_1y < -10:
            judgment = "⚠️ 深跌谨慎"
            reason = (f"52周低位({position:.0f}%)，1年跌{ret_1y:+.1f}%，"
                      "趋势偏弱，建议等待企稳信号")
        else:
            judgment = "🔔 低位关注"
            reason = f"52周低位({position:.0f}%)，近1月{change_1m:+.1f}%，观察是否有反弹迹象"

    elif position >= 80:
        # 高位区
        if change_1m > 5:
            judgment = "📈 强势持有"
            reason = (f"52周高位({position:.0f}%)，近1月涨{change_1m:+.1f}%，"
                      "动能强劲，但需注意高位追涨风险")
        elif change_1m < -3:
            judgment = "⚠️ 高位预警"
            reason = (f"52周高位({position:.0f}%)，近1月跌{change_1m:+.1f}%，"
                      "可能出现趋势反转，考虑止盈防护")
        else:
            judgment = "📈 高位整固"
            reason = (f"52周高位({position:.0f}%)，近1月{change_1m:+.1f}%，"
                      "方向尚不明确，观望为主")

    elif 30 <= position <= 70:
        # 中部区
        if ret_1y is not None and ret_1y > 15:
            judgment = "✅ 趋势稳健"
            reason = (f"区间中部({position:.0f}%)，1年涨{ret_1y:+.1f}%，"
                      "中长期趋势健康，持有或逢低布局")
        elif ret_1y is not None and ret_1y < -10:
            judgment = "📊 弱势震荡"
            reason = (f"区间中部({position:.0f}%)，但1年跌{ret_1y:+.1f}%，"
                      "整体偏弱，等待方向明确")
        else:
            judgment = "➖ 区间中性"
            reason = f"区间中部({position:.0f}%)，方向不明，建议观望"

    elif position < 30:
        # 偏低区
        if change_1m > 0:
            judgment = "📈 触底反弹"
            reason = (f"偏低区域({position:.0f}%)，近1月涨{change_1m:+.1f}%，"
                      "出现企稳迹象，关注持续力度")
        else:
            judgment = "📉 低位整理"
            reason = (f"偏低区域({position:.0f}%)，近1月跌{change_1m:+.1f}%，"
                      "仍处弱势，不宜盲目抄底")

    else:
        # 偏高区
        if change_1m > 0:
            judgment = "📈 偏强运行"
            reason = (f"偏高区域({position:.0f}%)，近1月涨{change_1m:+.1f}%，"
                      "动量向上，顺势持有")
        else:
            judgment = "📊 高位整理"
            reason = (f"偏高区域({position:.0f}%)，近1月跌{change_1m:+.1f}%，"
                      "缺乏上攻动力，注意风险")

    # 补充长期视角
    if lt_return:
        highlights = []
        for p, val in [("3年", "3y"), ("5年", "5y"), ("10年", "10y")]:
            v = lt_return.get(p)
            if v and v > 50:
                highlights.append(f"{p}+{v:+.0f}%")
        if highlights:
            reason += f"｜长期{' '.join(highlights)}，表现优异" if len(highlights) <= 2 else ""

    return judgment, reason


def _calc_position(name: str, symbol: str, lt_returns: dict = None) -> dict or None:
    """单指数 52 周位置 + 判断（yfinance → AKShare）。"""
    hist = _fetch_history(name, symbol, period="1y")
    if hist is None or len(hist) < 50:
        return None
    close = hist["Close"].iloc[-1]
    high_52w = hist["High"].max()
    low_52w = hist["Low"].min()
    range_52w = high_52w - low_52w
    position = ((close - low_52w) / range_52w) * 100 if range_52w > 0 else 50
    change_1m = 0
    if len(hist) >= 22:
        change_1m = ((close - hist["Close"].iloc[-22]) / hist["Close"].iloc[-22]) * 100
    elif len(hist) >= 2:
        change_1m = ((close - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100
    judgment, reason = generate_judgment(name, position, change_1m, lt_returns)
    return {"name": name, "symbol": symbol, "close": close,
            "high_52w": high_52w, "low_52w": low_52w,
            "position": position, "change_1m": change_1m,
            "judgment": judgment, "reason": reason}


def fetch_investment_opportunities(base_prices: list,
                                    lt_returns_dict: dict) -> tuple:
    """投资观察：计算基准指数与行业热点的52周位置+判断（规则+AI）。"""
    base_opps, raw_sector, all_for_ai = [], [], []
    for m in base_prices:
        o = _calc_position(m["name"], m["symbol"], lt_returns_dict.get(m["name"]))
        if o:
            o["lt_return"] = lt_returns_dict.get(m["name"], {})
            base_opps.append(o)
            all_for_ai.append(o)

    for name, symbol in SECTOR_INDICES:
        o = _calc_position(name, symbol, lt_returns_dict.get(name))
        if o:
            o["lt_return"] = lt_returns_dict.get(name, {})
            raw_sector.append(o)
            all_for_ai.append(o)

    ai_results = _call_deepseek_judgments(all_for_ai)
    if ai_results:
        for ai in ai_results:
            idx = ai.get("index", 0) - 1
            if 0 <= idx < len(all_for_ai):
                all_for_ai[idx]["judgment"] = ai.get("judgment", all_for_ai[idx]["judgment"])
                all_for_ai[idx]["reason"] = ai.get("reason", all_for_ai[idx]["reason"])
        print("✅ AI 判断已应用")

    sector_opps = [o for o in raw_sector
                   if o["position"] <= 15 or o["position"] >= 85
                   or (o["position"] <= 25 and abs(o["change_1m"]) > 5)
                   or (o["position"] >= 75 and o["change_1m"] < -3)]
    sector_opps.sort(key=lambda x: min(abs(x["position"] - 50), 50), reverse=True)
    sector_opps = sector_opps[:8]
    return base_opps, sector_opps


# ========== 每日综述生成 ==========

def generate_summary(market_snapshot, biz_news) -> str:
    """基于数据生成中文每日综述。"""
    lines = []

    green = sum(1 for m in market_snapshot if m["change_pct"] >= 0)
    total = len(market_snapshot)
    if total:
        if green >= total * 0.7:
            lines.append("全球股市今日整体走强，多数指数收涨，市场情绪积极。")
        elif green <= total * 0.3:
            lines.append("全球股市今日多数收跌，市场避险情绪较重。")
        else:
            lines.append("全球股市今日涨跌互现，情绪分化，关注结构性机会。")

    a_share = [m for m in market_snapshot
               if m["name"] in ("上证指数", "深证成指", "创业板指", "沪深300")]
    a_green = sum(1 for m in a_share if m["change_pct"] >= 0)
    if a_share:
        if a_green == len(a_share):
            lines.append("A股全线收红。")
        elif a_green == 0:
            lines.append("A股全线收绿，短期谨慎。")
        else:
            lines.append(f"A股{a_green}/{len(a_share)}收涨，走势分化。")

    # 热点关键词
    keywords = []
    for n in biz_news[:5]:
        t = n.get("title", "")
        for kw in ["政策", "降息", "加息", "通胀", "GDP", "PMI", "人民币", "房地产",
                    "新能源", "AI", "芯片", "光伏", "锂电", "消费", "医药",
                    "关税", "出口", "制造业", "A股", "IPO", "港股"]:
            if kw in t and kw not in keywords:
                keywords.append(kw)
    if keywords:
        lines.append(f"热点词：{' · '.join(keywords[:6])}。")

    return "\n".join(lines)


# ========== HTML 构建 ==========

def build_html_digest() -> str:
    """组装中文版 HTML 邮件。"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("📥 抓取新闻数据 ...")
    # 国内要闻：用 /v2/everything 搜硬新闻关键词，避免花边
    domestic_news = (
        fetch_everything("中国 AND (政策 OR 外交 OR 经济 OR 贸易 OR 军事 OR 疫情 OR 重大)",
                         page_size=5, days=1)
        or fetch_newsapi(country="cn", page_size=8, language=None)[:5]
    )
    # 国际要闻：用 business + general 类别减少体育娱乐
    intl_news = fetch_newsapi(language="en", page_size=5)
    # 财经
    biz_news = (
        fetch_newsapi(category="business", language="zh", page_size=5)
        or fetch_everything("财经 OR 经济 OR 金融 OR 市场", page_size=5, days=2)
    )
    # 科技
    tech_news = (
        fetch_newsapi(category="technology", language="zh", page_size=5)
        or fetch_everything("科技 OR AI OR 人工智能 OR 芯片", page_size=5, days=2)
    )
    hn_items = fetch_hackernews()

    print("📊 获取行情数据 ...")
    market_snapshot = fetch_market_snapshot(BASE_INDICES)
    lt_indices = [("上证指数","000001.SS"),("沪深300","000300.SS"),
                  ("科创50","000688.SS"),
                  ("恒生指数","^HSI"),("恒生科技","3067.HK"),
                  ("标普500","^GSPC"),("纳斯达克","^IXIC"),
                  ("日经225","^N225"),("费城半导体","^SOX"),
                  ("纳斯达克100","^NDX"),("伦敦金","GC=F")]
    periods, lt_rows, lt_dict = fetch_long_term_returns(lt_indices)
    base_opps, sector_opps = fetch_investment_opportunities(market_snapshot, lt_dict)

    summary_text = generate_summary(market_snapshot, biz_news)

    # ========== HTML 正文 ==========
    html = f"""<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
    body {{
        font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif;
        max-width:700px;margin:0 auto;padding:24px;color:#1d1d1f;background:#f5f5f7;
    }}
    .card {{
        background:#fff;border-radius:14px;padding:20px 24px;margin-bottom:18px;
        box-shadow:0 1px 3px rgba(0,0,0,.06);
    }}
    .summary {{
        background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
        color:#f0f0f0;border-radius:14px;padding:22px 24px;margin-bottom:18px;
        line-height:1.9;font-size:14.5px;
    }}
    .summary h2 {{ font-size:18px;margin:0 0 10px;color:#fff;border:none; }}
    .header {{ text-align:center;margin-bottom:20px; }}
    .header h1 {{ font-size:26px;color:#1a1a2e;margin:0; }}
    .header .date {{ color:#999;font-size:13px;margin-top:4px; }}
    h2 {{
        font-size:17px;color:#16213e;margin:0 0 12px;
        border-left:4px solid #e94560;padding-left:10px;
    }}
    .item {{
        padding:8px 0;border-bottom:1px solid #f0f0f0;
        font-size:14px;line-height:1.6;
    }}
    .item:last-child {{ border-bottom:none; }}
    .item a {{ color:#1a73e8;text-decoration:none;font-weight:500; }}
    .item a:hover {{ text-decoration:underline; }}
    .item .desc {{ color:#666;font-size:13px;margin-top:2px; }}
    .item .source {{ color:#aaa;font-size:11px; }}
    .market-table {{ width:100%;border-collapse:collapse;font-size:14px; }}
    .market-table td,.market-table th {{
        padding:7px 10px;border-bottom:1px solid #eee;text-align:left;
    }}
    .market-table th {{ color:#888;font-size:12px;font-weight:500; }}
    .green {{ color:#16a34a; }}
    .red {{ color:#dc2626; }}
    .signal {{ font-size:13px; }}
    .legend {{ font-size:12px;line-height:1.7;color:#666;padding:8px 4px; }}
    .legend b {{ color:#444; }}
    .legend .tag {{ display:inline-block;padding:1px 6px;border-radius:3px;margin:1px 2px;font-size:11px; }}
    .tag-low {{ background:#fef2f2;color:#dc2626; }}
    .tag-mid {{ background:#f5f5f4;color:#78716c; }}
    .tag-high {{ background:#f0fdf4;color:#16a34a; }}
    .footer {{
        text-align:center;color:#bbb;font-size:12px;margin-top:30px;
        padding-top:16px;border-top:1px solid #e5e5e5;
    }}
</style></head>
<body>

<div class="header">
    <h1>📋 每日大事推送</h1>
    <div class="date">{now_str} · 自动生成</div>
</div>

<!-- 综述 -->
<div class="summary">
    <h2>📌 每日综述</h2>
    <div>{summary_text.replace(chr(10), '<br>')}</div>
</div>
"""

    # ---- 全球指数今日行情 ----
    if market_snapshot:
        html += '<div class="card"><h2>📊 全球主要指数 · 今日</h2>'
        html += '<table class="market-table"><tr><th>指数</th><th>收盘</th><th>涨跌</th></tr>'
        for m in market_snapshot:
            cls = "green" if m["change_pct"] >= 0 else "red"
            html += (f'<tr><td>{m["name"]}</td><td>{m["close"]:.2f}</td>'
                     f'<td class="{cls}">{m["change_pct"]:+.2f}%</td></tr>')
        html += '</table></div>'

    # ---- 投资观察：基准指数 ----
    if base_opps:
        html += ('<div class="card"><h2>💡 投资观察 · 主要指数</h2>'
                 '<p style="color:#888;font-size:13px;margin:0 0 12px;">'
                 '当前价在52周区间的位置（0%=底部，100%=顶部）</p>')
        html += '<table class="market-table"><tr><th>指数</th><th>收盘</th><th>位置</th><th>近1月</th><th>判断</th></tr>'
        for o in base_opps:
            pos_cls = "red" if o["position"] <= 20 else ("green" if o["position"] >= 80 else "")
            m_cls = "green" if o["change_1m"] >= 0 else "red"
            html += (f'<tr>'
                     f'<td><b>{o["name"]}</b></td>'
                     f'<td>{o["close"]:.2f}</td>'
                     f'<td class="{pos_cls}">{o["position"]:.0f}%</td>'
                     f'<td class="{m_cls}">{o["change_1m"]:+.1f}%</td>'
                     f'<td class="signal">{_judgment_with_action(o["judgment"], long_desc=True)}<br>'
                     f'<span style="color:#888;font-size:11px;">{o["reason"][:70]}…</span></td>'
                     f'</tr>')
        html += '</table></div>'

    # ---- 投资观察：行业热点（评估筛选后） ----
    if sector_opps:
        html += ('<div class="card"><h2>🔥 行业热点扫描</h2>'
                 '<p style="color:#888;font-size:13px;margin:0 0 12px;">'
                 '经评估筛选，仅展示有信号意义的行业数据</p>')
        html += '<table class="market-table"><tr><th>行业</th><th>收盘</th><th>位置</th><th>近1月</th><th>判断</th></tr>'
        for o in sector_opps:
            pos_cls = "red" if o["position"] <= 20 else ("green" if o["position"] >= 80 else "")
            m_cls = "green" if o["change_1m"] >= 0 else "red"
            html += (f'<tr>'
                     f'<td><b>{o["name"]}</b></td>'
                     f'<td>{o["close"]:.2f}</td>'
                     f'<td class="{pos_cls}">{o["position"]:.0f}%</td>'
                     f'<td class="{m_cls}">{o["change_1m"]:+.1f}%</td>'
                     f'<td class="signal">{_judgment_with_action(o["judgment"], long_desc=True)}<br>'
                     f'<span style="color:#888;font-size:11px;">{o["reason"][:70]}…</span></td>'
                     f'</tr>')
        html += '</table></div>'

    # ---- 中长期涨幅 ----
    if lt_rows and periods:
        html += '<div class="card"><h2>📈 中长期涨幅一览</h2>'
        html += '<table class="market-table"><tr><th>指数</th>'
        for p_name, _ in periods:
            html += f'<th>{p_name}</th>'
        html += '</tr>'
        for row in lt_rows:
            html += '<tr>'
            for i, cell in enumerate(row):
                html += f'<td>{cell}</td>' if i > 0 else f'<td><b>{cell}</b></td>'
            html += '</tr>'
        html += '</table></div>'

    # ---- 新闻板块 ----
    def render_section(title, items):
        if not items:
            return ""
        h = f'<div class="card"><h2>{title}</h2>'
        for it in items:
            t = it["title"]
            u = it.get("url", "")
            d = it.get("desc", "")
            s = it.get("source", "")
            if u:
                h += (f'<div class="item">🔹 <a href="{u}">{t}</a>'
                      f' <span class="source">{s}</span>')
            else:
                h += f'<div class="item">🔹 {t}'
            if d:
                h += f'<div class="desc">{d}</div>'
            h += '</div>'
        h += '</div>'
        return h

    html += render_section("🌏 国内要闻", domestic_news)
    html += render_section("🌍 国际要闻", intl_news)
    html += render_section("💰 财经资讯", biz_news)
    html += render_section("🤖 科技动态", tech_news)

    if hn_items:
        html += '<div class="card"><h2>⚡ 技术社区 (Hacker News)</h2>'
        for it in hn_items:
            html += (f'<div class="item">🔹 <a href="{it["url"]}">{it["title"]}</a>'
                     f' <span class="source">HN</span></div>')
        html += '</div>'

    # ---- 操作建议汇总（四类分组） ----
    all_opps = base_opps + sector_opps
    g_buy, g_hold, g_caution, g_wait = [], [], [], []
    for o in all_opps:
        j = o["judgment"]
        a = ""
        for key, (short, _) in JUDGMENT_ACTIONS.items():
            if key in j:
                a = short
                break
        r = o["reason"][:50]
        item = f'<div style="padding:3px 0;font-size:13px;line-height:1.5;">'
        item += f'<b>{o["name"]}</b> → {o["judgment"]} '
        item += f'<span style="color:#7c3aed;">→ {a}</span>'
        item += f'<br><span style="color:#999;font-size:11px;margin-left:16px;">{r}</span></div>'
        if a in ("逢低布局", "轻仓参与"):
            g_buy.append(item)
        elif a in ("减仓防范", "注意风险"):
            g_caution.append(item)
        elif a in ("持有或加仓", "持有不追", "移动止盈", "等待方向"):
            g_hold.append(item)
        else:
            g_wait.append(item)

    if g_buy or g_hold or g_caution or g_wait:
        html += '<div class="card" style="background:#fafaf9;border:1px solid #e5e5e5;">'
        html += '<h2 style="font-size:15px;margin:0 0 10px;border-left:4px solid #e94560;padding-left:10px;">📋 今日操作建议汇总</h2>'
        if g_buy:
            html += '<p style="font-weight:600;color:#16a34a;margin:8px 0 4px;font-size:13px;">🟢 关注加仓</p>'+''.join(g_buy)
        if g_hold:
            html += '<p style="font-weight:600;color:#2563eb;margin:8px 0 4px;font-size:13px;">🔵 持有为主</p>'+''.join(g_hold[:6])
        if g_caution:
            html += '<p style="font-weight:600;color:#dc2626;margin:8px 0 4px;font-size:13px;">🟡 注意风险</p>'+''.join(g_caution)
        if g_wait:
            html += '<p style="font-weight:600;color:#78716c;margin:8px 0 4px;font-size:13px;">⚪ 观望等待</p>'+''.join(g_wait[:6])
        html += '</div>'

    # ---- 判词速查 ----
    html += """
<div class="card" style="background:#fafaf9;border:1px solid #e5e5e5;border-radius:10px;padding:16px 20px;margin-bottom:18px;">
<h2 style="font-size:14px;color:#444;margin:0 0 10px;border-left:3px solid #e94560;padding-left:8px;">📖 投资判词速查</h2>
<div class="legend">"""
    # Build legend items from JUDGMENT_ACTIONS
    legend_items = {
        "低位区（≤20%）": {"超跌关注":"逢低布局", "深跌谨慎":"等待企稳", "低位关注":"跟踪观望"},
        "偏低区（20-30%）": {"触底反弹":"轻仓参与", "低位整理":"不宜抄底"},
        "中部区（30-70%）": {"趋势稳健":"持有或加仓", "弱势震荡":"观望为主", "区间中性":"观望为宜"},
        "偏高区（70-80%）": {"偏强运行":"持有不追", "高位整理":"注意风险"},
        "高位区（≥80%）": {"强势持有":"移动止盈", "高位预警":"减仓防范", "高位整固":"等待方向"},
    }
    for zone, items in legend_items.items():
        html += f'<p style="margin:0 0 3px;"><b>{zone}</b> '
        for j, a in items.items():
            html += f'<span style="display:inline-block;padding:0 5px;border-radius:3px;font-size:11px;background:#f5f5f4;margin:0 2px;">{j} → {a}</span> '
        html += '</p>'
    html += """</div>
</div>"""

    html += f"""
<div class="footer">
    每日大事推送 · {today_str}<br>
    数据来源: NewsAPI / Yahoo Finance / Hacker News<br>
    <span style="color:#ccc">仅供信息参考，不构成投资建议 · 投资有风险，入市需谨慎</span>
</div>
</body></html>"""
    return html


# ========== 发邮件 ==========

def send_email(html_content: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📋 每日大事推送 - {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)

    print(f"✅ 邮件已发送至 {RECIPIENT_EMAIL}")


def main():
    print("📥 正在生成每日大事推送 ...")
    html = build_html_digest()
    print("📤 正在发送邮件 ...")
    send_email(html)
    print("🎉 完成!")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Daily News Digest - 每日大事推送
每天自动抓取国内外要闻、财经资讯、股市行情、科技动态，通过邮件推送。
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import requests
import yfinance as yf

# ===== 配置（从环境变量读取，GitHub Actions 中通过 Secrets 设置）=====
SMTP_SERVER = os.getenv("SMTP_SERVER", "mail.cstnet.cn")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")


def fetch_newsapi(category: str, page_size: int = 5, language: str = "zh") -> list:
    """从 NewsAPI 获取新闻头条。"""
    if not NEWSAPI_KEY:
        return []
    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "apiKey": NEWSAPI_KEY,
        "category": category,
        "pageSize": page_size,
        "language": language,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        articles = resp.json().get("articles", [])
        return [
            {"title": a.get("title", ""), "url": a.get("url", ""),
             "source": a.get("source", {}).get("name", "")}
            for a in articles if a.get("title")
        ]
    except Exception as e:
        print(f"NewsAPI [{category}/{language}] error: {e}")
        return []


def fetch_hackernews() -> list:
    """获取 Hacker News 热门技术文章。"""
    try:
        resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        )
        top_ids = resp.json()[:10]
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
                })
        return items[:5]
    except Exception as e:
        print(f"Hacker News error: {e}")
        return []


def fetch_market_data() -> list:
    """获取全球主要指数行情。"""
    indices = {
        "上证指数": "000001.SS",
        "深证成指": "399001.SZ",
        "恒生指数": "^HSI",
        "日经225": "^N225",
        "标普500": "^GSPC",
        "纳斯达克": "^IXIC",
    }
    results = []
    try:
        for name, symbol in indices.items():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if len(hist) >= 2:
                close = hist["Close"].iloc[-1]
                prev_close = hist["Close"].iloc[-2]
                change = ((close - prev_close) / prev_close) * 100
                emoji = "🟢" if change >= 0 else "🔴"
                results.append(f"{emoji} {name}:  {close:.2f}  ({change:+.2f}%)")
            elif len(hist) == 1:
                results.append(f"📊 {name}:  {hist['Close'].iloc[-1]:.2f}")
        return results
    except Exception as e:
        print(f"Market data error: {e}")
        return ["📊 行情数据暂时无法获取"]


def build_html_digest() -> str:
    """组装 HTML 邮件内容。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ========== 并行抓取各板块 ==========
    world_news = fetch_newsapi("general", 5, "zh")       # 国内要闻
    intl_news = fetch_newsapi("general", 5, "en")         # 国际要闻
    business_news = fetch_newsapi("business", 5, "zh")    # 中文财经
    tech_news = fetch_newsapi("technology", 5, "en")      # 国际科技
    hn_stories = fetch_hackernews()                       # HackerNews
    market_data = fetch_market_data()                     # 指数行情

    # ========== 组装 HTML ==========
    html = f"""
    <html>
    <head><meta charset="utf-8"><style>
        body {{
            font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            max-width: 680px; margin: 0 auto; padding: 20px; color: #333;
            background: #fafafa;
        }}
        h1 {{ color: #1a1a2e; font-size: 24px; }}
        .header {{ border-bottom: 3px solid #e94560; padding-bottom: 12px; margin-bottom: 20px; }}
        .header .date {{ color: #888; font-size: 14px; }}
        h2 {{ color: #16213e; font-size: 18px; margin: 24px 0 12px;
             border-left: 4px solid #e94560; padding-left: 12px; }}
        .market-box {{
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: #fff; padding: 16px 20px; border-radius: 10px;
            line-height: 2.0; font-size: 15px;
        }}
        .item {{
            padding: 10px 0; border-bottom: 1px solid #eee;
            display: flex; align-items: flex-start; gap: 8px;
        }}
        .item a {{ color: #1a73e8; text-decoration: none; font-size: 15px; }}
        .item a:hover {{ text-decoration: underline; }}
        .source {{ color: #999; font-size: 12px; white-space: nowrap; }}
        .footer {{ margin-top: 36px; padding-top: 12px; border-top: 1px solid #ddd;
                   color: #bbb; font-size: 12px; text-align: center; }}
    </style></head>
    <body>
        <div class="header">
            <h1>📋 每日大事推送</h1>
            <div class="date">{now} · 自动生成</div>
        </div>
    """

    # ---- 行情板块 ----
    if market_data:
        html += '<h2>📊 全球主要指数</h2><div class="market-box">'
        for line in market_data:
            html += f'<div>{line}</div>'
        html += '</div>'

    # ---- 各新闻板块 ----
    sections = [
        ("🌏 国内要闻", world_news),
        ("🌍 国际要闻", intl_news),
        ("💰 财经资讯", business_news),
        ("🤖 科技动态", tech_news),
        ("⚡ 技术社区精选", hn_stories),
    ]
    for title, items in sections:
        if not items:
            continue
        html += f'<h2>{title}</h2>'
        for item in items:
            t = item["title"]
            u = item.get("url", "")
            s = item.get("source", "")
            if u:
                html += (f'<div class="item">🔹 <a href="{u}">{t}</a>'
                         f' <span class="source">{s}</span></div>')
            else:
                html += f'<div class="item">🔹 {t}</div>'

    # ---- 尾部 ----
    html += f"""
        <div class="footer">
            <p>本邮件由 Daily News Digest 自动生成 · 数据来源: NewsAPI / Yahoo Finance / Hacker News</p>
            <p>{now}</p>
        </div>
    </body></html>
    """
    return html


def send_email(html_content: str):
    """通过 SMTP 发送邮件。"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📋 每日大事推送 - {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)

    print(f"✅ Email sent to {RECIPIENT_EMAIL}")


def main():
    print("📥 Building daily news digest ...")
    html = build_html_digest()
    print("📤 Sending email ...")
    send_email(html)
    print("🎉 Done!")


if __name__ == "__main__":
    main()

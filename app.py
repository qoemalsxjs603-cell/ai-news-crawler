
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

st.set_page_config(
    page_title="AI 韩国游戏新闻摘要系统",
    layout="wide"
)

st.markdown(
    """
    <style>
    html, body, [class*="css"], .stApp, .stMarkdown, .stDataFrame {
        font-family: Arial, "Microsoft YaHei", "Noto Sans KR", "Noto Sans CJK SC", sans-serif !important;
    }
    h1, h2, h3, p, div, span, button {
        font-family: Arial, "Microsoft YaHei", "Noto Sans KR", "Noto Sans CJK SC", sans-serif !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

client = OpenAI(
    api_key=st.secrets["OPENAI_API_KEY"]
)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

BASE_URL = "https://www.inven.co.kr"
LIST_URL = "https://www.inven.co.kr/webzine/news/"


def get_korea_today():
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def get_korea_yesterday():
    return (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)).strftime("%Y-%m-%d")


def safe_get(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=20
    )
    response.raise_for_status()
    return response.text


def normalize_url(url):
    if url.startswith("http"):
        return url
    return BASE_URL + url


def extract_date_from_text(text):
    match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return ""


def extract_article_date(article_soup):
    text = article_soup.get_text(" ", strip=True)
    return extract_date_from_text(text)


def extract_article_body(article_soup):
    candidates = [
        "#newsContent",
        "div#newsContent",
        ".articleContent",
        ".contentBody",
        ".viewContent"
    ]

    for selector in candidates:
        content = article_soup.select_one(selector)
        if content:
            body = content.get_text("\n", strip=True)
            if len(body) > 100:
                return body

    text = article_soup.get_text("\n", strip=True)
    return text[:5000]


def fallback_summary(title):
    clean_title = re.sub(r"\s+", " ", title).strip()
    korean = f"이 기사는 '{clean_title}' 관련 인벤 주요 게임 소식을 다룬다."
    chinese = f"这篇新闻介绍了与《{clean_title}》相关的韩国 Inven 主要游戏资讯。"
    return korean, chinese


def summarize_korean_and_chinese(title, content):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
너는 한국 게임 뉴스 전문 에디터이자 한중 번역가다.

반드시 아래 JSON 형식만 출력해라.
설명문, 코드블록, 따옴표 밖 문장, 줄바꿈 설명은 절대 넣지 마라.

{
  "korean_summary": "한국어 1줄 요약",
  "chinese_summary": "위 한국어 요약을 자연스러운 중국어 간체로 번역한 1줄 요약"
}

규칙:
1. korean_summary는 반드시 한국어 한 문장만 작성한다.
2. chinese_summary는 korean_summary와 같은 의미의 중국어 간체 번역문이어야 한다.
3. 각 요약은 너무 길지 않게 60자 안팎으로 작성한다.
4. 기사 제목만 반복하지 말고, 본문 핵심을 반영한다.
"""
                },
                {
                    "role": "user",
                    "content": f"기사 제목: {title}\n\n기사 본문:\n{content[:3000]}"
                }
            ],
            temperature=0.2
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        data = json.loads(raw)

        korean_summary = data.get("korean_summary", "").strip()
        chinese_summary = data.get("chinese_summary", "").strip()

        if not korean_summary or not chinese_summary:
            return fallback_summary(title)

        korean_summary = korean_summary.replace("\n", " ")
        chinese_summary = chinese_summary.replace("\n", " ")

        return korean_summary, chinese_summary

    except Exception:
        return fallback_summary(title)


def is_major_news_candidate(a_tag):
    parent_text = ""
    parent_classes = ""

    parent = a_tag
    for _ in range(5):
        if parent is None:
            break

        parent_text += " " + parent.get_text(" ", strip=True)
        parent_classes += " " + " ".join(parent.get("class", []))
        parent_id = parent.get("id", "")
        parent_classes += " " + parent_id

        parent = parent.parent

    check_text = (parent_text + " " + parent_classes).lower()

    major_keywords = [
        "주요뉴스",
        "mainnews",
        "main_news",
        "headline",
        "topnews",
        "top_news",
        "issue",
        "hot"
    ]

    return any(keyword.lower() in check_text for keyword in major_keywords)


def collect_inven_major_news_links():
    html = safe_get(LIST_URL)
    soup = BeautifulSoup(html, "lxml")

    all_article_links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href")

        if "/webzine/news/" not in href:
            continue

        if "news=" not in href:
            continue

        title = a_tag.get_text(" ", strip=True)

        if len(title) < 5:
            continue

        link = normalize_url(href)

        all_article_links.append({
            "title": title,
            "link": link,
            "is_major": is_major_news_candidate(a_tag)
        })

    unique_items = []
    seen = set()

    for item in all_article_links:
        if item["link"] in seen:
            continue

        seen.add(item["link"])
        unique_items.append(item)

    major_items = [item for item in unique_items if item["is_major"]]

    if major_items:
        return major_items

    return unique_items[:12]


def crawl_inven_major_news_by_date(target_date):
    results = []
    article_items = collect_inven_major_news_links()

    for item in article_items:
        try:
            article_html = safe_get(item["link"])
            article_soup = BeautifulSoup(article_html, "lxml")

            article_date = extract_article_date(article_soup)

            if article_date != target_date:
                continue

            content = extract_article_body(article_soup)

            if len(content) < 80:
                continue

            korean_summary, chinese_summary = summarize_korean_and_chinese(
                item["title"],
                content
            )

            results.append({
                "网站": "INVEN",
                "新闻分类": "主要新闻",
                "新闻标题": item["title"],
                "韩文一行摘要": korean_summary,
                "中文翻译摘要": chinese_summary,
                "原文链接": item["link"],
                "发布日期": article_date
            })

        except Exception:
            continue

    return results


def run_summary(target_date, label):
    with st.spinner(f"正在收集并分析{label}的主要新闻，请稍候..."):
        results = crawl_inven_major_news_by_date(target_date)
        df = pd.DataFrame(results)

        if df.empty:
            st.warning(f"没有找到{label}发布的 Inven 主要新闻。检索日期：{target_date}")
        else:
            st.success(f"完成！{label}共找到 {len(df)} 条主要新闻。")
            st.dataframe(
                df,
                use_container_width=True
            )

            excel_file = f"inven_major_news_summary_ko_zh_{target_date}.xlsx"
            df.to_excel(
                excel_file,
                index=False
            )

            with open(excel_file, "rb") as f:
                st.download_button(
                    label="下载 Excel 文件",
                    data=f,
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )


st.title("AI 韩国游戏新闻摘要系统")

st.write("本系统整理韩国 Inven 游戏新闻中“主要新闻”栏目内容，并生成韩文一行摘要及对应中文翻译。")

today = get_korea_today()
yesterday = get_korea_yesterday()

st.info(f"今日检索日期：{today} / 前一天检索日期：{yesterday}")

col1, col2 = st.columns(2)

with col1:
    if st.button("收集今日主要新闻"):
        run_summary(today, "今日")

with col2:
    if st.button("收集前一天主要新闻"):
        run_summary(yesterday, "前一天")

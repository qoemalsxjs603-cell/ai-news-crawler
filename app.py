
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
        font-family: Arial, "Microsoft YaHei", "Noto Sans CJK SC", sans-serif !important;
    }
    h1, h2, h3, p, div, span, button {
        font-family: Arial, "Microsoft YaHei", "Noto Sans CJK SC", sans-serif !important;
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


def make_simple_chinese_summary(title, content):
    clean_title = re.sub(r"\s+", " ", title).strip()
    clean_content = re.sub(r"\s+", " ", content).strip()

    if clean_title:
        return f"这篇主要新闻介绍了《{clean_title}》相关内容。"

    return f"这篇主要新闻介绍了韩国游戏行业相关动态：{clean_content[:40]}。"


def summarize_text(title, content):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "你是游戏新闻编辑。请只用中文输出一句话摘要，不要换行，不要使用项目符号，不超过45个汉字。"
                },
                {
                    "role": "user",
                    "content": f"标题：{title}\n\n正文：{content[:2500]}"
                }
            ],
            temperature=0.2
        )

        summary = response.choices[0].message.content.strip()
        summary = summary.replace("\n", " ")
        return summary

    except Exception:
        return make_simple_chinese_summary(title, content)


def is_major_news_candidate(a_tag):
    """
    인벤 뉴스 페이지의 '주요뉴스' 영역을 우선적으로 잡기 위한 필터.
    사이트 구조가 조금 바뀌어도 동작하도록 class/id/주변 텍스트를 함께 확인한다.
    """
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

    # 주요뉴스 영역을 못 찾는 경우, 페이지 상단 기사 일부를 주요뉴스 후보로 사용
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

            summary = summarize_text(
                item["title"],
                content
            )

            results.append({
                "网站": "INVEN",
                "新闻分类": "主要新闻",
                "新闻标题": item["title"],
                "中文一句话摘要": summary,
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

            excel_file = f"inven_major_news_summary_zh_{target_date}.xlsx"
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

st.write("本系统整理韩国 Inven 游戏新闻中“主要新闻”栏目内容，并生成中文一句话摘要。")

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


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

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

BASE_URL = "https://www.inven.co.kr"
HOT_NEWS_URL = "https://www.inven.co.kr/webzine/news/?hotnews=1"


def get_korea_today():
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def get_korea_yesterday():
    return (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)).strftime("%Y-%m-%d")


def safe_get(url):
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.text


def normalize_url(url):
    if url.startswith("http"):
        return url
    return BASE_URL + url


def clean_text(text):
    text = re.sub(r"\s+", " ", text)
    remove_words = [
        "인벤", "기자", "댓글", "공유", "스크랩", "목록", "관련기사",
        "Copyright", "무단전재", "재배포 금지"
    ]
    for word in remove_words:
        text = text.replace(word, " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_date_from_text(text):
    match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return ""


def extract_article_date(article_soup):
    return extract_date_from_text(article_soup.get_text(" ", strip=True))


def extract_article_title(article_soup, fallback_title):
    candidates = [
        "h1",
        ".articleTitle",
        ".newsTitle",
        ".title",
        ".view_title",
        ".article_title"
    ]

    for selector in candidates:
        tag = article_soup.select_one(selector)
        if tag:
            title = clean_text(tag.get_text(" ", strip=True))
            if len(title) >= 5:
                return title

    og_title = article_soup.select_one('meta[property="og:title"]')
    if og_title and og_title.get("content"):
        title = clean_text(og_title.get("content"))
        title = title.replace(" - 인벤", "").replace("| 인벤", "").strip()
        if len(title) >= 5:
            return title

    return clean_text(fallback_title)


def extract_article_body(article_soup):
    candidates = [
        "#newsContent",
        "div#newsContent",
        ".articleContent",
        ".contentBody",
        ".viewContent",
        ".article_body",
        ".news_content"
    ]

    for selector in candidates:
        content = article_soup.select_one(selector)
        if content:
            for tag in content(["script", "style", "iframe", "ins"]):
                tag.decompose()
            body = clean_text(content.get_text(" ", strip=True))
            if len(body) > 30:
                return body

    body = clean_text(article_soup.get_text(" ", strip=True))
    return body[:6000]


def fallback_korean_summary(content):
    content = clean_text(content)
    sentences = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+", content)

    for sentence in sentences:
        sentence = sentence.strip()
        if 25 <= len(sentence) <= 140:
            return sentence

    return content[:100] + "..."


def summarize_article(title, content):
    body_for_ai = clean_text(content)[:3500]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": """
너는 한국 게임 뉴스 전문 에디터다.
반드시 기사 제목이 아니라 기사 본문 내용을 바탕으로 요약해라.
결과는 반드시 JSON으로만 출력해라.

형식:
{
  "korean_summary": "기사 내용을 바탕으로 한 한국어 1줄 요약",
  "chinese_summary": "위 한국어 요약을 자연스럽게 번역한 중국어 간체 1줄"
}

규칙:
- korean_summary는 반드시 한국어 한 문장만 작성한다.
- chinese_summary는 korean_summary와 같은 의미의 중국어 간체 번역문이어야 한다.
- 제목만 반복하지 않는다.
- 기사 본문에서 핵심 사건, 발표, 업데이트, 출시, 성과 중 가장 중요한 내용을 잡는다.
- 각 요약은 80자 이내로 작성한다.
"""
                },
                {
                    "role": "user",
                    "content": f"기사 제목: {title}\n\n기사 본문:\n{body_for_ai}"
                }
            ],
            temperature=0.1
        )

        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        korean = data.get("korean_summary", "").strip().replace("\n", " ")
        chinese = data.get("chinese_summary", "").strip().replace("\n", " ")

        if korean and chinese:
            return korean, chinese

    except Exception:
        pass

    korean = fallback_korean_summary(content)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "请把下面这句韩文自然翻译成中文简体，只输出译文。"
                },
                {
                    "role": "user",
                    "content": korean
                }
            ],
            temperature=0.1
        )
        chinese = response.choices[0].message.content.strip().replace("\n", " ")
    except Exception:
        chinese = "中文翻译生成失败。"

    return korean, chinese


def collect_inven_hot_news_links():
    all_items = []

    # 주요뉴스 페이지가 여러 페이지로 나뉘어 있을 수 있어 1~3페이지까지 확인
    for page_no in range(1, 4):
        if page_no == 1:
            url = HOT_NEWS_URL
        else:
            url = f"{HOT_NEWS_URL}&pg={page_no}"

        try:
            html = safe_get(url)
        except Exception:
            continue

        soup = BeautifulSoup(html, "lxml")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href")

            if "/webzine/news/" not in href:
                continue

            if "news=" not in href:
                continue

            link_title = clean_text(a_tag.get_text(" ", strip=True))

            if len(link_title) < 3:
                continue

            link = normalize_url(href)

            all_items.append({
                "title": link_title,
                "link": link
            })

    unique_items = []
    seen = set()

    for item in all_items:
        if item["link"] in seen:
            continue
        seen.add(item["link"])
        unique_items.append(item)

    return unique_items


def crawl_inven_hot_news_by_date(target_date):
    results = []
    article_items = collect_inven_hot_news_links()

    for item in article_items:
        try:
            article_html = safe_get(item["link"])
            article_soup = BeautifulSoup(article_html, "lxml")

            article_date = extract_article_date(article_soup)

            if article_date != target_date:
                continue

            real_title = extract_article_title(article_soup, item["title"])
            content = extract_article_body(article_soup)

            if len(content) < 30:
                continue

            korean_summary, chinese_summary = summarize_article(real_title, content)

            results.append({
                "网站": "INVEN",
                "新闻分类": "主要新闻",
                "新闻标题": real_title,
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
        results = crawl_inven_hot_news_by_date(target_date)
        df = pd.DataFrame(results)

        if df.empty:
            st.warning(f"没有找到{label}发布的 Inven 主要新闻。检索日期：{target_date}")
        else:
            # 표 번호를 1부터 시작
            df.index = range(1, len(df) + 1)

            st.success(f"完成！{label}共找到 {len(df)} 条主要新闻。")
            st.dataframe(df, use_container_width=True)

            excel_file = f"inven_hot_news_summary_ko_zh_{target_date}.xlsx"
            df.to_excel(excel_file, index=True, index_label="编号")

            with open(excel_file, "rb") as f:
                st.download_button(
                    label="下载 Excel 文件",
                    data=f,
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )


st.title("AI 韩国游戏新闻摘要系统")

st.write("本系统整理韩国 Inven 游戏新闻中“主要新闻”页面内容，并生成韩文一行摘要及对应中文翻译。")

today = get_korea_today()
yesterday = get_korea_yesterday()

st.info(f"前一天检索日期：{yesterday} / 今日检索日期：{today}")

col1, col2 = st.columns(2)

with col1:
    if st.button("收集前一天主要新闻"):
        run_summary(yesterday, "前一天")

with col2:
    if st.button("收集今日主要新闻"):
        run_summary(today, "今日")


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
LIST_URL = "https://www.inven.co.kr/webzine/news/"


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


def extract_date_from_text(text):
    match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return ""


def extract_article_date(article_soup):
    return extract_date_from_text(article_soup.get_text(" ", strip=True))


def clean_text(text):
    text = re.sub(r"\s+", " ", text)
    remove_words = [
        "인벤", "기자", "댓글", "공유", "스크랩", "목록", "관련기사",
        "Copyright", "무단전재", "재배포 금지"
    ]
    for word in remove_words:
        text = text.replace(word, " ")
    return re.sub(r"\s+", " ", text).strip()


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
            if len(body) > 120:
                return body

    body = clean_text(article_soup.get_text(" ", strip=True))
    return body[:6000]


def fallback_korean_summary(content):
    content = clean_text(content)
    sentences = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+", content)

    for sentence in sentences:
        sentence = sentence.strip()
        if 30 <= len(sentence) <= 140:
            return sentence

    return content[:100] + "..."


def summarize_article(title, content):
    """
    기사 본문을 보고 한국어 1줄 요약 + 중국어 1줄 번역 생성.
    GPT 실패 시에도 본문 첫 핵심 문장을 기반으로 최소 요약을 만든다.
    """

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


def is_major_news_candidate(a_tag):
    parent_text = ""
    parent_classes = ""

    parent = a_tag
    for _ in range(5):
        if parent is None:
            break

        parent_text += " " + parent.get_text(" ", strip=True)
        parent_classes += " " + " ".join(parent.get("class", []))
        parent_classes += " " + parent.get("id", "")
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

        title = clean_text(a_tag.get_text(" ", strip=True))

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

            if len(content) < 120:
                continue

            korean_summary, chinese_summary = summarize_article(item["title"], content)

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
            st.dataframe(df, use_container_width=True)

            excel_file = f"inven_major_news_summary_ko_zh_{target_date}.xlsx"
            df.to_excel(excel_file, index=False)

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

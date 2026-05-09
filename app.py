import re
from urllib.parse import urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI


# =====================
# 基本设置
# =====================

BASE_URL = "https://www.inven.co.kr"
LIST_URL = "https://www.inven.co.kr/webzine/news/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,zh-CN;q=0.8,zh;q=0.7,en;q=0.6",
}

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
OPENAI_MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# =====================
# 工具函数
# =====================

def clean_text(text):
    text = re.sub(r"\s+", " ", text or "")
    return text.strip()


def fetch_html(url):
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def simple_chinese_fallback_summary(title, text):
    """当 OpenAI API 暂时不可用时，生成一个可读的中文备用摘要。"""
    cleaned = clean_text(text)
    sentences = re.split(r"(?<=[。！？.!?])\s+|[\n\r]+", cleaned)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    picked = sentences[:3]
    if not picked and cleaned:
        picked = [cleaned[:180]]

    summary_lines = []
    for idx, sentence in enumerate(picked, 1):
        summary_lines.append(f"{idx}. {sentence[:180]}")

    if not summary_lines:
        summary_lines.append("1. 未能提取足够的正文内容。")

    keywords = []
    candidates = re.findall(r"[가-힣A-Za-z0-9]{2,}", title + " " + cleaned[:1000])
    for word in candidates:
        if word not in keywords:
            keywords.append(word)
        if len(keywords) >= 5:
            break

    if not keywords:
        keywords = ["游戏", "新闻", "更新", "玩家", "市场"]

    return (
        "[中文摘要]\n"
        + "\n".join(summary_lines)
        + "\n\n[核心关键词]\n"
        + "、".join(keywords)
        + "\n\n※ OpenAI API 暂时不可用，因此显示本地备用摘要。"
    )


def summarize_text_in_chinese(title, text):
    if not text:
        return "未能提取正文内容。"

    if not client:
        return simple_chinese_fallback_summary(title, text)

    prompt = f"""
请用中文总结以下韩国游戏新闻。

要求：
1. 先给出 [中文摘要]
2. 用 3 条要点概括核心内容
3. 再给出 [核心关键词]
4. 提取 5 个关键词
5. 不要输出韩文
6. 不要解释你的工作过程

新闻标题：
{title}

新闻正文：
{text[:5000]}
"""

    models_to_try = []
    for model in [OPENAI_MODEL, "gpt-4.1-mini", "gpt-4o-mini"]:
        if model and model not in models_to_try:
            models_to_try.append(model)

    last_error = ""

    for model in models_to_try:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是专业的中文游戏新闻编辑，只用中文输出。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
            )
            result = response.choices[0].message.content
            if result:
                return result.strip()

        except Exception as e:
            last_error = str(e)

    fallback = simple_chinese_fallback_summary(title, text)
    return fallback + f"\n\n※ API 错误信息：{last_error[:300]}"


# =====================
# Inven 爬虫
# =====================

def collect_inven_article_links(max_articles=10):
    html = fetch_html(LIST_URL)
    soup = BeautifulSoup(html, "lxml")

    links = []

    for a_tag in soup.select("a[href]"):
        href = a_tag.get("href", "")
        title = clean_text(a_tag.get_text(" ", strip=True))

        if not href:
            continue

        full_url = urljoin(BASE_URL, href)

        # Inven 新闻正文链接通常包含 /webzine/news/ 与 news= 参数
        if "/webzine/news/" not in full_url:
            continue

        if "news=" not in full_url:
            continue

        if not title or len(title) < 4:
            continue

        # 排除菜单、分页、广告等无效文本
        blocked_words = ["더보기", "뉴스", "인벤", "전체", "댓글", "로그인"]
        if title in blocked_words:
            continue

        item = {
            "标题": title,
            "链接": full_url,
        }

        if item not in links:
            links.append(item)

        if len(links) >= max_articles:
            break

    return links


def extract_inven_article_content(url):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()

    selectors = [
        "#newsContent",
        "#articleContent",
        ".articleContent",
        ".newsContent",
        ".news_content",
        ".contentBody",
        ".article_body",
        ".view_content",
    ]

    for selector in selectors:
        content_div = soup.select_one(selector)
        if content_div:
            text = content_div.get_text("\n", strip=True)
            text = clean_text(text)
            if len(text) > 100:
                return text

    # 备用方案：从正文区域中找最长文本
    candidates = []
    for div in soup.select("article, section, div"):
        text = clean_text(div.get_text(" ", strip=True))
        if len(text) > 300:
            candidates.append(text)

    if candidates:
        return max(candidates, key=len)

    return ""


def crawl_inven(max_articles=10):
    results = []

    article_links = collect_inven_article_links(max_articles=max_articles)

    for item in article_links:
        title = item["标题"]
        link = item["链接"]

        try:
            content = extract_inven_article_content(link)
            summary = summarize_text_in_chinese(title, content)

            results.append({
                "网站": "Inven",
                "标题": title,
                "链接": link,
                "中文摘要": summary,
            })

        except Exception as e:
            results.append({
                "网站": "Inven",
                "标题": title,
                "链接": link,
                "中文摘要": f"处理失败：{str(e)[:300]}",
            })

    return results


# =====================
# Streamlit UI
# =====================

st.set_page_config(
    page_title="AI 游戏新闻摘要系统",
    page_icon="📰",
    layout="wide",
)

st.title("AI 游戏新闻摘要系统")

st.write(
    "本系统会自动收集 Inven 的游戏新闻，并使用 AI 生成中文摘要。"
)

max_articles = st.slider(
    "选择要收集的新闻数量",
    min_value=1,
    max_value=20,
    value=10,
)

if st.button("开始收集新闻"):

    with st.spinner("正在收集新闻并生成中文摘要，请稍等..."):

        all_results = crawl_inven(max_articles=max_articles)

        df = pd.DataFrame(all_results)

        if df.empty:
            st.warning("没有收集到新闻。请稍后再试，或检查网站结构是否发生变化。")
        else:
            st.success("完成！")
            st.dataframe(df, use_container_width=True)

            excel_file = "inven_news_summary_zh.xlsx"
            df.to_excel(excel_file, index=False)

            with open(excel_file, "rb") as f:
                st.download_button(
                    label="下载 Excel 文件",
                    data=f,
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

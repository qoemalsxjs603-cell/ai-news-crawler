import re
from urllib.parse import urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_soup(url):
    res = requests.get(url, headers=headers, timeout=15)
    res.raise_for_status()
    return BeautifulSoup(res.text, "lxml")


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def summarize_text(text):
    if not text:
        return "요약할 본문이 없습니다."

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
아래 뉴스 기사를 분석하라.
반드시 중국어를 먼저 출력하고, 그 다음 한국어를 출력하라.

[中文摘要]
- 핵심 3줄 요약
- 핵심 키워드 5개

[한국어 요약]
- 핵심 3줄 요약
- 핵심 키워드 5개
""",
                },
                {"role": "user", "content": text[:4000]},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"요약 실패: {e}"


def extract_article_text(soup):
    selectors = [
        "#newsContent",
        ".view_content",
        ".article_content",
        ".article-content",
        ".board_main_view",
        ".view_body",
        "article",
    ]

    for selector in selectors:
        box = soup.select_one(selector)
        if box:
            text = clean_text(box.get_text(" ", strip=True))
            if len(text) > 80:
                return text

    paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 30]
    return clean_text(" ".join(paragraphs))


def crawl_inven(max_count=5):
    results = []
    list_url = "https://www.inven.co.kr/webzine/news/"

    try:
        soup = fetch_soup(list_url)
    except Exception as e:
        st.warning(f"인벤 목록 페이지 수집 실패: {e}")
        return results

    candidates = []

    for a in soup.select("a[href]"):
        title = clean_text(a.get_text(" ", strip=True))
        href = a.get("href", "")

        if not title or len(title) < 8:
            continue
        if "webzine/news" not in href:
            continue
        if title in ["뉴스", "전체뉴스", "주요뉴스"]:
            continue

        link = urljoin(list_url, href)
        candidates.append((title, link))

    seen = set()
    unique_candidates = []
    for title, link in candidates:
        if link in seen:
            continue
        seen.add(link)
        unique_candidates.append((title, link))

    for title, link in unique_candidates[:max_count]:
        try:
            article_soup = fetch_soup(link)
            content = extract_article_text(article_soup)

            if not content:
                content = title

            summary = summarize_text(content)

            results.append(
                {
                    "사이트": "인벤",
                    "제목": title,
                    "링크": link,
                    "AI요약": summary,
                }
            )
        except Exception as e:
            results.append(
                {
                    "사이트": "인벤",
                    "제목": title,
                    "링크": link,
                    "AI요약": f"수집 실패: {e}",
                }
            )

    return results


def crawl_ruliweb(max_count=5):
    results = []
    list_url = "https://bbs.ruliweb.com/news"

    try:
        soup = fetch_soup(list_url)
    except Exception as e:
        st.warning(f"루리웹 목록 페이지 수집 실패: {e}")
        return results

    candidates = []

    for a in soup.select("a[href]"):
        title = clean_text(a.get_text(" ", strip=True))
        href = a.get("href", "")

        if not title or len(title) < 8:
            continue
        if href.startswith("#"):
            continue

        link = urljoin(list_url, href)

        if "bbs.ruliweb.com/news/read" not in link and "/news/" not in link:
            continue
        if title in ["뉴스", "읽을거리", "동영상"]:
            continue

        candidates.append((title, link))

    seen = set()
    unique_candidates = []
    for title, link in candidates:
        if link in seen:
            continue
        seen.add(link)
        unique_candidates.append((title, link))

    for title, link in unique_candidates[:max_count]:
        try:
            article_soup = fetch_soup(link)
            content = extract_article_text(article_soup)

            if not content:
                content = title

            summary = summarize_text(content)

            results.append(
                {
                    "사이트": "루리웹",
                    "제목": title,
                    "링크": link,
                    "AI요약": summary,
                }
            )
        except Exception as e:
            results.append(
                {
                    "사이트": "루리웹",
                    "제목": title,
                    "링크": link,
                    "AI요약": f"수집 실패: {e}",
                }
            )

    return results


st.title("AI 게임 뉴스 요약 시스템")
st.write("인벤 / 루리웹 뉴스를 자동 수집하고 AI가 중국어 + 한국어로 요약합니다.")

max_count = st.slider("사이트별 수집 기사 수", min_value=1, max_value=10, value=5)

if st.button("뉴스 수집 시작"):
    with st.spinner("AI 분석 중..."):
        all_results = []
        all_results.extend(crawl_inven(max_count=max_count))
        all_results.extend(crawl_ruliweb(max_count=max_count))

        df = pd.DataFrame(all_results)

        if df.empty:
            st.error("수집된 기사가 없습니다. 사이트 구조가 바뀌었거나 접속이 차단되었을 수 있습니다.")
        else:
            st.success(f"완료! 총 {len(df)}개 기사를 정리했습니다.")
            st.dataframe(df, use_container_width=True)

            excel_file = "news_summary.xlsx"
            df.to_excel(excel_file, index=False)

            with open(excel_file, "rb") as f:
                st.download_button(
                    label="엑셀 다운로드",
                    data=f,
                    file_name="news_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

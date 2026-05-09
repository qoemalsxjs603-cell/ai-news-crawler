```python
import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from openai import OpenAI

# ======================
# OpenAI
# ======================

client = OpenAI(
    api_key=st.secrets["OPENAI_API_KEY"]
)

# ======================
# 날짜
# ======================

yesterday = datetime.now() - timedelta(days=1)
target_date = yesterday.strftime("%Y-%m-%d")

# ======================
# 요약 함수
# ======================

def summarize_text(text):

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
                    뉴스 핵심 내용을 3줄로 요약하고,
                    핵심 키워드 5개를 정리해라.
                    """
                },
                {
                    "role": "user",
                    "content": text[:5000]
                }
            ],
            temperature=0.3
        )

        return response.choices[0].message.content

    except Exception as e:
        return str(e)

# ======================
# 인벤
# ======================

def crawl_inven(page):

    results = []

    url = "https://www.inven.co.kr/webzine/news/"

    page.goto(url)

    time.sleep(2)

    soup = BeautifulSoup(page.content(), "lxml")

    articles = soup.select("ul.news_list li")

    for article in articles[:5]:

        try:
            title_tag = article.select_one(".tit")
            date_tag = article.select_one(".date")
            link_tag = article.select_one("a")

            if not title_tag:
                continue

            title = title_tag.text.strip()
            date_text = date_tag.text.strip()

            link = link_tag["href"]

            article_page = page.context.new_page()
            article_page.goto(link)

            article_soup = BeautifulSoup(
                article_page.content(),
                "lxml"
            )

            content_div = article_soup.select_one("#newsContent")

            if not content_div:
                continue

            content = content_div.get_text(
                "\n",
                strip=True
            )

            summary = summarize_text(content)

            results.append({
                "사이트": "인벤",
                "제목": title,
                "날짜": date_text,
                "링크": link,
                "AI요약": summary
            })

            article_page.close()

        except:
            pass

    return results

# ======================
# 루리웹
# ======================

def crawl_ruliweb(page):

    results = []

    url = "https://bbs.ruliweb.com/news"

    page.goto(url)

    time.sleep(2)

    soup = BeautifulSoup(page.content(), "lxml")

    rows = soup.select(
        "table.board_list_table tbody tr"
    )

    for row in rows[:5]:

        try:
            title_tag = row.select_one(".subject_link")

            if not title_tag:
                continue

            title = title_tag.text.strip()

            link = (
                "https://bbs.ruliweb.com"
                + title_tag["href"]
            )

            article_page = page.context.new_page()
            article_page.goto(link)

            article_soup = BeautifulSoup(
                article_page.content(),
                "lxml"
            )

            content_div = article_soup.select_one(
                ".view_content"
            )

            if not content_div:
                continue

            content = content_div.get_text(
                "\n",
                strip=True
            )

            summary = summarize_text(content)

            results.append({
                "사이트": "루리웹",
                "제목": title,
                "링크": link,
                "AI요약": summary
            })

            article_page.close()

        except:
            pass

    return results

# ======================
# Streamlit UI
# ======================

st.title("AI 게임 뉴스 요약 시스템")

st.write("""
인벤 / 루리웹 뉴스를 자동 수집하고
GPT가 핵심 내용을 요약합니다.
""")

if st.button("뉴스 수집 시작"):

    with st.spinner("뉴스 분석 중..."):

        all_results = []

        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True
            )

            page = browser.new_page()

            inven_results = crawl_inven(page)
            ruli_results = crawl_ruliweb(page)

            all_results.extend(inven_results)
            all_results.extend(ruli_results)

            browser.close()

        df = pd.DataFrame(all_results)

        st.success("완료!")

        st.dataframe(df)

        excel_file = "news_summary.xlsx"

        df.to_excel(
            excel_file,
            index=False
        )

        with open(excel_file, "rb") as f:

            st.download_button(
                label="엑셀 다운로드",
                data=f,
                file_name="news_summary.xlsx",
                mime="application/vnd.ms-excel"
            )
```

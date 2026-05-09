import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

client = OpenAI(
api_key=st.secrets["OPENAI_API_KEY"]
)

headers = {
"User-Agent": "Mozilla/5.0"
}

def summarize_text(text):

    try:

        response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": """

아래 뉴스 기사를 분석하라.

[中文摘要]
중국어로 핵심 3줄 요약 + 키워드 5개

[한국어 요약]
한국어로 핵심 3줄 요약 + 키워드 5개

중국어를 먼저 출력하라.
"""
},
{
"role": "user",
"content": text[:4000]
}
],
temperature=0.3
)

        return response.choices[0].message.content

    except Exception as e:
        return str(e)

def crawl_inven():

    results = []

url = "https://www.inven.co.kr/webzine/news/"

res = requests.get(url, headers=headers)

soup = BeautifulSoup(res.text, "lxml")

articles = soup.select("ul.news_list li")

for article in articles[:5]:

    try:

        title_tag = article.select_one(".tit")
        link_tag = article.select_one("a")

        if not title_tag:
            continue

        title = title_tag.text.strip()
        link = link_tag["href"]

        article_res = requests.get(link, headers=headers)

        article_soup = BeautifulSoup(
            article_res.text,
            "lxml"
        )

        content_div = article_soup.select_one(
            "#newsContent"
        )

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
            "링크": link,
            "AI요약": summary
        })

    except:
        pass

return results

def crawl_ruliweb():

    results = []

url = "https://bbs.ruliweb.com/news"

res = requests.get(url, headers=headers)

soup = BeautifulSoup(res.text, "lxml")

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

        article_res = requests.get(
            link,
            headers=headers
        )

        article_soup = BeautifulSoup(
            article_res.text,
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

    except:
        pass

return results

st.title("AI 게임 뉴스 요약 시스템")

st.write(
"인벤 / 루리웹 뉴스를 자동 수집하고 AI가 중국어 + 한국어로 요약합니다."
)

if st.button("뉴스 수집 시작"):

    with st.spinner("AI 분석 중..."):

    all_results = []

    all_results.extend(crawl_inven())
    all_results.extend(crawl_ruliweb())

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

import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime, timedelta

st.set_page_config(page_title="AI 韩国游戏新闻摘要系统", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"]  {
    font-family: Arial, sans-serif;
}
h1 {
    font-size: 42px !important;
}
</style>
""", unsafe_allow_html=True)

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
                    "content": "请用中文一句话总结这篇韩国游戏新闻，不超过40字。"
                },
                {
                    "role": "user",
                    "content": text[:3000]
                }
            ],
            temperature=0.3
        )

        return response.choices[0].message.content.strip()

    except Exception as e:

        return f"摘要失败: {str(e)}"

def crawl_inven():

    results = []

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    url = "https://www.inven.co.kr/webzine/news/"

    res = requests.get(url, headers=headers)

    soup = BeautifulSoup(res.text, "lxml")

    links = soup.select("a[href*='/webzine/news/?news=']")

    checked = set()

    for link_tag in links:

        try:

            link = link_tag.get("href")

            if not link:
                continue

            if link in checked:
                continue

            checked.add(link)

            title = link_tag.get_text(strip=True)

            if len(title) < 5:
                continue

            article_res = requests.get(link, headers=headers)

            article_soup = BeautifulSoup(article_res.text, "lxml")

            date_tag = article_soup.select_one(".articleDate")

            if date_tag:

                article_date = date_tag.get_text(strip=True)[:10]

                if article_date != yesterday:
                    continue

            content_div = article_soup.select_one("#newsContent")

            if not content_div:
                continue

            content = content_div.get_text("\n", strip=True)

            if len(content) < 100:
                continue

            summary = summarize_text(content)

            results.append({
                "网站": "INVEN",
                "新闻标题": title,
                "中文摘要": summary,
                "原文链接": link,
                "发布日期": yesterday
            })

        except:
            pass

    return results

st.title("AI 韩国游戏新闻摘要系统")

st.write("自动收集韩国 Inven 游戏新闻，并生成中文一句话摘要。")

if st.button("开始收集新闻"):

    with st.spinner("AI 正在分析新闻..."):

        all_results = crawl_inven()

        df = pd.DataFrame(all_results)

        if len(df) == 0:

            st.warning("未找到昨天的新闻。")

        else:

            st.success(f"成功收集 {len(df)} 条新闻")

            st.dataframe(df)

            excel_file = "inven_news_summary.xlsx"

            df.to_excel(excel_file, index=False)

            with open(excel_file, "rb") as f:

                st.download_button(
                    label="下载 Excel 文件",
                    data=f,
                    file_name="inven_news_summary.xlsx",
                    mime="application/vnd.ms-excel"
                )

from __future__ import annotations

import streamlit as st


navigation = st.navigation(
    [
        st.Page("pages/01_分析工作區.py", title="分析工作區"),
        st.Page("pages/02_報告中心.py", title="報告中心"),
        st.Page("pages/03_資料補強.py", title="資料補強"),
        st.Page("pages/04_系統設定.py", title="系統設定"),
    ]
)
navigation.run()

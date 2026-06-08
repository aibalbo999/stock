from __future__ import annotations

import json

from app.services.topic_discovery_models import DiscoveryPlanQuality, TopicDiscoveryPlan


def topic_discovery_prompt(topic: str) -> str:
    return f"""
你是台股產業研究助理。請針對主題「{topic}」自動拆解研究子題，並提出台股候選研究公司。

約束：
- 只能輸出 JSON，不要 Markdown，不要解釋，不要前後文。
- 回覆第一個字元必須是 {{，最後一個字元必須是 }}。
- subtopics 最多 8 筆；candidate_companies 最多 24 筆。
- rationale 每欄最多 25 個中文字；search query 每筆最多 30 個中文字。
- 子題應是一個可執行研究任務，不只是關鍵字。
- 每個子題需包含 objective、required_evidence、risk_focus，說明研究目的、需要查核的資料、需監控的風險。
- 每個子題需包含 source_intents，表示應抓取的資料類型，例如 industry_news、company_disclosure、financial_metrics、valuation、capacity_supply、material_supply、regulatory_policy、international_context、early_signal。
- 子題應能驅動資料抓取，例如 CoWoS、HBM、AI 伺服器、液冷、地緣政治、缺電等，但不要固定死在這些範例。
- 若主題是硬體、半導體、AI 伺服器、機器人或大型供應鏈，第一階段必須往更上游拆到材料端，不能只停在組裝、零組件或系統整合。
- 上游材料端至少要查核一個獨立子題；AI/半導體可包含矽晶圓、電子級化學品、特用氣體、光阻/CMP、CCL、銅箔、玻纖布、ABF/樹脂；機器人可包含稀土磁材、電磁鋼、軸承鋼/特殊鋼、工程塑膠、碳纖/複合材料、鎂鋁合金。
- source_intents 可包含 material_supply，用於標記上游材料、原料、特用化學品、磁材、鋼材或板材供給檢查。
- candidate_companies 是「候選研究清單」，不是正式投資推薦；要優先列出具備可驗證未來升值假設、但仍需用資料驗證或排除的公司。
- 除大型龍頭外，候選清單必須保留一部分「報導較少但訊號可能轉強」的中小型或供應鏈二線公司；這些公司仍需被後續來源、月營收、估值與風險資料驗證，不能只因冷門就升格。
- 每個候選公司都要有清楚產業鏈位置、升值假設與 evidence_keywords，讓後續報告能產出具體投資理由，而不是只列概念股。
- 若主題是大型產業鏈，候選清單應保持寬口徑；AI 產業鏈通常至少列出 15 檔可驗證台股候選，再交由後續證據升格。
- 公司必須是台股 4 碼 ticker。
- 不確定 ticker 時不要輸出該公司。
- search_queries 要適合 Google News RSS 搜尋；繁體中文為主，但每個子題至少 1 筆可用英文或中英混合詞查國際資料。
- search_queries 必須對應 objective、required_evidence 或 risk_focus，不可只是公司名或籠統題材詞。
- 拆解時至少涵蓋：需求/成長、供給/產能、財務/營收、估值/股價、風險/瓶頸；若主題不適用可合併但不可完全缺漏。
- 不可把「熱門股票」當作子題；必須先說明產業因果，再提出候選公司。

JSON schema:
{{
  "subtopics": [
    {{
      "name": "string",
      "rationale": "string",
      "objective": "string",
      "required_evidence": ["營收", "產能", "訂單"],
      "risk_focus": ["供給瓶頸", "價格下修"],
      "search_queries": ["string"],
      "source_intents": ["industry_news", "company_disclosure"]
    }}
  ],
  "candidate_companies": [
    {{
      "ticker": "2330",
      "name": "台積電",
      "segment": "晶圓代工",
      "rationale": "string",
      "evidence_keywords": ["CoWoS", "HBM"]
    }}
  ]
}}
"""


def topic_discovery_repair_prompt(
    topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality
) -> str:
    return f"""
你是台股產業研究總監。請修正主題「{topic}」的研究拆解 JSON，讓它成為可執行、可查證、可用於後續投資研究的任務清單。

目前品質狀態：
{json.dumps(quality.model_dump(), ensure_ascii=False)}

目前 JSON：
{json.dumps(plan.model_dump(), ensure_ascii=False)}

修正要求：
- 只能輸出 JSON，不要 Markdown，不要解釋，不要前後文。
- 回覆第一個字元必須是 {{，最後一個字元必須是 }}。
- 保留合理的原子題與候選公司，但必須補齊品質缺口。
- subtopics 最多 10 筆；candidate_companies 最多 24 筆。
- 每個子題都要有 objective、required_evidence、risk_focus、search_queries。
- 每個子題都要有 source_intents，讓系統知道應補哪類來源；可用值包含 industry_news、company_disclosure、financial_metrics、valuation、capacity_supply、material_supply、regulatory_policy、international_context、early_signal。
- 若主題是硬體、半導體、AI 伺服器、機器人或大型供應鏈，必須補齊上游材料端子題與候選公司，不可只列組裝、零組件、設備或系統整合。
- 上游材料端可用 source_intents=material_supply；AI/半導體材料需涵蓋矽晶圓、電子級化學品、特用氣體、光阻/CMP、CCL、銅箔、玻纖布、ABF/樹脂之一組以上；機器人材料需涵蓋稀土磁材、電磁鋼、軸承鋼/特殊鋼、工程塑膠、碳纖/複合材料、鎂鋁合金之一組以上。
- 子題必須是可執行研究任務，不能只是熱門股、概念股或單一關鍵字。
- search_queries 要能直接用於 Google News RSS，並兼顧台灣與國際資料；每個子題至少保留 1 筆英文或中英混合國際查詢。
- search_queries 必須能說明要驗證哪個投資假設，不可只是公司名、熱門股或籠統題材詞。
- 至少涵蓋品質缺口中提到的研究面向；若主題不適用，需用同一子題合併處理但不能空缺。
- candidate_companies 只是候選研究清單，不是投資推薦；請優先修正成「可驗證未來升值假設候選」，公司必須是台股 4 碼 ticker，不確定 ticker 不要輸出。
- 若原候選過度集中在市場已高度關注的龍頭，請補入可驗證的長尾供應鏈候選，例如二線設備、材料、電源、散熱、PCB、載板或零組件公司；仍需列 evidence_keywords 供後續驗證。
- 每個候選公司都要能說明產業鏈位置、可能升值假設與需驗證的 evidence_keywords，避免只輸出概念股名稱。
- evidence_keywords 必須能用來驗證公司與主題的真實關聯，不能只寫「AI」或「熱門」。

JSON schema:
{{
  "subtopics": [
    {{
      "name": "string",
      "rationale": "string",
      "objective": "string",
      "required_evidence": ["營收", "產能", "訂單"],
      "risk_focus": ["供給瓶頸", "價格下修"],
      "search_queries": ["string"],
      "source_intents": ["industry_news", "company_disclosure"]
    }}
  ],
  "candidate_companies": [
    {{
      "ticker": "2330",
      "name": "台積電",
      "segment": "晶圓代工",
      "rationale": "string",
      "evidence_keywords": ["CoWoS", "先進封裝"]
    }}
  ]
}}
"""

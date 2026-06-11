from __future__ import annotations

from html import escape


def workspace_topbar_html(today: str) -> str:
    return f"""
        <section class="workspace-topbar is-compact">
            <div>
                <div class="workspace-kicker">AI 台股投資工作台</div>
                <h1>AI 台股操作者控制台</h1>
                <div class="workspace-subtitle">
                    先看系統建議，再決定讀最新版報告、補資料或重跑分析。
                </div>
            </div>
            <div class="workspace-meta">
                <span class="workspace-chip">Asia/Taipei {escape(today)}</span>
                <span class="workspace-chip">資料不足自動降級</span>
                <span class="workspace-chip is-accent">缺口自動補強</span>
            </div>
        </section>
        """


def workspace_flow_html() -> str:
    return """
        <section class="workflow-strip is-compact" aria-label="分析流程">
            <div class="workflow-step"><span>01</span><strong>主題拆解</strong></div>
            <div class="workflow-step"><span>02</span><strong>來源驗證</strong></div>
            <div class="workflow-step"><span>03</span><strong>個股評估</strong></div>
            <div class="workflow-step"><span>04</span><strong>補強與重跑</strong></div>
        </section>
        <section class="workspace-ledger is-compact" aria-label="報告判讀基準">
            <div class="ledger-item"><span>品質門檻</span><strong>未過門檻先標示，不包裝成建議</strong></div>
            <div class="ledger-item"><span>資料來源</span><strong>新聞、市場、財務、公司文件分開查核</strong></div>
            <div class="ledger-item"><span>投資口徑</span><strong>正式分析不等於買進，分數只用於排序</strong></div>
        </section>
        """


def empty_analysis_result_html() -> str:
    return """
                <div class="result-shell">
                    <div class="section-title">等待分析結果</div>
                    <div class="section-note">
                        左側完成設定後執行分析。結果會在這裡以 HTML 卡片報告呈現，資料來源與完整文字會收在次要區塊。
                    </div>
                </div>
                """


def analysis_submission_summary_html(summary: dict[str, str]) -> str:
    return f"""<section class="analysis-submission-summary is-{escape(summary.get("state", "attention"))}" aria-label="分析送出前確認">
<span>送出前確認</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<small class="quota-pressure is-{escape(summary.get("quota_pressure_class", "medium"))}">{escape(summary.get("quota_pressure", ""))}｜{escape(summary.get("quota_advice", ""))}</small>
<em>{escape(summary.get("next_step", ""))}</em>
</section>"""


def operator_workbench_header_html(overall: dict[str, str]) -> str:
    return f"""<section class="operator-workbench" aria-label="今日狀態">
<div class="operator-workbench-head">
<div>
<div class="workspace-kicker">今日狀態</div>
<h2>{escape(overall["label"])}</h2>
<p>{escape(overall["detail"])}</p>
</div>
<span class="operator-state is-{escape(overall["state"])}">{escape(overall["state"])}</span>
</div>
</section>"""


def operator_status_grid_html(card_html: str) -> str:
    return f"""<section class="operator-status-grid" aria-label="狀態摘要">
{card_html}
</section>"""


def operator_action_controls_html(*, primary: bool = False) -> str:
    if primary:
        return (
            '<section class="operator-action-controls is-primary" '
            'aria-label="主要建議操作"></section>'
        )
    return """<section class="operator-action-controls" aria-label="建議操作">
<span>次要操作</span>
<strong>其他可開啟的處理頁面</strong>
</section>"""

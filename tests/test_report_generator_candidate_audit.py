from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist


def test_candidate_audit_report_keeps_excluded_company_reasons() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2382",
                "name": "廣達",
                "segment": "系統組裝",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_sources": [
                    {
                        "title": "廣達 AI 伺服器訂單",
                        "publisher": "測試新聞",
                        "published_at": "2026-05-24",
                        "url": "https://example.com/quanta",
                    }
                ],
                "evidence_confidence_score": 92,
                "evidence_confidence_label": "高",
                "latest_evidence_date": "2026-05-24",
                "status": "evidence_supported",
                "validation_reason": "通過正式分析門檻：至少 2 篇公司主題證據。",
                "next_action": "納入正式分析。",
            },
            {
                "ticker": "3324",
                "name": "雙鴻",
                "segment": "散熱模組",
                "rationale": "",
                "evidence_keywords": ["液冷"],
                "evidence_count": 1,
                "evidence_source_count": 1,
                "evidence_titles": [],
                "status": "weak_evidence",
                "validation_reason": "弱證據：目前只有 1 篇、1 個來源。",
                "next_action": "補抓公司新聞、法說會、月營收與國際供應鏈資料後再驗證。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["2382"])

    assert "| AI 初始候選 | 2 |" in markdown
    assert "| 正式分析 | 1 |" in markdown
    assert "3324 雙鴻" in markdown
    assert "弱證據觀察" in markdown
    assert "入選支持度只表示候選公司與主題的來源支持度" in markdown
    assert "分析可信度仍需另看風險/機會歸因" in markdown
    assert "| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 | 入選支持度 |" in markdown
    assert "補抓公司新聞" in markdown
    assert "候選公司代表來源" in markdown
    assert "廣達 AI 伺服器訂單" in markdown
    assert "測試新聞" in markdown
    assert "高 92，最新 2026-05-24" in markdown


def test_candidate_audit_fallback_uses_low_confidence_reason() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3324",
                "name": "雙鴻",
                "segment": "散熱模組",
                "rationale": "",
                "evidence_keywords": ["液冷"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_confidence_score": 60,
                "evidence_confidence_label": "中",
                "status": "weak_evidence",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "弱證據：篇數與來源數達標，但入選支持度只有 60 分" in markdown
    assert "補抓有日期、近期且不同發布者" in markdown
    assert "中 60" in markdown


def test_candidate_audit_marks_stale_candidate_sources() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3059",
                "name": "華晶科",
                "segment": "3D 感測相機",
                "rationale": "",
                "evidence_keywords": ["3D 感測"],
                "evidence_count": 4,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_confidence_score": 63,
                "evidence_confidence_label": "中",
                "latest_evidence_date": "2025-08-08",
                "status": "weak_evidence",
                "validation_reason": "弱證據：篇數與來源數達標。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "最新候選來源為 2025-08-08" in markdown
    assert "超過 180 天新鮮度門檻" in markdown
    assert "最新 2025-08-08（距今約" in markdown
    assert "超過 180 天）" in markdown
    assert "最近 180 天內官方公告" in markdown


def test_candidate_audit_representative_sources_are_newest_first() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "1815",
                "name": "富喬",
                "segment": "玻纖布",
                "evidence_keywords": ["AI"],
                "evidence_count": 4,
                "evidence_source_count": 3,
                "evidence_sources": [
                    {
                        "title": "股東會年報(股東會後修訂本)",
                        "publisher": "公開資訊觀測站 MOPS",
                        "published_at": "2025-08-26",
                        "url": "https://example.com/old1",
                    },
                    {
                        "title": "股東會年報(尚未適用永續揭露準則)",
                        "publisher": "公開資訊觀測站 MOPS",
                        "published_at": "2025-05-23",
                        "url": "https://example.com/old2",
                    },
                    {
                        "title": "玻纖布 AI 需求增",
                        "publisher": "UDN",
                        "published_at": "2026-03-25",
                        "url": "https://example.com/newer",
                    },
                ],
                "evidence_confidence_score": 92,
                "evidence_confidence_label": "高",
                "latest_evidence_date": "2026-03-25",
                "status": "evidence_supported",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["1815"])

    company_block = markdown[markdown.find("- 1815 富喬") :]
    assert company_block.find("玻纖布 AI 需求增") < company_block.find("股東會年報(股東會後修訂本)")
    assert "股東會年報(尚未適用永續揭露準則)" not in company_block[:300]


def test_candidate_audit_dedupes_repeated_revalidation_reason() -> None:
    repeated_reason = (
        "上一版通過正式分析門檻；"
        "本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析；"
        "本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析"
    )
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "segment": "PCB",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器"],
                "evidence_count": 13,
                "evidence_source_count": 9,
                "evidence_titles": [],
                "status": "evidence_supported",
                "validation_reason": repeated_reason,
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["3037"])

    assert markdown.count("本次補強重驗證未穩定重建既有正式證據") == 1


def test_candidate_audit_filters_unrelated_release_note_sources() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "5443",
                "name": "均豪",
                "segment": "半導體自動化",
                "rationale": "機械手臂與自動化設備",
                "evidence_keywords": ["自動化", "機械手臂"],
                "evidence_count": 1,
                "evidence_source_count": 1,
                "evidence_titles": ["May 21, 2026"],
                "evidence_sources": [
                    {
                        "title": "May 21, 2026",
                        "publisher": "Google Cloud Release Notes",
                        "published_at": "2026-05-21",
                        "url": "https://cloud.google.com/release-notes",
                    }
                ],
                "status": "weak_evidence",
                "validation_reason": "弱證據：目前只有 1 篇、1 個來源。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "Google Cloud Release Notes" not in markdown
    assert "| 5443 均豪 | 半導體自動化 | 弱證據觀察 | 0 篇 / 0 來源 |" in markdown

"""Composable, read-only AI workflow tools backed by the existing runtime services."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def get_ai_workflow_tool_specs() -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []

    async def h_summarize_text(text: str, style: str = "bullets", max_points: int = 7, **_: Any) -> Dict[str, Any]:
        text = str(text).strip()
        if not text or len(text) > 12000:
            return {"error": "摘要文字需為 1–12000 字元。"}
        count = max(3, min(int(max_points), 12))
        style = style if style in {"bullets", "executive", "action_items"} else "bullets"
        add_instruction = {
            "bullets": f"用繁體中文整理為最多 {count} 點重點，保留關鍵事實與數字。",
            "executive": f"用繁體中文撰寫簡潔主管摘要，包含背景、核心發現及結論，最多 {count} 個要點。",
            "action_items": f"只根據原文整理待辦、負責事項（若有明示）與期限（若有明示），最多 {count} 項；不要推測。",
        }[style]
        return {"task": "摘要", "format": style, "instruction": add_instruction, "source_text": text, "source_chars": len(text)}

    async def h_compare_texts(text_a: str, text_b: str, focus: str = "差異", **_: Any) -> Dict[str, Any]:
        a, b = str(text_a).strip(), str(text_b).strip()
        if not a or not b or len(a) > 8000 or len(b) > 8000:
            return {"error": "兩段比較文字都必須為 1–8000 字元。"}
        return {"task": "比較", "focus": str(focus)[:120], "instructions": "只根據資料區分共同點、差異與可能影響；標示未知，不虛構。", "text_a": a, "text_b": b}

    async def h_rewrite_text(text: str, goal: str = "更清楚自然", audience: str = "一般讀者", **_: Any) -> Dict[str, Any]:
        text = str(text).strip()
        if not text or len(text) > 8000:
            return {"error": "待改寫文字需為 1–8000 字元。"}
        return {"task": "改寫", "goal": str(goal)[:120], "audience": str(audience)[:120], "instructions": "保留原意和事實，不新增承諾或資訊。", "source_text": text}

    async def h_extract_structured_facts(text: str, fields: str = "名稱,日期,數值,結論", **_: Any) -> Dict[str, Any]:
        text = str(text).strip()
        if not text or len(text) > 10000:
            return {"error": "來源文字需為 1–10000 字元。"}
        wanted = [f.strip()[:80] for f in str(fields).split(",")[:20] if f.strip()]
        return {"task": "結構化抽取", "fields": wanted, "output_format": "json object; absent values null", "source_text": text}

    async def h_generate_ideas(topic: str, count: int = 8, constraints: str = "", **_: Any) -> Dict[str, Any]:
        topic = str(topic).strip()
        if not topic or len(topic) > 1000:
            return {"error": "主題需為 1–1000 字元。"}
        count = max(3, min(int(count), 15))
        return {"task": "創意發想", "topic": topic, "count": count, "constraints": str(constraints)[:1000], "instructions": "產生不重複且可執行構想，簡述價值與第一步。"}

    async def _simple_ai(system: str, text: str, limit: int = 9000, **kwargs: Any) -> Dict[str, Any]:
        value = str(text).strip()
        if not value or len(value) > limit:
            return {"error": f"輸入需為 1–{limit} 字元。"}
        return {"task": "文字處理", "instructions": system, "source_text": value}

    async def h_classify_sentiment(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("分析文字情緒。回傳 JSON label(正向/中性/負向/混合)、confidence(0-1)、evidence(最多3個原文片語)。不要推斷作者身份。", text, **kwargs)

    async def h_extract_keywords(text: str, count: int = 12, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"抽取繁體中文重要關鍵詞，輸出 JSON array，最多 {max(1,min(int(count),30))} 個，避免泛詞。", text, **kwargs)

    async def h_generate_titles(text: str, style: str = "清楚精煉", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"為內容產生五個符合「{str(style)[:60]}」風格的繁體中文標題，不誇大。", text, **kwargs)

    async def h_translate_text(text: str, target_language: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"精準翻譯為{str(target_language)[:60]}，保留格式和原意，只輸出譯文。", text, **kwargs)

    async def h_proofread(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("校對繁體中文語法、錯字、標點，保留原意；提供修訂稿及簡短修改摘要，不增加事實。", text, **kwargs)

    async def h_simplify(text: str, audience: str = "一般讀者", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"把內容改寫成{str(audience)[:60]}容易理解的說明，保留數字、事實及限制。", text, **kwargs)

    async def h_expand_outline(text: str, depth: int = 3, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"整理成最多 {max(1,min(int(depth),4))} 層的繁體中文大綱，缺失資訊標示待補。", text, **kwargs)

    async def h_create_faq(text: str, count: int = 8, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"依來源建立最多 {max(1,min(int(count),20))} 組 FAQ。答案不可超出來源，未知處標示未說明。", text, limit=12000, **kwargs)

    async def h_action_items(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("只抽取明確承諾的待辦，回傳 JSON array: task, owner(無資料null), due(無資料null), quote。不得推測。", text, limit=12000, **kwargs)

    async def h_pros_cons(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("平衡分析方案的優點、缺點、風險、未知資訊及可驗證假設，不虛構數據。", text, **kwargs)

    async def h_explain_code(text: str, language: str = "auto", level: str = "初學者", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"解釋{str(language)[:40]}程式碼，讀者程度{str(level)[:40]}。說明流程、輸入輸出與疑似邊界；不要聲稱已執行。", text, **kwargs)

    async def h_review_code(text: str, focus: str = "正確性、安全、效能", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"審查程式碼，聚焦{str(focus)[:100]}。列出可定位問題、嚴重度、原因與修法，並標明假設；勿聲稱跑過程式。", text, **kwargs)

    async def h_generate_tests(text: str, framework: str = "pytest", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"為程式或需求設計{str(framework)[:50]}測試，涵蓋成功、邊界與失敗路徑，說明假設。", text, **kwargs)

    async def h_generate_regex(description: str, examples: str = "", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("設計 Python regex，輸出 pattern、說明、正例及反例；歧義先指出。", f"需求：{description}\n範例：{examples}", limit=5000, **kwargs)

    async def h_generate_schema(description: str, example: str = "", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("產生 Draft 2020-12 JSON Schema。只輸出有效 JSON；不確定欄位設為 optional。", f"需求：{description}\n範例：{example}", limit=6000, **kwargs)

    async def h_compare_options(options: str, criteria: str = "成本、風險、維護性", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"依據「{str(criteria)[:150]}」比較選項，列出理由與未知資訊；不虛構精確分數。", options, **kwargs)

    async def h_detect_pii(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("檢查可能個資類型，JSON items 含 type、masked_example、confidence。遮蔽號碼與地址；這不是法律判定。", text, **kwargs)

    async def h_draft_email(text: str, tone: str = "專業友善", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"依草稿或要點撰寫{str(tone)[:60]}繁體中文郵件。不捏造日期或承諾，缺資料用[待補]。", text, **kwargs)

    async def h_create_checklist(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("將工作描述拆解為有順序、可勾選的 checklist。不要添加未授權的外部操作。", text, **kwargs)

    async def h_dedupe_items(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("找出語意重複項目並分組，列代表項與合併理由；只提出建議，不刪除資料。", text, limit=10000, **kwargs)

    async def h_fake_test_data(description: str, count: int = 10, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"產生 {max(1,min(int(count),30))} 筆完全虛構的測試資料，輸出 JSON array，避免真實個資。", description, limit=6000, **kwargs)

    async def h_classify_labels(text: str, labels: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"從指定標籤分類，輸出 JSON labels、confidence、evidence；無法分類則 labels 為空。標籤：{str(labels)[:1000]}", text, **kwargs)

    async def h_redact_text(text: str, kinds: str = "email,phone,token", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"遮蔽文字中明顯的敏感資料類型({str(kinds)[:100]})，保留其餘內容；輸出修訂文字及遮蔽項類別，不展示原始敏感值。", text, **kwargs)

    async def h_make_flashcards(text: str, count: int = 10, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"依來源製作最多 {max(1,min(int(count),30))} 組學習卡片 JSON array [{'{'}question,answer{'}'}]，答案限來源內容。", text, limit=12000, **kwargs)

    async def h_quiz_from_text(text: str, count: int = 5, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"依來源製作 {max(1,min(int(count),15))} 題選擇題，JSON 含 question, choices, answer, explanation；不要加入來源外知識。", text, limit=12000, **kwargs)

    async def h_meeting_minutes(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("把紀錄整理為會議紀要：目的、討論、決議、待辦、未決問題。沒出現的資訊標示未提及。", text, limit=12000, **kwargs)

    async def h_risk_review(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("根據提供資料識別風險、可能性/影響的定性等級、緩解方法及證據缺口。不要宣稱專業認證結論。", text, **kwargs)

    async def h_create_user_story(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("將需求整理為 user stories 及可驗收 acceptance criteria。模糊或缺少條件需列出澄清問題。", text, **kwargs)

    async def h_api_doc(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("根據輸入產生 API 文件草稿：用途、參數、回應、錯誤及範例。未知欄位明確標示，不猜測。", text, **kwargs)

    async def h_prompt_review(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("檢視提示詞的目標清晰度、矛盾、注入風險、輸出格式及缺漏，提供改良稿和理由。", text, **kwargs)

    async def h_dialogue_roleplay(text: str, persona: str = "面試官", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"以{str(persona)[:60]}角色進行安全的文字演練，保持在虛構情境，不聲稱是真實人物或採取外部行動。", text, **kwargs)

    async def h_readability_review(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("評估文字可讀性，指出冗長句、術語、結構障礙與具體簡化建議；不捏造量化分數。", text, **kwargs)

    async def h_claim_evidence_map(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("把文字中的主要主張與其提供的證據配對，標出無證據、推論或互相矛盾處。只評估給定文字。", text, **kwargs)

    async def h_tone_transform(text: str, tone: str = "正式", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"將文字改成{str(tone)[:50]}語氣，保留事實與立場，只輸出改寫稿。", text, **kwargs)

    async def h_outline_to_article(text: str, audience: str = "一般讀者", **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai(f"依大綱撰寫面向{str(audience)[:50]}的文章。不得擴寫出大綱沒有支持的具體事實，缺口用提示標出。", text, limit=10000, **kwargs)

    async def h_article_to_outline(text: str, **kwargs: Any) -> Dict[str, Any]:
        return await _simple_ai("把文章轉成階層式大綱，保留論點和證據層次。", text, limit=12000, **kwargs)

    async def h_readability_metrics(text: str, **_: Any) -> Dict[str, Any]:
        import re
        value = str(text)
        sentences = [s for s in re.split(r"[。！？!?\n]+", value) if s.strip()]
        words = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", value)
        return {"characters": len(value), "sentences": len(sentences), "token_like_units": len(words), "average_sentence_chars": round(sum(map(len, sentences)) / max(1, len(sentences)), 2), "long_sentences": [s[:300] for s in sentences if len(s) > 80][:20]}

    async def h_compare_json_objects(json_a: str, json_b: str, **_: Any) -> Dict[str, Any]:
        import json
        try:
            a, b = json.loads(json_a), json.loads(json_b)
        except Exception as exc:
            return {"error": f"JSON 解析失敗：{type(exc).__name__}"}
        diffs = []
        def walk(left: Any, right: Any, path: str = "$") -> None:
            if type(left) is not type(right):
                diffs.append({"path": path, "a": left, "b": right})
            elif isinstance(left, dict):
                for k in sorted(set(left) | set(right)):
                    if k not in left or k not in right:
                        diffs.append({"path": f"{path}.{k}", "a": left.get(k, "<missing>"), "b": right.get(k, "<missing>")})
                    else:
                        walk(left[k], right[k], f"{path}.{k}")
            elif isinstance(left, list):
                if left != right:
                    diffs.append({"path": path, "a_length": len(left), "b_length": len(right), "values_differ": True})
            elif left != right:
                diffs.append({"path": path, "a": left, "b": right})
        walk(a, b)
        return {"equal": not diffs, "difference_count": len(diffs), "differences": diffs[:200]}

    async def h_validate_csv_text(text: str, delimiter: str = ",", **_: Any) -> Dict[str, Any]:
        import csv
        import io
        if len(text) > 50000:
            return {"error": "CSV 最多 50000 字元。"}
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=(delimiter or ",")[:1]))
        except Exception as exc:
            return {"valid": False, "error": type(exc).__name__}
        widths = [len(row) for row in rows]
        expected = widths[0] if widths else 0
        return {"valid": bool(rows) and all(w == expected for w in widths), "rows": len(rows), "columns": expected, "inconsistent_rows": [i + 1 for i, w in enumerate(widths) if w != expected][:100], "preview": rows[:5]}

    async def h_validate_xml_text(text: str, **_: Any) -> Dict[str, Any]:
        import xml.etree.ElementTree as ET
        if len(text) > 50000:
            return {"valid": False, "error": "XML 最多 50000 字元。"}
        try:
            root = ET.fromstring(text)
            return {"valid": True, "root_tag": root.tag, "children": len(list(root)), "attributes": dict(list(root.attrib.items())[:30])}
        except ET.ParseError as exc:
            return {"valid": False, "error": str(exc)[:500], "line": getattr(exc, "position", (None, None))[0]}

    async def h_validate_yaml_text(text: str, **_: Any) -> Dict[str, Any]:
        try:
            import yaml
        except ImportError:
            return {"error": "目前環境沒有 PyYAML，無法安全解析 YAML。"}
        if len(text) > 50000:
            return {"valid": False, "error": "YAML 最多 50000 字元。"}
        try:
            parsed = yaml.safe_load(text)
            return {"valid": True, "root_type": type(parsed).__name__, "top_level_keys": list(parsed)[:100] if isinstance(parsed, dict) else None}
        except Exception as exc:
            return {"valid": False, "error": str(exc)[:500]}

    async def h_parse_markdown_headings(text: str, **_: Any) -> Dict[str, Any]:
        import re
        headings = [{"level": len(m.group(1)), "text": m.group(2).strip()} for line in text.splitlines() if (m := re.match(r"^(#{1,6})\s+(.+)$", line.strip()))]
        return {"heading_count": len(headings), "headings": headings[:200]}

    async def h_extract_urls(text: str, **_: Any) -> Dict[str, Any]:
        import re
        urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>\]\)]+", text)))
        return {"count": len(urls), "urls": urls[:100]}

    async def h_extract_emails(text: str, **_: Any) -> Dict[str, Any]:
        import re
        items = list(dict.fromkeys(re.findall(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?!\w)", text)))
        return {"count": len(items), "emails": [v[:2] + "***@" + v.split("@", 1)[1] for v in items[:50]]}

    async def h_extract_phone_like(text: str, **_: Any) -> Dict[str, Any]:
        import re
        vals = list(dict.fromkeys(re.findall(r"(?<!\d)(?:\+?\d[\d\s().-]{6,}\d)(?!\d)", text)))
        return {"count": len(vals), "masked_candidates": ["***" + re.sub(r"\D", "", v)[-3:] for v in vals[:50]]}

    async def h_extract_dates(text: str, **_: Any) -> Dict[str, Any]:
        import re
        patterns = [r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b", r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b", r"\d{1,2}月\d{1,2}日"]
        dates = list(dict.fromkeys(item for pattern in patterns for item in re.findall(pattern, text)))
        return {"dates": dates[:100], "count": len(dates), "note": "僅抽取格式候選，需依上下文確認含義。"}

    async def h_extract_numbers(text: str, **_: Any) -> Dict[str, Any]:
        import re
        nums = list(dict.fromkeys(re.findall(r"(?<![\w])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?(?![\w])", text)))
        return {"numbers": nums[:200], "count": len(nums)}

    async def h_extract_citations(text: str, **_: Any) -> Dict[str, Any]:
        import re
        patterns = r"\[[0-9]{1,3}\]|\([A-Z][A-Za-z]+(?: et al\.)?,?\s*\d{4}\)|https?://[^\s<>]+|doi:\s*\S+"
        refs = list(dict.fromkeys(re.findall(patterns, text, flags=re.I)))
        return {"citations": refs[:100], "count": len(refs)}

    async def h_detect_language_hint(text: str, **_: Any) -> Dict[str, Any]:
        import re
        sample = text[:5000]
        cjk = len(re.findall(r"[\u4e00-\u9fff]", sample))
        kana = len(re.findall(r"[\u3040-\u30ff]", sample))
        hangul = len(re.findall(r"[\uac00-\ud7af]", sample))
        latin = len(re.findall(r"[A-Za-z]", sample))
        counts = {"chinese_han": cjk, "japanese_kana": kana, "korean_hangul": hangul, "latin": latin}
        likely = max(counts, key=counts.get) if any(counts.values()) else "unknown"
        return {"likely_script": likely, "script_counts": counts, "confidence": "heuristic; short or mixed text may be ambiguous"}

    async def h_split_text_chunks(text: str, chunk_chars: int = 2000, overlap: int = 100, **_: Any) -> Dict[str, Any]:
        size = max(200, min(int(chunk_chars), 8000))
        overlap = max(0, min(int(overlap), min(500, size // 4)))
        chunks = []
        start = 0
        while start < len(text) and len(chunks) < 100:
            end = min(start + size, len(text))
            if end < len(text):
                cut = max(text.rfind("\n", start, end), text.rfind("。", start, end), text.rfind(" ", start, end))
                if cut > start + size // 2:
                    end = cut + 1
            chunks.append({"index": len(chunks) + 1, "start": start, "end": end, "text": text[start:end]})
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
        return {"count": len(chunks), "chunks": chunks, "truncated": len(text) > (chunks[-1]["end"] if chunks else 0)}

    async def h_count_text_patterns(text: str, patterns: str, **_: Any) -> Dict[str, Any]:
        import re
        try:
            regs = [re.compile(p[:200], re.I) for p in str(patterns).splitlines()[:20] if p.strip()]
        except re.error as exc:
            return {"error": f"正規式無效：{exc}"}
        return {"matches": [{"pattern": r.pattern, "count": sum(1 for _ in r.finditer(text[:50000]))} for r in regs]}

    async def h_make_json_key_path(text: str, key: str, **_: Any) -> Dict[str, Any]:
        import json
        try:
            obj = json.loads(text)
        except Exception as exc:
            return {"error": f"JSON 解析失敗：{type(exc).__name__}"}
        value = obj
        traversed = []
        for part in str(key).split(".")[:20]:
            traversed.append(part)
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                return {"found": False, "path": traversed}
        return {"found": True, "path": traversed, "value": value}

    async def h_validate_semver(value: str, **_: Any) -> Dict[str, Any]:
        import re
        match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?", str(value).strip())
        return {"valid_semver": bool(match), "version": str(value).strip(), "major": int(match.group(1)) if match else None, "minor": int(match.group(2)) if match else None, "patch": int(match.group(3)) if match else None}

    async def h_validate_utc_offset(value: str, **_: Any) -> Dict[str, Any]:
        import re
        match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", str(value).strip())
        valid = bool(match and int(match.group(2)) <= 14 and int(match.group(3)) < 60 and (int(match.group(2)) < 14 or int(match.group(3)) == 0))
        return {"valid": valid, "offset": value, "total_minutes": ((1 if match.group(1) == "+" else -1) * (int(match.group(2)) * 60 + int(match.group(3)))) if valid else None}

    async def h_validate_ipv4(value: str, **_: Any) -> Dict[str, Any]:
        import ipaddress
        try:
            ip = ipaddress.IPv4Address(str(value).strip())
            return {"valid": True, "canonical": str(ip), "is_private": ip.is_private, "is_global": ip.is_global, "is_loopback": ip.is_loopback}
        except Exception:
            return {"valid": False, "input": str(value)[:100]}

    async def h_validate_ipv6(value: str, **_: Any) -> Dict[str, Any]:
        import ipaddress
        try:
            ip = ipaddress.IPv6Address(str(value).strip())
            return {"valid": True, "canonical": str(ip), "is_private": ip.is_private, "is_global": ip.is_global, "is_loopback": ip.is_loopback}
        except Exception:
            return {"valid": False, "input": str(value)[:100]}

    async def h_countdown_between_dates(start_date: str, end_date: str, **_: Any) -> Dict[str, Any]:
        from datetime import date
        try:
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        except ValueError:
            return {"error": "日期請用 YYYY-MM-DD 格式。"}
        delta = (end - start).days
        return {"start": start.isoformat(), "end": end.isoformat(), "days": abs(delta), "direction": "forward" if delta >= 0 else "backward", "weeks": abs(delta) // 7, "remaining_days": abs(delta) % 7}

    async def h_normalize_whitespace(text: str, **_: Any) -> Dict[str, Any]:
        import re
        normalized = re.sub(r"[ \t]+", " ", str(text))
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        return {"text": normalized[:20000], "before_chars": len(str(text)), "after_chars": len(normalized)}

    async def h_escape_markdown(text: str, **_: Any) -> Dict[str, Any]:
        import re
        return {"escaped": re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", str(text)[:10000])}

    async def h_html_entities(text: str, mode: str = "escape", **_: Any) -> Dict[str, Any]:
        import html
        val = str(text)[:10000]
        return {"text": html.escape(val) if mode == "escape" else html.unescape(val), "mode": mode if mode in {"escape", "unescape"} else "escape"}

    async def h_base64_size(text: str, **_: Any) -> Dict[str, Any]:
        import base64
        raw = str(text).encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        return {"input_bytes": len(raw), "encoded_chars": len(encoded), "estimated_expansion_percent": round((len(encoded) / max(1, len(raw)) - 1) * 100, 2)}

    async def h_hash_text(text: str, algorithm: str = "sha256", **_: Any) -> Dict[str, Any]:
        import hashlib
        name = str(algorithm).lower()
        if name not in {"sha256", "sha512", "sha1", "md5"}:
            return {"error": "僅支援 sha256、sha512、sha1、md5。"}
        digest = hashlib.new(name, str(text).encode("utf-8")).hexdigest()
        return {"algorithm": name, "digest": digest, "note": "雜湊不能還原原文；MD5/SHA1 不適用於安全用途。"}

    async def h_parse_url(text: str, **_: Any) -> Dict[str, Any]:
        from urllib.parse import urlsplit, parse_qsl
        parsed = urlsplit(str(text).strip())
        return {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port, "path": parsed.path, "query_pairs": parse_qsl(parsed.query)[:50], "fragment": parsed.fragment[:300], "requires_external_safety_check": True}

    async def h_csv_preview(text: str, rows: int = 10, **_: Any) -> Dict[str, Any]:
        import csv, io
        if len(text) > 50000:
            return {"error": "CSV 預覽最多 50000 字元。"}
        data = list(csv.reader(io.StringIO(text)))
        return {"rows": len(data), "columns": len(data[0]) if data else 0, "preview": data[:max(1,min(int(rows),30))]}

    async def h_transpose_table(text: str, **_: Any) -> Dict[str, Any]:
        import csv, io
        rows = list(csv.reader(io.StringIO(text[:30000])))
        if not rows:
            return {"error": "沒有可轉置的資料。"}
        width = max(map(len, rows))
        padded = [row + [""] * (width - len(row)) for row in rows]
        return {"table": list(map(list, zip(*padded))), "rows": width, "columns": len(rows)}

    async def h_split_sentences(text: str, **_: Any) -> Dict[str, Any]:
        import re
        sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])\s*|\n+", str(text)) if s.strip()]
        return {"count": len(sentences), "sentences": sentences[:300]}

    async def h_validate_email_shape(value: str, **_: Any) -> Dict[str, Any]:
        import re
        value = str(value).strip()
        ok = len(value) <= 254 and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value) is not None
        return {"syntactically_plausible": bool(ok), "note": "格式檢查不代表信箱存在或可收信。"}

    async def h_validate_json_pointer(text: str, pointer: str, **_: Any) -> Dict[str, Any]:
        import json
        try:
            value = json.loads(text)
        except Exception as exc:
            return {"error": f"JSON 解析失敗：{type(exc).__name__}"}
        if pointer in ("", "/"):
            return {"found": True, "value": value}
        current = value
        path = [p.replace("~1", "/").replace("~0", "~") for p in pointer.strip("/").split("/")][:40]
        for part in path:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return {"found": False, "pointer": pointer}
        return {"found": True, "pointer": pointer, "value": current}

    def add(name: str, description: str, properties: Dict[str, Any], required: List[str], handler: Any, category: str = "AI 工作流") -> None:
        specs.append({
            "name": name,
            "category": category,
            "description": description,
            "parameters_desc": ", ".join(properties),
            "parameters_schema": {"type": "object", "properties": properties, "required": required},
            "handler": handler,
            "trigger_keywords": [word for word in name.replace("_", " ").split() if len(word) > 2],
            "read_only": True,
        })

    str_prop = lambda desc: {"type": "string", "description": desc}
    add("ai_summarize_text", "將使用者提供的文章、貼文或筆記整理成重點；不讀取其他伺服器資料", {"text": str_prop("待摘要文字，最多 12000 字元"), "style": {"type": "string", "enum": ["bullets", "executive", "action_items"]}, "max_points": {"type": "integer", "minimum": 3, "maximum": 12}}, ["text"], h_summarize_text)
    add("ai_compare_texts", "比較兩段使用者提供的文字，列共同點、差異與影響", {"text_a": str_prop("第一段文字"), "text_b": str_prop("第二段文字"), "focus": str_prop("比較焦點")}, ["text_a", "text_b"], h_compare_texts)
    add("ai_rewrite_text", "依目標和受眾改寫使用者提供的文字，保留原意，不新增事實", {"text": str_prop("待改寫文字"), "goal": str_prop("改寫目標"), "audience": str_prop("目標讀者")}, ["text"], h_rewrite_text)
    add("ai_extract_structured_facts", "從使用者提供文字抽取指定欄位為 JSON，未提及欄位回傳 null", {"text": str_prop("來源文字"), "fields": str_prop("逗號分隔欄位名稱")}, ["text"], h_extract_structured_facts)
    add("ai_generate_ideas", "依主題和限制產生不同且可執行的創意方案", {"topic": str_prop("構想主題"), "count": {"type": "integer", "minimum": 3, "maximum": 15}, "constraints": str_prop("限制條件")}, ["topic"], h_generate_ideas)
    s = str_prop
    i = lambda d, hi=30: {"type": "integer", "minimum": 1, "maximum": hi, "description": d}
    add("ai_classify_sentiment", "辨識使用者文字情緒及原文證據", {"text": s("文字")}, ["text"], h_classify_sentiment)
    add("ai_extract_keywords", "抽取文件關鍵詞", {"text": s("文字"), "count": i("關鍵詞數")}, ["text"], h_extract_keywords)
    add("ai_generate_titles", "為內容產生標題選項", {"text": s("內容"), "style": s("風格")}, ["text"], h_generate_titles)
    add("ai_translate_text", "將文字翻譯成指定語言", {"text": s("原文"), "target_language": s("目標語言")}, ["text", "target_language"], h_translate_text)
    add("ai_proofread_text", "校對文字錯字語法並保留原意", {"text": s("文字")}, ["text"], h_proofread)
    add("ai_simplify_explanation", "將文字改寫得適合指定讀者理解", {"text": s("內容"), "audience": s("讀者")}, ["text"], h_simplify)
    add("ai_expand_outline", "生成層級式內容大綱", {"text": s("主題"), "depth": i("層級", 4)}, ["text"], h_expand_outline)
    add("ai_create_faq", "根據來源建立有根據的 FAQ", {"text": s("來源"), "count": i("問題數", 20)}, ["text"], h_create_faq)
    add("ai_extract_action_items", "從會議記錄抽取明確待辦", {"text": s("記錄")}, ["text"], h_action_items)
    add("ai_analyze_pros_cons", "分析方案優缺點及未知風險", {"text": s("方案")}, ["text"], h_pros_cons)
    add("ai_explain_code", "以指定程度說明程式碼，不執行程式", {"text": s("程式碼"), "language": s("語言"), "level": s("程度")}, ["text"], h_explain_code, "AI 開發工具")
    add("ai_review_code", "審查程式碼正確性安全與效能，不宣稱執行", {"text": s("程式碼"), "focus": s("重點")}, ["text"], h_review_code, "AI 開發工具")
    add("ai_generate_tests", "設計成功邊界失敗測試案例", {"text": s("程式或需求"), "framework": s("框架")}, ["text"], h_generate_tests, "AI 開發工具")
    add("ai_generate_regex", "依需求產生含正反例的 regex", {"description": s("需求"), "examples": s("範例")}, ["description"], h_generate_regex, "AI 開發工具")
    add("ai_generate_json_schema", "產生 JSON Schema 草稿", {"description": s("需求"), "example": s("範例 JSON")}, ["description"], h_generate_schema, "AI 開發工具")
    add("ai_compare_options", "依準則比較多個選項", {"options": s("選項"), "criteria": s("準則")}, ["options"], h_compare_options)
    add("ai_detect_pii", "以遮蔽方式標示疑似個資類型", {"text": s("文字")}, ["text"], h_detect_pii, "AI 隱私工具")
    add("ai_draft_email", "依要點草擬不捏造資料的郵件", {"text": s("要點"), "tone": s("語氣")}, ["text"], h_draft_email)
    add("ai_create_checklist", "把描述拆解為可勾選步驟", {"text": s("工作描述")}, ["text"], h_create_checklist)
    add("ai_semantic_deduplicate", "找出相似重複項目但不修改資料", {"text": s("項目清單")}, ["text"], h_dedupe_items)
    add("ai_generate_synthetic_test_data", "產生虛構且不含真實個資的測試資料", {"description": s("資料欄位"), "count": i("數量")}, ["description"], h_fake_test_data, "AI 開發工具")
    add("ai_classify_into_labels", "根據提供標籤分類文字並附證據", {"text": s("內容"), "labels": s("標籤")}, ["text", "labels"], h_classify_labels)
    add("ai_redact_sensitive_text", "遮蔽文字中明顯的敏感資料", {"text": s("文字"), "kinds": s("資料類別")}, ["text"], h_redact_text, "AI 隱私工具")
    add("ai_make_flashcards", "依來源製作有根據的學習卡片", {"text": s("來源"), "count": i("數量")}, ["text"], h_make_flashcards)
    add("ai_generate_quiz", "依來源製作題目答案與解析", {"text": s("來源"), "count": i("數量", 15)}, ["text"], h_quiz_from_text)
    add("ai_format_meeting_minutes", "整理會議目的討論決議及待辦", {"text": s("會議記錄")}, ["text"], h_meeting_minutes)
    add("ai_review_risks", "從提供內容盤點風險與緩解方式", {"text": s("內容或計畫")}, ["text"], h_risk_review)
    add("ai_create_user_stories", "把需求轉為 user stories 與驗收條件", {"text": s("需求")}, ["text"], h_create_user_story, "AI 開發工具")
    add("ai_draft_api_docs", "依輸入建立不虛構資料的 API 文件草稿", {"text": s("程式或 API 摘要")}, ["text"], h_api_doc, "AI 開發工具")
    add("ai_review_prompt", "檢視提示詞矛盾、注入風險與輸出格式", {"text": s("提示詞")}, ["text"], h_prompt_review, "AI 開發工具")
    add("ai_roleplay_text_scenario", "進行文字型角色演練，不連接外部或冒充真實人物", {"text": s("情境或台詞"), "persona": s("角色類型")}, ["text"], h_dialogue_roleplay)
    add("ai_review_readability", "找出內容可讀性障礙並提出修改建議", {"text": s("內容")}, ["text"], h_readability_review)
    add("ai_map_claims_to_evidence", "將主張對應來源證據並標記證據缺口", {"text": s("文件或論證")}, ["text"], h_claim_evidence_map)
    add("ai_transform_tone", "改變文字語氣但保留立場與事實", {"text": s("文字"), "tone": s("目標語氣")}, ["text"], h_tone_transform)
    add("ai_outline_to_article", "根據大綱撰寫文章並標示資料缺口", {"text": s("大綱"), "audience": s("讀者")}, ["text"], h_outline_to_article)
    add("ai_article_to_outline", "將文章整理為階層式大綱", {"text": s("文章")}, ["text"], h_article_to_outline)
    add("text_readability_metrics", "計算句數、字元與長句，提供可讀性客觀指標", {"text": s("文字")}, ["text"], h_readability_metrics, "文本處理")
    add("json_structural_diff", "逐路徑比較兩個 JSON 結構並列出差異", {"json_a": s("JSON A"), "json_b": s("JSON B")}, ["json_a", "json_b"], h_compare_json_objects, "編碼與資料")
    add("csv_validate_preview", "驗證 CSV 欄寬並回傳有限列預覽", {"text": s("CSV 文字"), "delimiter": s("分隔符")}, ["text"], h_validate_csv_text, "編碼與資料")
    add("xml_safe_validate", "以標準 XML parser 驗證輸入並回傳根元素資訊", {"text": s("XML 文字")}, ["text"], h_validate_xml_text, "編碼與資料")
    add("yaml_safe_validate", "使用 safe_load 驗證 YAML，不建構任意物件", {"text": s("YAML 文字")}, ["text"], h_validate_yaml_text, "編碼與資料")
    add("markdown_extract_headings", "擷取 Markdown 標題與階層結構", {"text": s("Markdown 文字")}, ["text"], h_parse_markdown_headings, "文本處理")
    add("text_extract_urls", "抽取文字中的 HTTP(S) URL", {"text": s("文字")}, ["text"], h_extract_urls, "文本處理")
    add("text_extract_masked_emails", "抽取並遮蔽 email 位址以降低敏感資料外洩", {"text": s("文字")}, ["text"], h_extract_emails, "AI 隱私工具")
    add("text_extract_masked_phone_candidates", "抽取電話格式候選並只回傳遮蔽尾碼", {"text": s("文字")}, ["text"], h_extract_phone_like, "AI 隱私工具")
    add("text_extract_date_candidates", "擷取常見日期格式候選並提示需人工確認", {"text": s("文字")}, ["text"], h_extract_dates, "文本處理")
    add("text_extract_numeric_values", "擷取文字中數字、百分比及小數值", {"text": s("文字")}, ["text"], h_extract_numbers, "文本處理")
    add("text_extract_citation_candidates", "擷取文字中常見引用、DOI 或 URL 候選", {"text": s("文字")}, ["text"], h_extract_citations, "文本處理")
    add("text_detect_script_hint", "依 Unicode 字元統計推測主要文字系統，不宣稱語言辨識", {"text": s("文字")}, ["text"], h_detect_language_hint, "文本處理")
    add("text_split_bounded_chunks", "將長文字切成有限字元區塊並保留少量重疊", {"text": s("文字"), "chunk_chars": i("區塊字元數", 8000), "overlap": i("重疊字元數", 500)}, ["text"], h_split_text_chunks, "文本處理")
    add("text_count_regex_patterns", "統計多個 regex pattern 在文字中的匹配次數", {"text": s("文字"), "patterns": s("每行一個 regex，最多 20 個")}, ["text", "patterns"], h_count_text_patterns, "文本處理")
    add("json_query_key_path", "以安全的點分隔路徑讀取 JSON 值", {"text": s("JSON 文字"), "key": s("路徑，例如 user.profile.name")}, ["text", "key"], h_make_json_key_path, "編碼與資料")
    add("json_pointer_query", "使用 JSON Pointer 讀取 JSON 節點", {"text": s("JSON 文字"), "pointer": s("JSON Pointer")}, ["text", "pointer"], h_validate_json_pointer, "編碼與資料")
    add("version_semver_validate", "驗證並拆解三段式 Semantic Version", {"value": s("版本字串")}, ["value"], h_validate_semver, "編碼與資料")
    add("timezone_offset_validate", "驗證固定 UTC offset 格式與合法範圍", {"value": s("例如 +08:00")}, ["value"], h_validate_utc_offset, "時間曆法")
    add("network_validate_ipv4", "解析 IPv4 並分類私有、全域或 loopback 位址", {"value": s("IPv4")}, ["value"], h_validate_ipv4, "網路探測")
    add("network_validate_ipv6", "解析 IPv6 並分類私有、全域或 loopback 位址", {"value": s("IPv6")}, ["value"], h_validate_ipv6, "網路探測")
    add("date_countdown_between", "計算兩個 ISO 日期間隔與週日數", {"start_date": s("開始日期 YYYY-MM-DD"), "end_date": s("結束日期 YYYY-MM-DD")}, ["start_date", "end_date"], h_countdown_between_dates, "時間曆法")
    add("text_normalize_whitespace", "統一水平空白並收斂多重空行", {"text": s("文字")}, ["text"], h_normalize_whitespace, "文本處理")
    add("text_escape_markdown", "跳脫 Markdown 特殊字元以安全顯示使用者文字", {"text": s("文字")}, ["text"], h_escape_markdown, "文本處理")
    add("text_html_entities", "對文字執行 HTML entity escape 或 unescape", {"text": s("文字"), "mode": {"type": "string", "enum": ["escape", "unescape"]}}, ["text"], h_html_entities, "編碼與資料")
    add("base64_encoded_size", "估算 UTF-8 文字 Base64 編碼長度", {"text": s("文字")}, ["text"], h_base64_size, "編碼與資料")
    add("text_digest_hash", "對文字計算指定摘要雜湊；不適用於密碼儲存", {"text": s("文字"), "algorithm": {"type": "string", "enum": ["sha256", "sha512", "sha1", "md5"]}}, ["text"], h_hash_text, "編碼與資料")
    add("url_parse_components", "以標準 URL parser 拆解 URL 元件，不發出網路請求", {"text": s("URL")}, ["text"], h_parse_url, "網路探測")
    add("csv_bounded_preview", "解析 CSV 並回傳有限列預覽", {"text": s("CSV 文字"), "rows": i("預覽列數", 30)}, ["text"], h_csv_preview, "編碼與資料")
    add("table_transpose_csv", "將 CSV 表格行列轉置，並補齊不等長列", {"text": s("CSV 文字")}, ["text"], h_transpose_table, "編碼與資料")
    add("text_split_sentences", "以中英文標點將文字分割為句子", {"text": s("文字")}, ["text"], h_split_sentences, "文本處理")
    add("email_syntax_check", "檢查 email 格式是否看似合理，不驗證信箱存在", {"value": s("Email")}, ["value"], h_validate_email_shape, "AI 隱私工具")
    return specs

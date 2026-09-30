# 本機低記憶體開發與測試

本機開發優先降低記憶體尖峰並維持執行穩定：測試預設不平行執行，也不要同時啟動多個 Bot／pytest 程序。

## 建議流程

```bash
znenv/bin/python -m pytest
```

pytest 設定採序列執行。若目前記憶體緊張，可只執行需要的測試檔：

```bash
znenv/bin/python -m pytest tests/test_ai_tool_routing.py
```

不需要在一般測試期間啟動 Discord Bot、下載模型或執行模型推論。需要測 Embedding 時，使用 fake/stub session 或只測單一模型路徑；避免同時載入六個 ONNX session。

## ONNX 執行資源

- ZeroNexus 會優先逐個載入模型；同一時間最多保留一個 ONNX session。
- 預設每個 session 使用單一 intra-op 與 inter-op 執行緒。
- 可用 `ZERONEXUS_ONNX_THREADS` 設定執行緒數（預設 `1`，上限 `2`）。
- 關閉不再使用的 session 後，會清除 session 參照並回收 Python／NumPy 暫存。

## 本地神經模型檔案

啟動時只檢查六個 Embedding／分類模型是否存在且大小合理，不會自動下載大檔。缺少模型時核心功能仍可啟動，Embedding／分類會使用既有輕量備援；如需補齊，可自行執行：

```bash
znenv/bin/python scripts/brain/setup_brain_models.py
```

此命令會下載缺少的 Embedding／分類模型，請確認網路與磁碟空間足夠後再手動執行。

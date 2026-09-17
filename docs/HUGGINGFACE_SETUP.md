# Hugging Face 模型串接與推論設定指南 (Hugging Face Setup Guide)

ZeroNexus 支援透過官方 Hugging Face Serverless / Router Inference API 串接開源頂級語言模型（如 Meta Llama 3.3 70B、Qwen 2.5 72B、Mistral 等）。

本文件提供完整的繁體中文設定步驟、環境變數配置以及疑難排解說明。

---

## 一、 獲取 Hugging Face Access Token

1. 前往 [Hugging Face 官方網站](https://huggingface.co/) 並登入您的帳號。
2. 點擊右上角個人頭像，進入 **Settings** ➔ **Access Tokens**（或直接訪問 `https://huggingface.co/settings/tokens`）。
3. 點擊 **Create new token**。
4. 設定 Token 名稱（例如：`ZeroNexus-Bot`），Type 選擇 **Read** 權限即可（推論僅需 Read 權限）。
5. 點擊 **Create token**，並複製生成的金鑰（格式通常為 `hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）。

> [!IMPORTANT]
> 請妥善保管您的 Token，ZeroNexus 內部具備自動遮蔽與脫敏防護（日誌僅會顯示 `hf_••••xxxx`），絕不以明文外洩金鑰。

---

## 二、 環境變數配置 (.env)

在 ZeroNexus 專案根目錄的 `.env` 檔案中新增或修改以下配置：

```bash
# ------------------------------------------------------------------------------
# Hugging Face AI 設定
# ------------------------------------------------------------------------------
# 您的 Hugging Face Read Access Token
HUGGINGFACE_TOKEN=hf_your_token_here

# 預設呼叫的 Hugging Face 模型名稱 (支援 Hub 上的標準 model ID)
# 推薦模型：
# - meta-llama/Llama-3.3-70B-Instruct (推薦，性能卓越)
# - Qwen/Qwen2.5-72B-Instruct (強大中文與程式碼能力)
# - mistralai/Mistral-7B-Instruct-v0.3 (輕量級快速響應)
HUGGINGFACE_MODEL=meta-llama/Llama-3.3-70B-Instruct
```

---

## 三、 API 端點與連線架構

ZeroNexus 採用高可用雙端點自動故障轉移架構：

1. **主端點 (Primary Router Endpoint)**:
   `https://router.huggingface.co/hf-inference/v1/chat/completions`
   採用 OpenAI 相容格式，由 Hugging Face 智慧路由分配至最佳可用節點。

2. **備份端點 (Fallback Inference Endpoint)**:
   `https://api-inference.huggingface.co/v1/chat/completions`
   當主路由發生非 200 異常或網路逾時時，系統自動容錯切換至 Serverless 備份端點。

---

## 四、 如何在 Discord 中使用 Hugging Face 模型

1. **指令切換**：
   使用 `/人工智慧 切換模型` 指令，在模型名稱中輸入：
   - `meta-llama/Llama-3.3-70B-Instruct` 或 `llama-3.3-70b`
   - `Qwen/Qwen2.5-72B-Instruct`
   - 或其他 Hugging Face Hub 上已支援 Serverless Inference 的相容模型。

2. **自然語言切換**：
   在 AI 對話頻道中直接輸入：
   - 「幫我切換成 llama 3.3」
   - 「改用 qwen 2.5 72b」
   ZeroNexus 會自動比對模型目錄並切換您的個人偏好，由當前人設自然銜接後續對話。

---

## 五、 常見問題排查 (FAQ)

### Q1: 呼叫時出現 `HTTP 401 Unauthorized`？
- **原因**：提供的 `HUGGINGFACE_TOKEN` 無效或過期。
- **排查**：請至 Hugging Face Token 管理頁面確認 Token 狀態，並確認已授予 `Read` 權限。

### Q2: 呼叫時出現 `HTTP 503 Model is currently loading`？
- **原因**：部分冷門模型在 Serverless API 處於睡眠狀態，需要 20~60 秒預熱加載。
- **處理**：ZeroNexus 預設設有重試退避機制；若急需使用，建議改用常駐熱點模型如 `meta-llama/Llama-3.3-70B-Instruct`。

### Q3: 呼叫時出現 `HTTP 429 Rate limit exceeded`？
- **原因**：免費版 Serverless API 達到當前時段頻率上限。
- **處理**：ZeroNexus 金鑰池會自動將該金鑰納入指數退避冷卻，並自動容錯至 Gemini / DeepSeek / OpenRouter 等備用渠道，保障對話不中斷。

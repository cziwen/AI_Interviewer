# 快速启动指南

本指南基于当前代码实现：**ASR -> 决策/LLM -> TTS**。

## 前置要求

- Python 3.9+
- Node.js 16+
- 可用的方舟/豆包语音凭证

## 后端启动

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp ../.env.local.example .env
uvicorn app.main:app --reload
```

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

## 必填环境变量（核心）

| 变量 | 说明 |
|---|---|
| `ARK_API_KEY` | 方舟文本模型调用密钥（LLM/Eval/Decision） |
| `ARK_BASE_URL` | 方舟兼容 API Base URL |
| `ARK_LLM_MODEL` | 文本模型（建议 `doubao-seed-2-0-mini-260215`） |
| `ARK_ASR_MODE` | `sauc_v3` / `openspeech_v2` / `gateway_json` |
| `ARK_ASR_WS_URL` | ASR WebSocket 地址 |
| `ARK_ASR_APP_ID` | ASR 应用 AppID（sauc/openspeech 模式） |
| `ARK_ASR_ACCESS_TOKEN` | ASR Access Token（sauc/openspeech 模式） |
| `ARK_ASR_RESOURCE_ID` | ASR 资源 ID（sauc_v3 常用） |
| `ARK_ASR_CLUSTER` | ASR 集群（如 `bigmodel`） |
| `ARK_TTS_MODEL` | TTS 模型/服务标识 |
| `ARK_TTS_VOICE` | TTS 音色（如 `zh_female_shuangkuaisisi_moon_bigtts`） |
| `ARK_TTS_SAMPLE_RATE` | 采样率，默认 24000 |

## 推荐本地 ASR/TTS 组合（与当前代码匹配）

```env
ARK_ASR_MODE=sauc_v3
ARK_ASR_WS_URL=wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
ARK_ASR_RESOURCE_ID=volc.bigasr.sauc.duration
ARK_ASR_CLUSTER=bigmodel
ARK_ASR_APP_ID=<your_app_id>
ARK_ASR_ACCESS_TOKEN=<your_asr_token>

ARK_LLM_MODEL=doubao-seed-2-0-mini-260215
ARK_TTS_VOICE=zh_female_shuangkuaisisi_moon_bigtts
```

## 验证

1. 打开 `http://localhost:5173/admin/login` 创建面试。
2. 进入 `/interview/{token}`，开始说话。
3. 预期行为：
- 后端日志出现 `asr.connecting` -> `asr.connected`
- 候选人说话后出现 `pipeline.transcribed`
- AI 返回 `response.created`、`response.audio.delta`、`response.done`

## 常见错误

- `HTTP 401`（ASR 连接）
: 多为 `ARK_ASR_ACCESS_TOKEN` / 资源权限 / `ARK_ASR_RESOURCE_ID` 不匹配。

- `code 45000030 requested resource not granted`
: 当前 token 未授权对应 `resource_id`，需在控制台开通或更换 `ARK_ASR_RESOURCE_ID`。

- `TTS 404`
: `ARK_TTS_MODEL` 不是可调用模型 ID 或当前账户未开通对应服务。

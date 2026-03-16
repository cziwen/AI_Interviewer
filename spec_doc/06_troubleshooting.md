# 故障排查指南

## 1. ASR 连接 401

**症状**
- `ws.error` 中出现 `server rejected WebSocket connection: HTTP 401`

**排查**
- 确认 `ARK_ASR_MODE` 与 `ARK_ASR_WS_URL` 对应。
- `sauc_v3` 模式需配置：
  - `ARK_ASR_APP_ID`
  - `ARK_ASR_ACCESS_TOKEN`
  - `ARK_ASR_RESOURCE_ID`
- `gateway_json` 模式通常使用 `ARK_API_KEY`，但权限模型不同，容易 401。

## 2. ASR 403 resource not granted

**症状**
- 错误码 `45000030`，提示 `requested resource not granted`

**原因**
- `ARK_ASR_RESOURCE_ID` 未开通或与 token 权限不匹配。

**处理**
- 在控制台确认可用 `resource_id`，更新 `.env` 后重启后端。

## 3. TTS 404

**症状**
- `audio.speech.create` 或 TTS 请求返回 404

**原因**
- `ARK_TTS_MODEL` 不是可调用模型 ID/服务标识。

**处理**
- 使用控制台 API 示例中的模型/服务参数。
- 若走 openspeech v1，请确认 `Authorization: Bearer;{token}` 格式与 `voice_type` 参数。

## 4. LLM 可用但语音不可用

**现象**
- `ARK_LLM_MODEL` 调用正常，ASR/TTS 失败。

**解释**
- 文本模型与语音服务通常是不同权限体系。
- 需要分别开通并配置语音侧凭证。

## 5. 快速自检脚本建议

- 验证 LLM：`chat.completions`
- 验证 TTS：请求返回 `code=3000` 且 `data` 可解码音频
- 验证 ASR：WebSocket 首帧能收到服务端响应（非 401/403）

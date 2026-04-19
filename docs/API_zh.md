# VoxCPM Local Launcher API

这是本地 VoxCPM 启动器的单页 API 文档。

[English API Docs](./API.md) | [README](../README.md) | [中文 README](../README_zh.md)

## 总览

服务当前暴露三组接口：

- OpenAI 兼容 TTS 接口
- VoxCPM 原生接口
- 本地 voice registry 接口

FastAPI 入口由 `app/api/main.py` 组装，请求归一化和 mode 映射由 `app/services/synthesis_service.py` 负责。

## 兼容性说明

当前服务已经补齐了和 `vllm-omni` VoxCPM2 OpenAI 示例的基础兼容：

- `POST /v1/audio/speech`
- 模型别名 `voxcpm2` 和 `openbmb/VoxCPM2`
- 占位字段 `voice: "default"`
- 通过 `ref_audio` 做声音克隆

额外兼容行为：

- `ref_audio` 可作为 `reference_audio` 的别名
- `ref_text` 可作为 `prompt_text` 的别名
- 音频引用支持：
  - 本地文件路径
  - `file://` URI
  - `http(s)` URL
  - `data:audio/...;base64,...`

## Base URL

默认本地 API 地址：

```text
http://127.0.0.1:8000
```

## 模型名

TTS 请求当前接受这些模型名：

- `voxcpm2`
- `openbmb/VoxCPM2`
- `voxcpm-openai-tts`
- 启动器实际加载的本地模型 id，比如 `models/OpenBMB__VoxCPM2`

可通过下面接口查询：

- `GET /v1/models`

## 路由总表

### 系统接口

- `GET /`
- `GET /health`
- `GET /api/health`
- `GET /v1/models`
- `GET /voxcpm/meta`

### OpenAI 兼容 TTS

- `GET /v1/audio/voices`
- `GET /v1/audio/speakers`
- `GET /speakers`
- `POST /v1/audio/speech`

### VoxCPM 原生接口

- `POST /voxcpm/speech`
- `POST /voxcpm/generate`
- `POST /voxcpm/speech/upload`
- 兼容别名：
  - `POST /api/v1/tts/voxcpm`
  - `POST /api/tts/voxcpm`
  - `POST /api/tts`

### Voice Registry

- `GET /voxcpm/voices`
- `POST /voxcpm/voices`
- `GET /voxcpm/voices/{voice_id}`
- `DELETE /voxcpm/voices/{voice_id}`

## Mode 模型

当前内部归一成 3 个执行模式：

- `design`
  - 只有文本
- `clone`
  - 参考音频或已注册音色
- `ultimate_clone`
  - `prompt_text` 加提示音频/参考音频

接受的外部 mode 别名包括：

- `preset_voice`
- `reference`
- `reference_with_text`
- `cross_lingual`
- `instruction`
- `voice_design`
- `tts`

## 特殊 Token 与风格标记

我检索了当前上游 `VoxCPM/` 子模块的公开 README、推理代码和文本归一化逻辑，当前没有发现一份面向客户端公开文档化的特殊 token 列表，例如 `[Surprise-ah]` 这一类可直接写进文本里的固定标签。

上游仓库当前明确公开的用法是：

- 音色设计：在 `text` 开头用括号写自然语言音色描述
- 可控克隆：在 `text` 开头用括号写自然语言风格提示
- 极致克隆：提供 `prompt_text` 和提示/参考音频

上游示例对应的写法更接近：

```text
(A young woman, gentle and sweet voice)Hello, welcome to VoxCPM2!
(slightly faster, cheerful tone)This is a cloned voice with style control.
```

这里有个很重要的区分：

- 当前没有证据表明上游公开支持一套稳定的 `[Surprise-ah]` 文本标签协议
- 不建议前端依赖未文档化的方括号 token
- 上游代码里出现的 `ref_audio tokens` 指的是模型内部结构，不是给客户端直接写进 `text` 的提示语法

推荐客户端做法：

- 优先使用自然语言风格提示
- 风格提示尽量简短，并放在文本最前面
- 优先使用显式字段：`reference_audio`、`prompt_audio`、`prompt_text`、`voice`、`voice_id`

## OpenAI 兼容 TTS

### 零样本示例

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"voxcpm2\", \"input\": \"Hello, this is VoxCPM2.\", \"voice\": \"default\"}" \
  --output output.wav
```

### 使用 `vllm-omni` 风格 `ref_audio` 做克隆

```json
{
  "model": "voxcpm2",
  "input": "This should sound like the reference speaker.",
  "voice": "default",
  "ref_audio": "data:audio/wav;base64,...",
  "response_format": "wav"
}
```

### 本地扩展字段

OpenAI 路由还支持这些扩展字段：

- `reference_audio`
- `prompt_audio`
- `prompt_text`
- `mode`
- `instruction`
- `auto_asr`
- `cfg_value`
- `inference_timesteps`
- `normalize`
- `denoise`

### 关键语义

- `voice` 不会自动创建持久化说话人
- 只有当 `voice` 命中已注册的 voice profile id 时，它才会变成可复用音色
- 单次请求里的 `ref_audio` 或 `reference_audio` 只是一次性 clone

## VoxCPM 原生接口

### JSON 接口

```json
{
  "model": "voxcpm2",
  "text": "要合成的文本",
  "mode": "reference_with_text",
  "reference_audio": "file:///D:/voices/ref.wav",
  "prompt_text": "参考文本",
  "response_format": "wav"
}
```

### 上传接口

`POST /voxcpm/speech/upload` 支持 multipart 表单字段：

- `text`
- `mode`
- `voice_id`
- `reference_audio`
- `prompt_audio`
- `prompt_text`
- `response_format`

上传文件是临时文件，请求结束后会自动清理，不会自动保存成可复用音色。

## Voice Registry

voice profile 默认保存在：

```text
runtime/voices/<voice_id>/
```

### 创建或更新

```json
{
  "id": "taichi_cn_01",
  "display_name": "Taichi CN",
  "mode_hint": "reference_with_text",
  "audio_path": "file:///D:/voices/taichi/ref.wav",
  "prompt_text": "参考文本",
  "copy_audio_to_registry": true
}
```

### 查询列表

```bash
curl http://localhost:8000/voxcpm/voices
```

### 删除

```bash
curl -X DELETE http://localhost:8000/voxcpm/voices/taichi_cn_01
```

### 复用已注册音色

OpenAI 兼容请求：

```json
{
  "model": "voxcpm2",
  "input": "请用已注册音色读这句话。",
  "voice": "taichi_cn_01"
}
```

原生请求：

```json
{
  "model": "voxcpm2",
  "text": "请用已注册音色读这句话。",
  "voice_id": "taichi_cn_01"
}
```

## 删除语义

- 临时上传音频会在请求完成后自动删除
- 已注册音色必须通过 `DELETE /voxcpm/voices/{voice_id}` 删除
- 在 Windows 下如果遇到文件锁，物理目录删除可能延后，但逻辑删除会立即生效

## 返回格式

当前输出格式只支持：

- `wav`

服务端返回：

- `Content-Type: audio/wav`
- 响应体直接是音频字节
- `X-VoxCPM-Model`：最终命中的本地模型 ID
- `X-VoxCPM-Sample-Rate`：输出采样率
- `X-VoxCPM-Audio-Seconds`：生成音频时长，单位秒
- `X-VoxCPM-Output-Bytes`：最终 WAV 载荷大小，单位字节
- `X-VoxCPM-Synthesis-Seconds`：合成阶段墙钟耗时，单位秒
- `X-VoxCPM-RTF`：实时率，计算方式为 `synthesis_seconds / audio_seconds`

说明：

- `X-VoxCPM-Synthesis-Seconds` 只统计请求归一化完成之后的合成阶段。
- 上传保存、远程 `ref_audio` 下载、以及响应回传不计入这个指标。

## 推荐使用方式

Neiroha 前端和通用 OpenAI 风格客户端，优先走 OpenAI 路由。

如果你需要下面这些能力，优先走原生路由：

- multipart 上传
- 更明确的 mode 控制
- voice registry 管理
- 更清晰的本地语义

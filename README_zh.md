# VoxCPM Local Launcher

一个面向本地部署的 VoxCPM 封装工作区，目标是把官方 `VoxCPM/` WebUI、外层启动脚本和 FastAPI 服务拆开管理，同时保留一套稳定的本地启动方式。

当前仓库提供：

- `pixi` 环境管理
- 从 ModelScope 下载模型到项目本地 `./models`
- 通过 Git submodule 引入官方 `OpenBMB/VoxCPM`
- 官方 Gradio WebUI 启动脚本
- API-only 模式
- OpenAI 风格兼容接口
- VoxCPM 原生接口
- 本地 voice registry 路由
- 可选 ASR，默认禁用，避免极致克隆时自动拉取或自动识别

## 当前能力

- 默认主模型：`OpenBMB/VoxCPM2`
- 默认 ASR 模型：`iic/SenseVoiceSmall`
- 模型下载目录：`./models`
- ModelScope 缓存目录：`./models/_modelscope_cache`
- API 路由已经从 `scripts/launch_voxcpm.py` 拆到独立 `app/api/routers/`
- `scripts/launch_voxcpm.py` 现在只负责 CLI、Gradio 挂载和 Uvicorn 启动编排
- `voice` / `voice_id` 已经可以映射到本地 `runtime/voices/` registry
- 原生接口已经覆盖：
  - 文件路径
  - `file:///` URI
  - multipart 上传
  - `voice_id` 引用
- 极致克隆默认要求手动提供 `prompt_text`
- 只有服务端启用 `--enable-asr` 且请求里传 `auto_asr=true` 时，才会自动识别参考音频文本

## 目录结构

```text
.
├─ app/
│  ├─ api/
│  │  ├─ main.py
│  │  └─ routers/
│  │     ├─ health.py
│  │     ├─ openai_tts.py
│  │     ├─ voxcpm_native.py
│  │     └─ voices.py
│  ├─ core/
│  │  ├─ config.py
│  │  ├─ registry.py
│  │  ├─ schemas.py
│  │  └─ utils.py
│  └─ services/
│     └─ synthesis_service.py
├─ scripts/
│  ├─ launch_voxcpm.py
│  ├─ download_modelscope_model.py
│  └─ adopt_modelscope_cache.py
├─ runtime/
│  └─ voices/
├─ models/
├─ VoxCPM/
├─ pixi.toml
├─ pixi.lock
└─ plan.md
```

说明：

- `VoxCPM/` 通过 Git submodule 固定到官方上游 `https://github.com/OpenBMB/VoxCPM.git`
- `app/` 对齐 `plan.md` 的推荐结构，承担 FastAPI、schema、registry 和 service
- `runtime/voices/` 用来保存本地 voice profile
- `models/`、`runtime/`、`.pixi/` 都属于本地运行资产，不应直接提交

## 快速开始

### 0. 拉取仓库与子模块

首次克隆时建议直接带上 submodule：

```powershell
git clone --recurse-submodules https://github.com/neiroha/<repo-name>.git
cd <repo-name>
```

如果已经克隆了外层仓库，再执行一次：

```powershell
git submodule update --init --recursive
```

### 1. 安装环境

```powershell
pixi install
```

### 2. 下载主模型

```powershell
pixi run install
```

### 3. 可选下载或接管 ASR 模型

如果直接从 ModelScope 下载：

```powershell
pixi run install-asr
```

如果 ASR 已经被官方 WebUI 下载到了用户缓存，可直接接管到本项目：

```powershell
pixi run adopt-asr-cache
```

### 4. 启动服务

默认不启用 ASR：

```powershell
pixi run webui
pixi run api
pixi run combined
```

启用本地 ASR：

```powershell
pixi run webui-asr
pixi run api-asr
pixi run combined-asr
```

查看启动参数：

```powershell
pixi run launcher-help
```

## API 路由

### 系统与元信息

- `GET /`
- `GET /health`
- `GET /api/health`
- `GET /v1/models`
- `GET /voxcpm/meta`

### OpenAI 兼容接口

- `GET /v1/audio/voices`
- `GET /v1/audio/speakers`
- `GET /speakers`
- `POST /v1/audio/speech`

### VoxCPM 原生接口

- `POST /voxcpm/speech`
- `POST /voxcpm/generate`
- `POST /voxcpm/speech/upload`
- 兼容别名：
  - `/api/v1/tts/voxcpm`
  - `/api/tts/voxcpm`
  - `/api/tts`

### Voice Registry

- `GET /voxcpm/voices`
- `POST /voxcpm/voices`
- `GET /voxcpm/voices/{voice_id}`
- `DELETE /voxcpm/voices/{voice_id}`

## 支持的输入入口

同一套 FastAPI 现在支持 4 类输入方式：

### 1. 直接传本地文件路径

```json
{
  "text": "请读这句话",
  "reference_audio": "D:/voices/ref.wav"
}
```

### 2. 传 `file:///` URI

```json
{
  "text": "请读这句话",
  "reference_audio": "file:///D:/voices/ref.wav"
}
```

### 3. 走 multipart 上传音频

- `POST /voxcpm/speech/upload`

### 4. 走已注册的 `voice_id`

```json
{
  "text": "请读这句话",
  "voice_id": "taichi_cn_01"
}
```

## 生成模式

当前内部真正落地的是 3 个归一化模式：

### 1. `design`

- 纯文本生成
- 不需要参考音频

### 2. `clone`

- 需要 `reference_audio` 或 `voice_id`
- 可选 `instruction` / `control`

### 3. `ultimate_clone`

- 需要目标文本
- 需要 `prompt_text`
- 需要 `prompt_audio`、`reference_audio` 或 `voice_id`
- 如果只传一个音频路径，服务端会把它同时当作 `reference_audio` 和 `prompt_audio`

同时接受下面这些外部别名并自动归一：

- `preset_voice`
- `reference`
- `reference_with_text`
- `cross_lingual`
- `instruction`
- `voice_design`
- `tts`

## Voice Registry 设计

本地 voice profile 会保存在：

```text
runtime/
  voices/
    <voice_id>/
      meta.json
      reference.wav
      prompt.wav
```

注册 voice 的 JSON 示例：

```json
{
  "id": "taichi_cn_01",
  "display_name": "太乙真人-中文",
  "engine": "torch_native",
  "model": "models/OpenBMB__VoxCPM2",
  "mode_hint": "reference_with_text",
  "audio_path": "file:///D:/voices/taichi/ref.wav",
  "prompt_text": "对，这就是我，万人敬仰的太乙真人。",
  "language": "zh",
  "copy_audio_to_registry": true
}
```

说明：

- `audio_path` 是参考音频
- `prompt_audio_path` 可选，用于极致克隆
- `copy_audio_to_registry=true` 时，会把音频复制到 `runtime/voices/<id>/`
- OpenAI `voice` 字段和原生接口 `voice_id` 都会优先查这个 registry

## 请求示例

### OpenAI 兼容接口

```json
{
  "model": "voxcpm-openai-tts",
  "input": "请用温柔一点的语气读这句话。",
  "voice": "taichi_cn_01",
  "response_format": "wav",
  "mode": "preset_voice"
}
```

### VoxCPM 原生接口

```json
{
  "model": "models/OpenBMB__VoxCPM2",
  "text": "要合成的文本",
  "mode": "reference_with_text",
  "voice_id": "taichi_cn_01",
  "response_format": "wav"
}
```

## 发布说明

建议发布到 `neiroha` 组织下的新仓库，例如：

```text
https://github.com/neiroha/<repo-name>.git
```

当前仓库采用的就是推荐方案：

- 外层仓库维护 `pixi` 环境、下载脚本、FastAPI 封装和启动器
- 官方 `VoxCPM/` 通过 Git submodule 固定到上游仓库
- 模型、缓存、日志、voice registry 和运行时输出不进入版本控制

如果后续要更新官方上游，可以使用：

```powershell
git submodule update --remote --init VoxCPM
```

## 注意事项

- 仓库不会提交模型权重
- 仓库不会提交运行期缓存、日志和测试音频
- `runtime/voices/` 默认视为本地资产
- 如需重新启用极致克隆里的自动识别能力，请使用 `*-asr` 任务启动
- 当前主要针对 Windows + CUDA + Pixi 工作流

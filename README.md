# VoxCPM Local Launcher

一个面向本地部署的 VoxCPM 封装工作区，提供：

- `pixi` 环境管理
- 从 ModelScope 下载模型到项目本地 `./models`
- 官方 Gradio WebUI 启动脚本
- 单独的 FastAPI 服务
- OpenAI 风格兼容接口
- 可选 ASR，默认禁用，避免极致克隆时自动拉取或自动识别

这个仓库的发布目标是 GitHub 组织账号 `neiroha`，而不是个人账号。

## 当前能力

- 默认主模型：`OpenBMB/VoxCPM2`
- 默认 ASR 模型：`iic/SenseVoiceSmall`
- 模型下载目录：`./models`
- ModelScope 缓存目录：`./models/_modelscope_cache`
- API-only 模式已经和官方 WebUI 解耦
- 极致克隆默认要求手动提供 `prompt_text`
- 只有服务端启用 `--enable-asr` 且请求里传 `auto_asr=true` 时，才会自动识别参考音频文本

## 目录结构

```text
.
├─ pixi.toml
├─ pixi.lock
├─ scripts/
│  ├─ launch_voxcpm.py
│  ├─ download_modelscope_model.py
│  └─ adopt_modelscope_cache.py
├─ models/
├─ runtime/
└─ VoxCPM/
```

说明：

- `VoxCPM/` 是当前本地克隆的上游官方仓库
- `models/`、`runtime/`、`.pixi/` 都属于本地运行资产，不应直接提交

## 快速开始

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

## API 路由

### 健康检查

- `GET /health`

### OpenAI 兼容接口

- `GET /v1/models`
- `GET /v1/audio/voices`
- `POST /v1/audio/speech`

### 原生接口

- `GET /voxcpm/meta`
- `POST /voxcpm/speech`
- `POST /voxcpm/speech/upload`
- 兼容别名：
  - `/voxcpm/generate`
  - `/api/v1/tts/voxcpm`
  - `/api/tts/voxcpm`
  - `/api/tts`

## 三种生成模式

### 1. `design`

- 纯文本生成
- 不需要参考音频

### 2. `clone`

- 需要 `reference_audio`
- 可选 `instruction` / `control`

### 3. `ultimate_clone`

- 需要目标文本
- 需要 `prompt_text`
- 需要 `prompt_audio` 或 `reference_audio`
- 如果只传一个音频路径，服务端会把它同时当作 `reference_audio` 和 `prompt_audio`

## 发布说明

建议发布到 `neiroha` 组织下的新仓库，例如：

```text
https://github.com/neiroha/<repo-name>.git
```

推送前请注意一件事：

当前 `VoxCPM/` 目录本身还是一个独立 Git 仓库，里面有自己的 `.git`。这意味着外层仓库在第一次 `git add .` 之前，需要先决定采用哪种方式：

1. 保持 `VoxCPM/` 为上游子模块风格
2. 去掉 `VoxCPM/.git`，把上游代码作为普通目录一并纳入外层仓库

如果目标是发布一个“可复现的本地启动器整合仓库”，通常更推荐先确认许可证要求，再决定是否保留为子模块。

## 注意事项

- 仓库不会提交模型权重
- 仓库不会提交运行期缓存、日志和测试音频
- 如需重新生成极致克隆里的自动识别能力，请使用 `*-asr` 任务启动
- 当前主要针对 Windows + CUDA + Pixi 工作流

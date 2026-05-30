# Neiroha-VoxCPM

[Neiroha](https://github.com/Neiroha/Neiroha)的VoxCPM2推理后端,使用官方仓库+Pytorch+原模型实现.

包含一个独立的FastAPI服务和一个官方Gradio WebUI

兼容OpenAI TTS接口规范以及提供了一个原生的VoxCPM2接口.

本地配置默认使用 TOML 分层:

```text
configs/server.toml
configs/model-presets/default.toml
configs/voice-sets/default.toml
runtime/voices/<voice-id>/voice.toml
```

OpenAI API 里的 `model=default` 表示 voice set,不是底层 VoxCPM2 权重.底层模型路径、device、optimize、ASR 等参数放在 model preset 里.默认保留三种 VoxCPM2 原生推理/克隆模式的 voice profile:

- `voxcpm2-design`: 文本音色设计
- `voxcpm2-clone`: 参考音频可控克隆
- `voxcpm2-ultimate-clone`: `prompt_audio` + `prompt_text` 高保真克隆

[English](./README.md) 

[API Docs](./docs/API.md) | [API 文档-中文](./docs/API_zh.md) | [模型来源](./docs/model-sources.md)

## 快速开始

### 1. 拉取仓库与子模块

```powershell
git clone --recurse-submodules https://github.com/neiroha/Neiroha-VoxCPM.git
cd Neiroha-VoxCPM
```

如果外层仓库已经拉过，再执行：

```powershell
git submodule update --init --recursive
```

### 2. 安装环境

```powershell
pixi install
```

### 3. 下载主模型

```powershell
pixi run install
```

可选下载 ASR：

```powershell
pixi run install-asr
```

### 4. 启动服务

默认启动 API + Neiroha Admin：

```powershell
pixi run serve
```

只启动 API：

```powershell
pixi run api
```

端口、启动界面、预加载和默认 model preset 来自 `configs/server.toml` 与 `configs/model-presets/default.toml`，pixi task 不再硬编码端口和模型路径。

只启动 Neiroha Admin：

```powershell
pixi run admin
```

其他启动界面或引擎选项优先改 `configs/server.toml` 和 `configs/model-presets/default.toml`，临时覆盖参数可查看 `scripts/launch_engine.py --help`。

契约测试：

```powershell
pixi run test
pixi run smoke
```

查看启动参数：

```powershell
python -B scripts/launch_engine.py --help
```

如果是一次性克隆，传 `ref_audio` 或 `reference_audio` 即可。

如果要复用本地说话人，先调用 `POST /api/voxcpm/voices` 注册音色，然后请求里写：

```json
{
  "model": "default",
  "input": "请用已注册音色读这句话。",
  "voice": "taichi_cn_01"
}
```

`voxcpm2`、`openbmb/VoxCPM2`、`voxcpm-openai-tts` 这些旧 model 名仍可作为兼容别名使用。原生接口标准路径是 `/api/voxcpm/*`，旧的 `/voxcpm/*` 接口也继续保留。

## 目录结构

```text
├─ app/
├─ configs/
├─ docs/
├─ models/
├─ runtime/
├─ scripts/
├─ tests/
├─ VoxCPM/
└─ pixi.toml
```

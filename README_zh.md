# Neiroha-VoxCPM

[Neiroha](https://github.com/Neiroha/Neiroha)的VoxCPM2推理后端,使用官方仓库+Pytorch+原模型实现.

包含一个独立的FastAPI服务和一个官方Gradio WebUI

兼容OpenAI TTS接口规范以及提供了一个原生的VoxCPM2接口.

[English](./README.md) 

[API Docs](./docs/API.md) | [API 文档-中文](./docs/API_zh.md)

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

只启动 API：

```powershell
pixi run api
```

启用 ASR 的 API：

```powershell
pixi run api-asr
```

只启动 WebUI：

```powershell
pixi run webui
```

同时启动 API + WebUI：

```powershell
pixi run combined
```

查看启动参数：

```powershell
python -B scripts/launch_voxcpm.py --help
```

如果是一次性克隆，传 `ref_audio` 或 `reference_audio` 即可。

如果要复用本地说话人，先调用 `POST /voxcpm/voices` 注册音色，然后请求里写：

```json
{
  "model": "voxcpm2",
  "input": "请用已注册音色读这句话。",
  "voice": "taichi_cn_01"
}
```

## 目录结构

```text
├─ app/
├─ docs/
├─ models/
├─ runtime/
├─ scripts/
├─ VoxCPM/
├─ pixi.toml
└─ plan.md
```

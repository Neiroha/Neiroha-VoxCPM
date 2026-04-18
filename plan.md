# VoxCPM PyTorch 服务化改造计划

## 1. 方向重置

本计划废弃此前以 `VoxCPM.cpp / GGUF / C++ server` 为主线的方案，正式切换到下面这条路线：

- `官方 VoxCPM` 作为上游源码基线
- `PyTorch + CUDA` 作为唯一推理主线
- `pixi` 统一管理 Python 环境
- `FastAPI` 负责对外暴露接口
- `Nano-vLLM` 作为首选推理调度层
- 保留一层本地 engine 抽象，必要时可回退到官方 PyTorch 推理，不改外部 API

一句话总结：

**不再围绕 C++ 量化推理做工程，而是围绕官方 PyTorch 推理做一个适合 Windows 和多端接入的统一后端。**

## 2. 目标

这次改造只做后端，不碰前端 UI。交付目标有两个：

1. 提供一套 `OpenAI TTS` 兼容接口。
   - 兼容你现在的 `Neiroha` 这类适配层
   - 请求体风格兼容 `vllm-omni` 那类 OpenAI TTS 扩展字段
2. 提供一套 `VoxCPM2 原生接口`。
   - 面向不同推理模式
   - 不受 OpenAI schema 限制
   - 用来承接 clone / reference / transcript / instruction 等扩展能力

## 3. 已确认约束

- 目标场景是单人 TTS 软件，不追求高并发
- 优先考虑 `Windows + NVIDIA CUDA` 使用体验
- Python 环境统一由 `pixi` 管理
- CUDA 目标版本按你当前决定，先以 `12.8` 为本机基线(50系显卡支持)
如果有torch需要 
一律使用
torch = { url = "https://mirrors.aliyun.com/pytorch-wheels/cu128/torch-2.7.0%2Bcu128-cp312-cp312-win_amd64.whl" }
torchaudio = { url = "https://mirrors.aliyun.com/pytorch-wheels/cu128/torchaudio-2.7.0%2Bcu128-cp312-cp312-win_amd64.whl" }
torchvision = { url = "https://mirrors.aliyun.com/pytorch-wheels/cu128/torchvision-0.22.0%2Bcu128-cp312-cp312-win_amd64.whl" }

- 需要保留后续 Linux 一键启动的可能性
- 当前目录 `D:\Python_Project\VoxCPM` 还不是一个 `git` 仓库

最后这一点很重要：

**子模块必须挂在一个 git 仓库里，所以正式实施第一步不是直接 `submodule add`，而是先把当前工程初始化成父仓库，或者迁入你已有的主仓库。**

## 4. 核心决策

### 4.2 官方仓库必须作为子模块接入

官方仓库不直接散放到本地目录里，而是固定成子模块，例如：

```text
vendor/VoxCPM
```

这样做的好处：

- 上游版本清晰
- 以后同步 upstream 更容易
- 本地改动和上游源码能明确分层
- 你的服务化代码不会和官方源码混在一起

### 4.3 服务端必须做 engine 抽象

虽然当前规划优先走 `Nano-vLLM`，但不能把 API 层直接绑死在某一个推理入口上。

建议拆成：

- `NanoVllmEngine`
- `TorchNativeEngine`

两者共用同一套业务接口，FastAPI 只依赖抽象层。这样即使：

- Nano-vLLM 在 Windows 支持不稳定
- 某些 mode 暂时只能走官方 PyTorch
- 某些模型在 vLLM 路线上表现不理想

也不需要推翻整个后端结构。

## 5. 建议目录结构

```text
VoxCPM/
  plan.md
  pixi.toml
  .git/
  .gitmodules
  vendor/
    VoxCPM/                 # 官方仓库子模块
  app/
    api/
      main.py
      routers/
        health.py
        openai_tts.py
        voxcpm_native.py
        voices.py
    core/
      config.py
      schemas.py
      queue.py
      registry.py
    engines/
      base.py
      nanovllm_engine.py
      torch_native_engine.py
    services/
      synthesis_service.py
      model_service.py
      audio_loader.py
  runtime/
    models/
    voices/
    cache/
    outputs/
    logs/
  scripts/
    bootstrap.ps1
    bootstrap.sh
    download_models.py
    dev.py
```

### 旧目录处理建议

现有的 `VoxCPM.cpp-src` 不再继续扩展。处理策略：

- 先保留，不马上删除
- 标记为 `archive / experiment`
- 等 PyTorch 路线稳定后，再决定是否移出当前工程

## 6. 接口策略

## 6.1 OpenAI TTS 兼容接口

目标是让现有 `openaiCompatible` 适配器尽量少改，同时兼容你提到的 `vllm-omni` 风格附加字段。

### 需要暴露的接口

- `GET /health`
- `GET /v1/models`
- `GET /v1/audio/voices`
- `GET /speakers`
- `POST /v1/audio/speech`

### 基础请求体

```json
{
  "model": "voxcpm2",
  "input": "你好，欢迎使用 VoxCPM。",
  "voice": "character_name",
  "speed": 1.0,
  "response_format": "wav"
}
```

### 扩展字段策略

为了兼容 `vllm-omni` 类接口和你的中端透传逻辑，`POST /v1/audio/speech` 允许额外字段直接进请求体，不单独再包一层：

```json
{
  "model": "voxcpm2",
  "input": "请用中文说这句话。",
  "voice": "temporary",
  "response_format": "wav",
  "mode": "reference_with_text",
  "reference_audio": "file:///D:/voices/ref.wav",
  "prompt_text": "元参考文本",
  "instruction": "用温柔、轻快的语气",
  "language": "zh"
}
```

也就是说：

- OpenAI 基础字段保持兼容
- VoxCPM 扩展字段原样透传到后端
- API 层负责把这些字段映射成实际推理调用

### OpenAI 接口边界

这套接口主要服务于：

- 已注册音色的标准合成
- 简单 clone 请求
- 中端适配器直接透传附加参数

复杂模式虽然允许走这条接口，但文档上仍然建议用户优先使用原生接口，因为原生接口更清晰。

## 6.2 VoxCPM2 原生接口

这套接口不追求兼容 OpenAI，而是追求把模式表达清楚。

### 需要暴露的接口

- `POST /voxcpm/speech`
- `POST /voxcpm/speech/upload`
- `GET /voxcpm/voices`
- `POST /voxcpm/voices`
- `GET /voxcpm/voices/{id}`
- `DELETE /voxcpm/voices/{id}`

### 原生 JSON 合成接口

```json
{
  "model": "voxcpm2",
  "text": "要合成的文本",
  "mode": "reference_with_text",
  "voice_id": "optional_voice",
  "reference_audio": "file:///D:/voices/ref.wav",
  "prompt_text": "参考文本",
  "instruction": "平静、自然、偏播报",
  "language": "zh",
  "speed": 1.0,
  "response_format": "wav"
}
```

### 建议先抽象的模式

第一版先不要在计划阶段过度绑定官方内部 mode 名称，而是先抽象成下面几类：

- `preset_voice`
  - 使用已注册的 voice profile
- `reference`
  - 只提供参考音频
- `reference_with_text`
  - 参考音频 + prompt_text
- `cross_lingual`
  - 跨语言克隆
- `instruction`
  - 带语气/风格指令
- `design`
  - 文本描述音色

真正落地时，再根据 `vendor/VoxCPM` 里官方推理脚本和模型能力，把这些抽象模式精确映射到 upstream 可执行路径。

## 7. voice registry 设计

OpenAI 接口里的 `voice` 不应理解为“模型自带 speaker”，而应理解为你自己的音色注册表。

建议结构：

```json
{
  "id": "taichi_cn_01",
  "display_name": "太乙真人-中文",
  "engine": "nanovllm",
  "model": "voxcpm2",
  "mode_hint": "reference_with_text",
  "audio_path": "runtime/voices/taichi_cn_01/ref.wav",
  "prompt_text": "对，这就是我，万人敬仰的太乙真人。",
  "language": "zh",
  "sample_rate": 24000,
  "created_at": "2026-04-18T00:00:00Z",
  "updated_at": "2026-04-18T00:00:00Z"
}
```

建议目录：

```text
runtime/
  voices/
    taichi_cn_01/
      ref.wav
      meta.json
```

这样能同时满足：

- OpenAI `voice` 查询
- 原生接口的音色管理
- Windows 整合包里的导入导出

## 8. 环境与依赖策略

## 8.1 pixi 统一管理

`pixi.toml` 作为唯一环境入口，负责：

- Python
- PyTorch
- CUDA 对应依赖
- FastAPI / Uvicorn
- Pydantic
- SoundFile / Librosa / NumPy
- Hugging Face 下载工具
- Nano-vLLM 相关 Python 依赖

### 原则

- 不再引入 C++ 编译链作为主路径
- 不再围绕 GGUF / llama.cpp 类构建设计环境
- Windows 和 Linux 尽量共用同一份 `pixi.toml`

## 8.2 模型下载策略

后端应支持脚本自动下载模型，不要求用户手动整理目录。

建议统一下载到：

```text
models/
```

至少支持：

- 自动检测模型是否存在
- 缺失时按配置下载
- 启动前校验模型完整性
- 多模型共存

## 9. 服务端架构

## 9.1 推荐分层

```text
FastAPI Router
    |
    v
Synthesis Service
    |
    +-- Voice Registry
    +-- Audio Loader
    +-- Request Normalizer
    |
    v
Engine Adapter
    |
    +-- NanoVllmEngine
    +-- TorchNativeEngine
```

### 每层职责

- Router
  - 处理 HTTP 请求和响应
- Request Normalizer
  - 把 OpenAI 风格和原生风格的参数归一成统一内部请求对象
- Synthesis Service
  - 模式分发、队列控制、异常处理
- Engine Adapter
  - 真正调用 Nano-vLLM 或官方 PyTorch 推理

## 9.2 队列和并发

由于是单人 TTS 软件，先不要上复杂并发。

第一版只做：

- 单 GPU 串行队列
- 单次只跑一个推理任务
- 可返回排队状态或忙碌错误

这样能明显降低：

- 显存抖动
- 多请求争抢
- Windows 上长进程不稳定

## 10. 实施阶段

## P0：仓库清理与基线重建

目标：把工程结构从实验状态拉回正式状态。

需要完成：

1. 初始化当前父仓库为 git 仓库，或迁入现有主仓库
2. 把官方 `VoxCPM` 作为子模块接入
3. 新建 `pixi.toml`
4. 新建 `app/` 与 `runtime/` 基础目录
5. 把 `VoxCPM.cpp-src` 标记为归档实验目录
6. 记录 upstream commit 和本地改造范围

建议子模块路径：

```text
vendor/VoxCPM
```

## P1：环境和启动脚手架

目标：先把 Python 环境和服务启动骨架跑起来。

需要完成：

1. `pixi install`
2. `pixi run` 启动 FastAPI 开发服务
3. 加入基础配置文件和日志目录
4. 加入模型下载脚本
5. 加入健康检查接口

这一阶段先不要求真正出音频，但要把工程入口跑通。

## P2：Engine 层接入

目标：让后端真正能调用 `VoxCPM2` 推理。

需要完成：

1. 阅读 `vendor/VoxCPM` 中官方推理入口
2. 明确 Nano-vLLM 的接入点
3. 实现 `NanoVllmEngine`
4. 实现 `TorchNativeEngine` 作为保底
5. 统一内部 `SynthesisRequest / SynthesisResult`
6. 跑通最小文本合成

这一步是整个项目最关键的技术验证点。

## P3：OpenAI TTS 兼容接口

目标：让你现有中端尽快能直接接入。

需要完成：

1. `GET /v1/models`
2. `GET /v1/audio/voices`
3. `GET /speakers`
4. `POST /v1/audio/speech`
5. 支持标准字段和扩展字段透传
6. 返回原始音频字节与正确的 `Content-Type`

验收标准：

- 你的 OpenAI 兼容适配器能不大改直接接进来
- `voice` 能映射到 registry
- 附加字段能传到内部推理层

## P4：VoxCPM2 原生接口

目标：把真正的模式能力暴露出来。

需要完成：

1. `POST /voxcpm/speech`
2. `POST /voxcpm/speech/upload`
3. `GET /voxcpm/voices`
4. `POST /voxcpm/voices`
5. `GET /voxcpm/voices/{id}`
6. `DELETE /voxcpm/voices/{id}`

这一阶段重点不是“接口数量”，而是：

- 各 mode 的参数能否完整映射
- 上传音频、文件路径、voice_id 三种入口能否统一
- clone 和跨语言场景是否真的可用

## P5：Windows 交付整理

目标：让它适合作为你自己的 Windows 单机后端。

需要完成：

- 一键启动脚本
- 模型自动检测和下载
- 日志落盘
- 运行时目录固定
- 常见报错提示友好化

如果 Nano-vLLM 在 Windows 表现不稳，这一阶段直接切到：

- 同一套 FastAPI
- 同一套请求协议
- engine 改走 `TorchNativeEngine`

## 11. 风险点

### 风险 1：Nano-vLLM 在 Windows 的稳定性

处理策略：

- 从第一天就做 engine 抽象
- 不把业务逻辑写死在 Nano-vLLM
- 保留官方 PyTorch 直推的保底路径

### 风险 2：官方推理模式与预想 mode 不完全对应

处理策略：

- 计划里先做模式抽象
- 等子模块落地后再按 upstream 精确映射
- API 文档以“平台自定义 mode”对外，而不是强耦合内部函数名

### 风险 3：显存占用超出 8GB 级别预期

处理策略：

- 第一版先按串行推理设计
- 模型启动参数可配置
- 必要时允许降精度或降低某些生成参数

### 风险 4：Windows 和 Linux 依赖差异

处理策略：

- Python 依赖尽量收敛到 `pixi`
- 平台差异尽量只出现在启动脚本和少量配置层
- API 层和业务层不写平台分支

## 12. 验收标准

## 12.1 功能验收

- 能通过 `pixi` 一键拉起服务
- 能自动检测并下载模型
- 能通过 OpenAI 接口返回音频
- 能通过原生 VoxCPM 接口返回音频
- 能注册、查询、删除 voice profile
- 能处理至少一条 clone 流程

## 12.2 架构验收

- 官方源码以子模块存在
- 服务化代码和 upstream 源码物理隔离
- Nano-vLLM 和官方 PyTorch 至少具备一主一备两条可切换路径

## 12.3 使用体验验收

- Windows 本机能跑
- Linux 后续能复用同一套 API 设计
- 现有前端和中端适配层接入改动尽量小

## 13. 下一步执行顺序

按这个新方案，真正开始动手时的顺序应当是：

1. 把当前目录转成父 git 仓库
2. 把官方 `VoxCPM` 作为子模块接入 `vendor/VoxCPM`
3. 建好 `pixi.toml`
4. 先搭 FastAPI 骨架和 `/health`
5. 再读官方推理入口，接 `Nano-vLLM`
6. 最后补 OpenAI 兼容接口和原生接口

## 14. 最终结论

从现在开始，这个项目的正式主线应该是：

- `官方 VoxCPM` 负责模型与推理代码基线
- `pixi` 负责环境
- `PyTorch + CUDA` 负责推理
- `Nano-vLLM` 优先承担调度
- `FastAPI` 负责统一对外接口
- `OpenAI TTS + VoxCPM Native` 双接口并行提供

也就是说，后续工程重点不再是“怎么把 C++ 版再包漂亮一点”，而是：

**把官方 PyTorch 推理包装成一个你自己的、稳定的、可多端复用的 TTS 服务。**

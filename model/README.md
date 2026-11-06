# 智能模型资产

本目录保存两代 MaixCAM 的模型描述、运行时支撑代码和模型清单。

## 权重策略

正式权重不进入普通 Git：

- MaixCAM Pro 的 Maix-Speech KWS 权重只在 `/root/models/am_3332_192_int8.mud` 及其配套文件中；
- MaixCAM2 的 SenseVoice 两个 `.axmodel` 合计约 505 MB，普通 Git 不宜承载。

仓库保存 `.mud`、SenseVoice server/tokenizer/frontend 支撑代码、文件大小和 SHA256；运行时仍从 `/root/models/` 加载。

## 目录

```text
model/
├── manifest.json
├── maixcam_pro/
│   ├── README.md
│   └── check_model.sh
└── maixcam2/
    ├── README.md
    ├── sensevoice.mud
    ├── check_model.sh
    └── sensevoice-maixcam2/
        ├── SenseVoiceAx.py
        ├── server.py
        ├── tokenizer.py
        ├── frontend.py
        └── ... (不包含两个 .axmodel)
```

## 平台

| 平台 | 模型 | 任务 | 运行时路径 |
|---|---|---|---|
| MaixCAM Pro（一代） | `am_3332_192_int8.mud` | Maix-Speech KWS | `/root/models/am_3332_192_int8.mud` |
| MaixCAM2（二代） | SenseVoice + streaming | 开放词表 ASR | `/root/models/sensevoice-maixcam2/` |

## 边界

- STM32 不加载模型，只接收高层 `PERFORM` 事件；
- 模型权重和真机录音不进入公开仓库；
- 详细路径、大小和 SHA256 见 `manifest.json`。

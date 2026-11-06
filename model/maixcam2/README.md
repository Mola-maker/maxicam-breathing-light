# MaixCAM2（二代）SenseVoice 模型

运行时目录：

```text
/root/models/sensevoice-maixcam2/
├── sensevoice.axmodel              # 256,550,253 B
├── streaming_sensevoice.axmodel    # 249,023,211 B
├── SenseVoiceAx.py
├── am.mvn
├── chn_jpn_yue_eng_ko_spectok.bpe.model
├── client.py
├── embeddings.npy
├── frontend.py
├── model.mud
├── pe_nonstream.npy
├── pe_streaming.npy
├── server.py
└── tokenizer.py
```

应用描述符：

```text
/root/JLU_LEDLAB/config/sensevoice.mud
```

## 仓库包含什么

`model/maixcam2/sensevoice-maixcam2/` 包含除两个 `.axmodel` 权重外的全部支撑代码和小型数据文件。部署：

```sh
mkdir -p /root/models/sensevoice-maixcam2
cp -a model/maixcam2/sensevoice-maixcam2/. \
      /root/models/sensevoice-maixcam2/
cp model/maixcam2/sensevoice.mud \
   /root/JLU_LEDLAB/config/sensevoice.mud
```

## 外置权重

| 文件 | 大小 | SHA256 |
|---|---:|---|
| `sensevoice.axmodel` | 256,550,253 B | `67d290cf7cebf45db5f37b2e93b8bdfff44dc35110bb29d84204a5f9eae9fd4d` |
| `streaming_sensevoice.axmodel` | 249,023,211 B | `ba1ddd60841297903bfdae059ad88092d0fd1c543e1d80d7f64199d4e27b8263` |

权重从已有 MaixCAM2 设备、Sipeed 镜像或受控模型存储获取，不进入普通 Git。

## 校验

```sh
sh model/maixcam2/check_model.sh
```

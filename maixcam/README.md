# MaixCAM-Pro：YOLO11 姿态识别与 HTML 骨骼

模型已在设备 `/root/models` 时，无需再下载。此示例使用设备端 MaixPy 的
`nn.YOLO11`，不需要在 Pro 上安装 PyTorch 或 Ultralytics。

## 运行

1. 在 MaixVision 中连接 MaixCAM-Pro，打开文件夹 `/home/jlu/桌面/maixcam`。
2. 使用 MaixVision 的设备文件管理器确认模型名称。也可在**设备终端**执行：

   ```sh
   ls /root/models/*pose*.mud
   ```

3. 修改 `main.py` 顶部的 `MODEL_PATH`，默认是
   `/root/models/yolo11n_pose.mud`。必须使用 **YOLO11 人体 Pose 模型**，并保留
   `.mud` 引用的配套模型文件；普通目标检测模型不输出骨骼。模型必须适用于
   MaixCAM / MaixCAM-Pro，MaixCAM2 的模型不可直接替换。
4. 点击 **运行项目**，将 `main.py` 和 `index.html` 一起发送到设备。
   也支持“运行当前文件”：新版 `main.py` 内置了相同网页，漏传 HTML 时自动使用。
   项目内存在 `index.html` 时优先使用该文件；修改网页后请运行整个项目。
5. MaixVision 的预览和设备屏幕会显示摄像头画面、骨骼与英文姿态标签。
6. 从设备“设置 → 系统信息”或 MaixVision 获取设备 IP。
   电脑浏览器打开 `http://设备IP:8080`，页面自动读取实时骨骼，中文显示姿态。
   电脑必须能够访问设备 IP，例如连接设备 USB 网络或同一局域网。

只需要看 HTML 绘制效果时，在电脑上直接打开 `index.html`，使用演示按钮。
演示数据是人工生成的，不代表模型效果。浏览器实时页面只绘制骨骼；摄像头画面
请在 MaixVision 看。这里不读取电脑摄像头。

## 识别范围

YOLO11-Pose 检测 COCO 17 个关节，程序随后使用手腕高度与膝关节夹角进行
**单帧规则分类**：举左手、举右手、举双手、站立、屈膝／坐姿。
标签可以同时存在，例如“站立 / 举双手”。手腕高于肩膀是本示例“举手”的定义。

- 输出缺失坐标为 `null`，不画对应骨骼连线，也不将遮挡猜成确定姿态。
- 左右是人体自身的左右。网页人物编号只是当前帧顺序，没有跨帧跟踪。
- `crouch_or_sit` 表示两腿屈膝，不能可靠区分坐下与下蹲。
- 角度受拍摄方向影响；全身入镜、足够照明，并按现场效果调整
  `classify_pose()` 的高度阈值和角度阈值。
- 跑步、挥手、跌倒等连续动作需要跨帧跟踪与时序规则或单独训练的动作模型。
- `dual_buff=False` 使关键点对应当前图像，避免双缓冲带来的一帧偏移，代价是
  帧率可能降低。程序显示实测循环 FPS，没有预设性能承诺。
- 人体检测分数不是动作分类置信度。规则分类没有经过训练或准确率评估。

## 网页数据接口

`GET /api/pose` 返回最新一帧；网页按约 100 ms 的间隔轮询。

```json
{
  "width": 320,
  "height": 224,
  "frame_id": 1,
  "fps": 10.0,
  "age_ms": 20,
  "people": []
}
```

每个人包含 `index`、`score`、`bbox: [x,y,w,h]`、
`points: [[x,y],null,...]`（17 项）及 `actions`。坐标是模型输入图像中的像素。
数据超过 3 秒未更新或请求失败时，网页清除旧骨骼并显示状态。
HTTP 服务只提供页面与 JSON，使用 Python 标准库，无额外 Web 依赖。

## 常见问题

- `No such file`：检查的是**设备**路径，不是电脑路径。
- `index.html` 找不到：新版会改用内置网页；若仍然出现该异常，设备运行的是旧版
  `main.py`，请从本地重新运行最新文件。
- 找不到 `nn.YOLO11`：在设备设置中更新 MaixPy；电脑的补全包不能替代设备版本。
- 模型加载失败：检查 `.mud` 及配套文件、硬件目标与 Pose 模型类型。
- `Address already in use`：停止旧程序，或修改 `HTTP_PORT` 并使用相应端口访问。

## 搜索到的参考项目

使用 Exa 搜索 GitHub，并读取官方代码与文档后选择以下参考：

| 参考 | 用途与适用性 |
| --- | --- |
| [Sipeed 单文件姿态分类示例](https://github.com/sipeed/MaixPy/blob/main/examples/vision/ai_vision/nn_yolo11_pose_cls.py) | 最直接的 MaixPy YOLO11-Pose 参考；包含关节角度规则与屏幕骨骼绘制。 |
| [Sipeed Human Pose Classifier 应用](https://github.com/sipeed/MaixPy/tree/main/projects/app_human_pose_classifier) | 已有完整应用，便于参考更多姿态及界面。 |
| [1yakupoguz/pose-estimation-task](https://github.com/1yakupoguz/pose-estimation-task) | PC 上使用 YOLO11s-Pose、角度与跟踪判断姿态；不能原样在 Pro 的 NPU 上运行。 |

接口与运行方式依据：

- [Sipeed 人体关键点检测](https://wiki.sipeed.com/maixpy/doc/zh/vision/body_key_points.html)
- [Sipeed 人体姿态分类器](https://wiki.sipeed.com/maixpy/doc/zh/vision/body_pose_classification.html)
- [MaixVision 使用与运行项目](https://wiki.sipeed.com/maixpy/doc/zh/basic/maixvision.html)
- [dual_buff 帧对应说明](https://wiki.sipeed.com/maixpy/doc/zh/vision/dual_buff.html)

本示例独立实现；并未下载或复制完整第三方项目、权重。

## 本地验证

在电脑终端运行 `python3 -m unittest discover -v` 可检查规则和关键点转换。
本地检查不包含 Pro 硬件、摄像头或 NPU 推理；需按上述步骤在设备上验证。

# MaixCAM Pro（一代）KWS 模型

运行时模型：

```text
/root/models/am_3332_192_int8.mud
```

这是 Maix-Speech 的关键词识别描述符；它引用的配套 `.cvimodel` 等文件也必须位于模型目录。

当前仓库不包含该权重，因为模型只保存在一代 MaixCAM Pro 设备上，本工作区无法访问该设备；远端 Git 历史中也没有权重。

## 词表

```text
chang1 chang2 chang4
chun1 chun2 chun3
ang1 ang2
chang2 chun1
```

`ang` 仅调试；单字 `chang`/`chun` 的开门规则见 `maixcam/pro/app/README_pwm.md`，整词 `chang2 chun1` 可直接开门。

## 板端检查

```sh
ls -lh /root/models/am_3332_192_int8.mud
cat /root/models/am_3332_192_int8.mud
```

或：

```sh
sh model/maixcam_pro/check_model.sh
```

## 备份建议

在 Pro 上打包 `.mud` 及其引用的配套文件，放到受控模型存储或 Git LFS；不要直接塞进普通 Git。

# light-dots 俄罗斯方块

20x20 Surplife LED 窗帘上的俄罗斯方块。在本机终端游玩, 通过 MaixCAM (10.78.72.1:8000) 上现有的 Surplife API 推送画面。游戏区 20x18, 最下面两行固定灰色。

```bash
python3 tetris.py                 # 连接 http://10.78.72.1:8000
python3 tetris.py --offline       # 只在终端玩
python3 tetris.py --calib         # 方向校准: 左上红, 顶行绿, 左列蓝, 底两行灰
python3 tetris.py --no-transpose  # 默认已交换 x/y (实测需要), 另有 --flip-x / --flip-y
python3 -m unittest test_tetris
```

按键: W/↑ 旋转, A/← 左, D/→ 右, S/↓ 加速, 空格 落底, P 暂停, R 重来, Q 退出。终端至少 90x23。

协议逆向笔记见 ../PROTOCOL.md。

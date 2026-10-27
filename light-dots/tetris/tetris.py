#!/usr/bin/env python3
"""
20x20 LED 窗帘俄罗斯方块

终端里玩, 画面同步推送到 MaixCAM 上的 Surplife API (POST /pixels)。
协议细节见 ../PROTOCOL.md。

按键: WASD 或方向键 (W/↑ 旋转, A/← 左, D/→ 右, S/↓ 下落一格)
      空格 直接落底, P 暂停, R 重新开始, Q 退出

用法:
    python3 tetris.py                         # 默认 API http://10.78.72.1:8000
    python3 tetris.py --api http://IP:8000
    python3 tetris.py --offline               # 只在终端玩
    python3 tetris.py --calib                 # 显示方向校准图案后退出
    python3 tetris.py --no-transpose --flip-x # 如果灯面方向不对
"""

from __future__ import annotations

import argparse
import curses
import json
import random
import threading
import time
import urllib.error
import urllib.request

W, H = 20, 20
RESERVED = 2               # 最下面两行灰色预留
FIELD_H = H - RESERVED     # 游戏区 20 x 18
GREY = "#808080"
BLACK = "#000000"

# 名称: (形状, LED 颜色, curses 颜色)
PIECES = {
    "I": ([(0, 1), (1, 1), (2, 1), (3, 1)], "#00ffff", curses.COLOR_CYAN),
    "O": ([(1, 0), (2, 0), (1, 1), (2, 1)], "#ffff00", curses.COLOR_YELLOW),
    "T": ([(1, 0), (0, 1), (1, 1), (2, 1)], "#aa00ff", curses.COLOR_MAGENTA),
    "S": ([(1, 0), (2, 0), (0, 1), (1, 1)], "#00ff00", curses.COLOR_GREEN),
    "Z": ([(0, 0), (1, 0), (1, 1), (2, 1)], "#ff0000", curses.COLOR_RED),
    "J": ([(0, 0), (0, 1), (1, 1), (2, 1)], "#0000ff", curses.COLOR_BLUE),
    "L": ([(2, 0), (0, 1), (1, 1), (2, 1)], "#ff8000", curses.COLOR_WHITE),
}
LINE_SCORES = [0, 100, 300, 500, 800]


# ======================================================================
# 游戏逻辑
# ======================================================================

class Piece:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.cells = list(PIECES[kind][0])
        self.x = W // 2 - 2
        self.y = 0

    def blocks(self, cells=None, dx=0, dy=0):
        return [(self.x + cx + dx, self.y + cy + dy) for cx, cy in (cells or self.cells)]

    def rotated(self):
        if self.kind == "O":
            return list(self.cells)
        n = 4 if self.kind == "I" else 3
        # 顺时针: (x, y) -> (n-1-y, x)
        return [(n - 1 - cy, cx) for cx, cy in self.cells]


class Tetris:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.board: list[list[str | None]] = [[None] * W for _ in range(FIELD_H)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.over = False
        self.paused = False
        self._bag: list[str] = []
        self.next_kind = self._draw_bag()
        self.piece = self._spawn()

    def _draw_bag(self) -> str:
        if not self._bag:
            self._bag = list(PIECES)
            random.shuffle(self._bag)
        return self._bag.pop()

    def _spawn(self) -> Piece:
        p = Piece(self.next_kind)
        self.next_kind = self._draw_bag()
        if not self._fits(p.blocks()):
            self.over = True
        return p

    def _fits(self, blocks) -> bool:
        for x, y in blocks:
            if x < 0 or x >= W or y >= FIELD_H:
                return False
            if y >= 0 and self.board[y][x] is not None:
                return False
        return True

    @property
    def gravity(self) -> float:
        return max(0.08, 0.8 - (self.level - 1) * 0.07)

    def move(self, dx: int, dy: int) -> bool:
        if self._fits(self.piece.blocks(dx=dx, dy=dy)):
            self.piece.x += dx
            self.piece.y += dy
            return True
        return False

    def rotate(self) -> None:
        cells = self.piece.rotated()
        for kick in (0, -1, 1, -2, 2):          # 简单墙踢
            if self._fits(self.piece.blocks(cells, dx=kick)):
                self.piece.cells = cells
                self.piece.x += kick
                return

    def step(self) -> None:
        """重力下落一格, 落地则锁定"""
        if not self.move(0, 1):
            self._lock()

    def hard_drop(self) -> None:
        while self.move(0, 1):
            self.score += 2
        self._lock()

    def _lock(self) -> None:
        for x, y in self.piece.blocks():
            if y >= 0:
                self.board[y][x] = self.piece.kind
        full = [y for y in range(FIELD_H) if all(self.board[y])]
        for y in full:
            del self.board[y]
            self.board.insert(0, [None] * W)
        if full:
            self.lines += len(full)
            self.score += LINE_SCORES[len(full)] * self.level
            self.level = 1 + self.lines // 10
        self.piece = self._spawn()

    def frame(self) -> list[list[str]]:
        """20x20 #RRGGBB 画面, 底部两行为灰色"""
        f = [[BLACK] * W for _ in range(H)]
        for y in range(FIELD_H):
            for x in range(W):
                k = self.board[y][x]
                if k:
                    f[y][x] = PIECES[k][1]
        if not self.over:
            for x, y in self.piece.blocks():
                if 0 <= y < FIELD_H:
                    f[y][x] = PIECES[self.piece.kind][1]
        for y in range(FIELD_H, H):
            f[y] = [GREY] * W
        return f


# ======================================================================
# LED 推送 (后台线程, 只发差异, 总是发最新一帧)
# ======================================================================

class LedSink:
    def __init__(self, api: str, transpose=False, flip_x=False, flip_y=False) -> None:
        self.api = api.rstrip("/")
        self.transpose, self.flip_x, self.flip_y = transpose, flip_x, flip_y
        self._target: list[list[str]] | None = None
        self._sent: list[list[str]] | None = None   # None = 需要整屏重绘
        self._cond = threading.Condition()
        self._stop = False
        self.error: str | None = None
        self._last_check = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def show(self, frame: list[list[str]]) -> None:
        with self._cond:
            self._target = [row[:] for row in frame]
            self._cond.notify()

    def close(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()

    def _map(self, x: int, y: int) -> tuple[int, int]:
        if self.flip_x:
            x = W - 1 - x
        if self.flip_y:
            y = H - 1 - y
        return (y, x) if self.transpose else (x, y)

    def _post(self, path: str, body: dict | None, method: str = "POST") -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.api + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")

    def _mode_lost(self) -> bool:
        """语音控制 (/color) 会把灯切出绘图模式, 每 2 秒查一次"""
        now = time.time()
        if now - self._last_check < 2.0:
            return False
        self._last_check = now
        return self._post("/status", None, method="GET").get("mode") != "paint"

    def _run(self) -> None:
        last = None
        while True:
            with self._cond:
                if self._target is None and not self._stop:
                    self._cond.wait(0.5)
                if self._stop:
                    return
                target, self._target = self._target, None
            try:
                if target is None:
                    # 空闲: 画面被外部覆盖时整屏重绘
                    if last is None or not self._mode_lost():
                        continue
                    self._sent = None
                    target = last
                self._send(target)
                last = target
                self.error = None
            except (urllib.error.URLError, OSError, ValueError) as e:
                self.error = str(getattr(e, "reason", e))[:60]
                self._sent = None
                with self._cond:
                    if self._target is None:
                        self._target = target
                time.sleep(1.0)

    def _send(self, frame: list[list[str]]) -> None:
        """
        只发变化的像素。服务端按颜色分组, 每种颜色一条 BLE 命令, 按出现顺序发送;
        因此先列出彩色像素、最后列出黑色(擦除), 避免方块先灭再亮的闪烁。
        整屏重绘也不用 clear (先全灭再画), 而是直接覆盖每个像素。
        """
        paint, erase = [], []
        for y in range(H):
            for x in range(W):
                c = frame[y][x]
                if self._sent is not None and self._sent[y][x] == c:
                    continue
                dx, dy = self._map(x, y)
                (erase if c == BLACK else paint).append({"x": dx, "y": dy, "color": c})
        if paint or erase:
            self._post("/pixels", {"pixels": paint + erase, "clear": False})
        self._sent = [row[:] for row in frame]


def calib_frame() -> list[list[str]]:
    """(0,0) 红, 顶行绿, 左列蓝, 底两行灰: 用来确认方向"""
    f = [[BLACK] * W for _ in range(H)]
    for x in range(1, W):
        f[0][x] = "#00ff00"
    for y in range(1, H - RESERVED):
        f[y][0] = "#0000ff"
    f[0][0] = "#ff0000"
    for y in range(H - RESERVED, H):
        f[y] = [GREY] * W
    return f


# ======================================================================
# 终端界面
# ======================================================================

KEYS_LEFT = {curses.KEY_LEFT, ord("a"), ord("A")}
KEYS_RIGHT = {curses.KEY_RIGHT, ord("d"), ord("D")}
KEYS_DOWN = {curses.KEY_DOWN, ord("s"), ord("S")}
KEYS_ROT = {curses.KEY_UP, ord("w"), ord("W")}


def draw(scr, game: Tetris, frame, sink: LedSink | None) -> None:
    scr.erase()
    pair = {PIECES[k][1]: i + 1 for i, k in enumerate(PIECES)}
    pair[GREY] = len(PIECES) + 1
    ox, oy = 2, 1
    scr.addstr(oy - 1, ox, "+" + "--" * W + "+")
    for y in range(H):
        scr.addstr(oy + y, ox, "|")
        for x in range(W):
            c = frame[y][x]
            if c == BLACK:
                scr.addstr(" .")
            else:
                scr.addstr("██", curses.color_pair(pair[c]))
        scr.addstr("|")
    scr.addstr(oy + H, ox, "+" + "--" * W + "+")

    sx = ox + W * 2 + 5
    lines = [
        f"分数  {game.score}",
        f"行数  {game.lines}",
        f"等级  {game.level}",
        "",
        "下一个:",
    ]
    for i, s in enumerate(lines):
        scr.addstr(oy + i, sx, s)
    shape, color, _ = PIECES[game.next_kind]
    for cx, cy in shape:
        scr.addstr(oy + 6 + cy, sx + cx * 2, "██", curses.color_pair(pair[color]))

    help_ = ["W/↑ 旋转  A/← 左  D/→ 右", "S/↓ 下落  空格 落底",
             "P 暂停  R 重来  Q 退出"]
    for i, s in enumerate(help_):
        scr.addstr(oy + 10 + i, sx, s)

    if sink is None:
        led = "LED: 离线"
    elif sink.error:
        led = f"LED: 连接失败 {sink.error}"
    else:
        led = f"LED: {sink.api}"
    scr.addstr(oy + 14, sx, led[:40])
    if game.paused:
        scr.addstr(oy + 16, sx, "== 暂停 ==", curses.A_BOLD)
    if game.over:
        scr.addstr(oy + 16, sx, "== 游戏结束, R 重来 ==", curses.A_BOLD)
    scr.refresh()


def main(scr, args) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    for i, k in enumerate(PIECES):
        curses.init_pair(i + 1, PIECES[k][2], -1)
    curses.init_pair(len(PIECES) + 1, curses.COLOR_BLACK if curses.COLORS < 16 else 8, -1)
    scr.keypad(True)
    scr.timeout(30)

    sink = None if args.offline else LedSink(args.api, args.transpose, args.flip_x, args.flip_y)
    game = Tetris()
    last_fall = time.time()
    last_frame = None
    try:
        while True:
            key = scr.getch()
            if key in (ord("q"), ord("Q")):
                break
            if key in (ord("r"), ord("R")):
                game.reset()
            elif key in (ord("p"), ord("P")) and not game.over:
                game.paused = not game.paused
            elif not game.over and not game.paused:
                if key in KEYS_LEFT:
                    game.move(-1, 0)
                elif key in KEYS_RIGHT:
                    game.move(1, 0)
                elif key in KEYS_DOWN:
                    if game.move(0, 1):
                        game.score += 1
                    last_fall = time.time()
                elif key in KEYS_ROT:
                    game.rotate()
                elif key == ord(" "):
                    game.hard_drop()
                    last_fall = time.time()

            if not game.over and not game.paused and time.time() - last_fall >= game.gravity:
                game.step()
                last_fall = time.time()

            frame = game.frame()
            if frame != last_frame and sink:
                sink.show(frame)
            last_frame = frame
            try:
                draw(scr, game, frame, sink)
            except curses.error:
                scr.erase()
                scr.addstr(0, 0, "终端太小, 需要至少 90x23"[: max(1, curses.COLS - 1)])
                scr.refresh()
    finally:
        if sink:
            sink.close()


def cli() -> None:
    ap = argparse.ArgumentParser(description="20x20 LED 窗帘俄罗斯方块")
    ap.add_argument("--api", default="http://10.78.72.1:8000", help="Surplife API 地址")
    ap.add_argument("--offline", action="store_true", help="不连接灯, 只在终端玩")
    ap.add_argument("--calib", action="store_true", help="显示方向校准图案后退出")
    ap.add_argument("--no-transpose", dest="transpose", action="store_false",
                    help="不交换 x/y (默认交换: 摄像头 API 按行优先写掩码, 灯面实测为列优先)")
    ap.add_argument("--flip-x", action="store_true", help="左右镜像")
    ap.add_argument("--flip-y", action="store_true", help="上下镜像")
    args = ap.parse_args()

    if args.calib:
        sink = LedSink(args.api, args.transpose, args.flip_x, args.flip_y)
        sink._send(calib_frame())
        print("已发送: 左上角红, 顶行绿, 左列蓝, 底两行灰。方向不对就加 --no-transpose/--flip-x/--flip-y")
        return
    curses.wrapper(main, args)


if __name__ == "__main__":
    cli()

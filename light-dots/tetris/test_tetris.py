import unittest
import tetris as T


class TetrisTest(unittest.TestCase):
    def test_reserved_rows_grey(self):
        f = T.Tetris().frame()
        self.assertEqual(len(f), 20)
        for y in (18, 19):
            self.assertTrue(all(c == T.GREY for c in f[y]))

    def test_piece_stops_above_reserved(self):
        g = T.Tetris()
        g.hard_drop()
        self.assertTrue(any(g.board[T.FIELD_H - 1]))

    def test_line_clear(self):
        g = T.Tetris()
        g.board[T.FIELD_H - 1] = ["I"] * 20
        g.board[T.FIELD_H - 1][0] = None
        g.piece = T.Piece("I")
        g.piece.cells = [(0, 0), (0, 1), (0, 2), (0, 3)]
        g.piece.x = 0
        g.hard_drop()
        self.assertEqual(g.lines, 1)
        self.assertEqual(g.board[T.FIELD_H - 1].count(None), 19)

    def test_walls(self):
        g = T.Tetris()
        for _ in range(30):
            g.move(-1, 0)
        self.assertTrue(min(x for x, _ in g.piece.blocks()) == 0)

    def test_rotate_cycle(self):
        p = T.Piece("T")
        c = p.cells
        for _ in range(4):
            p.cells = p.rotated()
        self.assertEqual(sorted(p.cells), sorted(c))


if __name__ == "__main__":
    unittest.main()

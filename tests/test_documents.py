import unittest

from app.documents import split_posts


class DocumentTests(unittest.TestCase):
    def test_split_ignores_title_only_chunk(self):
        text = "# 只有标题\n\n---\n\n# 完整文章\n" + ("这是完整正文。" * 20)
        posts = split_posts(text)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][0], "完整文章")


if __name__ == "__main__":
    unittest.main()

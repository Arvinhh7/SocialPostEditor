import unittest

from app.retrieval import Retriever, char_ngrams


class RetrievalTests(unittest.TestCase):
    def test_char_ngrams_support_chinese(self):
        grams = char_ngrams("AI投毒风险")
        self.assertIn("投毒", grams)
        self.assertIn("投毒风", grams)

    def test_relevant_post_ranks_first(self):
        posts = [
            {"id": 1, "title": "体育", "text": "世界杯品牌赞助活动", "platform": "LinkedIn", "language": "zh-CN", "content_type": "活动", "topic": "体育", "tone": "热情", "authenticity": 5, "published_at": None},
            {"id": 2, "title": "风险", "text": "隐藏文字会造成 AI 投毒和品牌治理风险", "platform": "LinkedIn", "language": "zh-CN", "content_type": "风险教育", "topic": "AI投毒", "tone": "克制", "authenticity": 5, "published_at": None},
        ]
        hits = Retriever("hybrid").search(posts, {"topic": "隐藏文字的 AI 投毒风险", "platform": "LinkedIn", "language": "zh-CN", "format": "风险教育", "tone": "克制"}, 2)
        self.assertEqual(hits[0].post_id, 2)
        self.assertGreater(hits[0].final_score, hits[1].final_score)


if __name__ == "__main__":
    unittest.main()


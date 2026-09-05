import asyncio
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import UploadFile

from app import main as api
from app.db import Database
from app.ingestion import infer_post_metadata, infer_published_at, text_fingerprint
from app.models import PostMetadataUpdate


class MetadataInferenceTests(unittest.TestCase):
    def test_infers_common_metadata_without_a_model_call(self):
        metadata, warnings = infer_post_metadata(
            filename="2026-08-20_小红书_RAG复盘.md",
            title="第一次做 RAG 的复盘",
            text="我复盘了这次测试数据，也记录了踩坑过程。" * 10,
        )

        self.assertEqual(metadata["platform"], "小红书")
        self.assertEqual(metadata["language"], "zh-CN")
        self.assertEqual(metadata["content_type"], "项目复盘")
        self.assertEqual(metadata["topic"], "第一次做 RAG 的复盘")
        self.assertEqual(metadata["published_at"], "2026-08-20")
        self.assertIn("第一人称", metadata["tone"])
        self.assertEqual(warnings, [])

    def test_fingerprint_ignores_whitespace_and_case(self):
        self.assertEqual(text_fingerprint("RAG 项目\n复盘"), text_fingerprint("rag项目 复盘"))

    def test_invalid_filename_date_is_not_stored(self):
        self.assertIsNone(infer_published_at("2026-02-31_文章.md"))


class BulkUploadApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = api.db
        api.db = Database(Path(self.temp.name) / "test.db")
        api.db.init()

    def tearDown(self):
        api.db = self.original_db
        self.temp.cleanup()

    @staticmethod
    def upload(filename: str, text: str) -> UploadFile:
        return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename=filename)

    def test_bulk_upload_auto_labels_and_skips_duplicates(self):
        body = "我记录了这次 RAG 项目的真实测试过程和数据判断。" * 12
        files = [
            self.upload("2026-08-20_小红书.md", f"# RAG 项目复盘\n{body}"),
            self.upload("duplicate.md", f"# 重复标题\n{body}"),
        ]

        result = asyncio.run(api.bulk_upload_posts(files, 2))

        self.assertEqual(result["summary"]["files_received"], 2)
        self.assertEqual(result["summary"]["posts_created"], 1)
        self.assertEqual(result["summary"]["duplicates_skipped"], 1)
        created = result["created"][0]["post"]
        self.assertEqual(created["platform"], "小红书")
        self.assertEqual(created["language"], "zh-CN")
        self.assertEqual(created["authenticity"], 4)

    def test_imported_metadata_can_be_corrected(self):
        body = "这是一篇用于测试批量导入和元数据纠正能力的完整历史文章。" * 10
        result = asyncio.run(api.bulk_upload_posts([self.upload("article.txt", body)], 2))
        post_id = result["created"][0]["post"]["id"]

        corrected = api.update_post_metadata(
            post_id,
            PostMetadataUpdate(platform="LinkedIn", topic="人工确认的主题", authenticity=5),
        )

        self.assertEqual(corrected["platform"], "LinkedIn")
        self.assertEqual(corrected["topic"], "人工确认的主题")
        self.assertEqual(corrected["authenticity"], 5)

    def test_single_upload_uses_same_inference_and_deduplication(self):
        body = "我记录了单篇文章导入后自动识别平台和主题的过程。" * 12
        first = asyncio.run(api.upload_posts(self.upload("2026-08-20_小红书.md", body), 2))
        duplicate = asyncio.run(api.upload_posts(self.upload("duplicate.md", body), 2))

        self.assertEqual(first["posts"][0]["platform"], "小红书")
        self.assertEqual(duplicate["count"], 0)
        self.assertEqual(duplicate["skipped"][0]["reason"], "内容重复")

    def test_add_posts_rolls_back_the_whole_batch(self):
        with self.assertRaises(sqlite3.IntegrityError):
            api.db.add_posts(
                [
                    {"role_id": 2, "title": "有效", "text": "有效正文" * 20},
                    {"role_id": 99999, "title": "无效角色", "text": "无效正文" * 20},
                ]
            )
        self.assertEqual(api.db.list_posts(2), [])



if __name__ == "__main__":
    unittest.main()

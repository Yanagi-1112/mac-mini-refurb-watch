import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock
from urllib.error import URLError

import check


class MockResponse:
    def __init__(self, body):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


def air_tile(part="FDH74J/A", title="13インチMacBook Air"):
    return {
        "partNumber": part,
        "productDetailsUrl": "/jp/shop/product/fdh74j/a?fnode=example",
        "title": title,
        "price": {"currentPrice": {"amount": "123,800円（税込）"}},
        "filters": {"dimensions": {"refurbClearModel": "macbookair"}},
    }


def mini_tile(part="TEST1J/A"):
    return {
        "partNumber": part,
        "productDetailsUrl": "/jp/shop/product/test1j/a?fnode=example",
        "title": "Mac mini Apple M4チップ",
        "price": {"currentPrice": {"amount": "84,800円（税込）"}},
        "filters": {"dimensions": {"refurbClearModel": "macmini"}},
    }


class KeyboardDetectionTests(unittest.TestCase):
    def test_tile_us_label_uses_fast_path_without_detail_request(self):
        tile = air_tile(title="13インチMacBook Air - USキーボード")
        kb = {}

        with mock.patch("check.fetch_product_page") as fetch_product_page:
            result = check.is_macbook_air_us(tile, kb)

        self.assertTrue(result)
        self.assertTrue(kb[tile["partNumber"]])
        fetch_product_page.assert_not_called()

    def test_jis_detail_is_not_us_and_is_cached(self):
        tile = air_tile()
        html = "<html>ファンクションキー（フルハイト）を含むJIS配列準拠キーボード</html>"

        with mock.patch("check.time.sleep"), mock.patch(
            "check.urllib.request.urlopen", return_value=MockResponse(html)
        ) as urlopen:
            result = check.is_macbook_air_us(tile, kb := {})

        self.assertFalse(result)
        self.assertIs(kb[tile["partNumber"]], False)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://www.apple.com/jp/shop/product/fdh74j/a")
        self.assertNotIn("?", request.full_url)
        self.assertEqual(request.get_header("User-agent"), check.UA)

    def test_us_detail_is_us_and_is_cached(self):
        tile = air_tile()
        html = "<html>US配列準拠キーボードを搭載</html>"

        with mock.patch("check.time.sleep"), mock.patch(
            "check.urllib.request.urlopen", return_value=MockResponse(html)
        ):
            result = check.is_macbook_air_us(tile, kb := {})

        self.assertTrue(result)
        self.assertIs(kb[tile["partNumber"]], True)

    def test_cached_part_does_not_request_detail(self):
        tile = air_tile()

        with mock.patch("check.fetch_product_page") as fetch_product_page:
            result = check.is_macbook_air_us(tile, {tile["partNumber"]: False})

        self.assertFalse(result)
        fetch_product_page.assert_not_called()

    def test_detail_request_failure_excludes_item_without_caching(self):
        tile = air_tile()
        kb = {}
        stderr = io.StringIO()

        with mock.patch("check.time.sleep"), mock.patch(
            "check.urllib.request.urlopen", side_effect=URLError("offline")
        ):
            with redirect_stderr(stderr):
                items = check.extract_items([tile], check.is_macbook_air_us, kb)

        self.assertEqual(items, {})
        self.assertNotIn(tile["partNumber"], kb)
        self.assertTrue(stderr.getvalue())

    def test_detail_without_keyboard_word_excludes_item_without_caching(self):
        tile = air_tile()
        kb = {}
        stderr = io.StringIO()
        html = "<html>MacBook Airの製品仕様</html>"

        with mock.patch("check.time.sleep"), mock.patch(
            "check.urllib.request.urlopen", return_value=MockResponse(html)
        ):
            with redirect_stderr(stderr):
                items = check.extract_items([tile], check.is_macbook_air_us, kb)

        self.assertEqual(items, {})
        self.assertNotIn(tile["partNumber"], kb)
        self.assertTrue(stderr.getvalue())

    def test_multiple_detail_requests_sleep_once_between_requests(self):
        tiles = [air_tile("FIRSTJ/A"), air_tile("SECONDJ/A")]
        responses = [
            MockResponse("<html>JIS配列準拠キーボード</html>"),
            MockResponse("<html>US配列準拠キーボード</html>"),
        ]

        with mock.patch("check.time.sleep") as sleep, mock.patch(
            "check.urllib.request.urlopen", side_effect=responses
        ):
            items = check.extract_items(tiles, check.is_macbook_air_us, {})

        sleep.assert_called_once_with(1)
        self.assertEqual(set(items), {"SECONDJ/A"})


class StateTests(unittest.TestCase):
    def test_load_new_state_keeps_items_and_keyboard_cache(self):
        state = {
            "items": {"FDH74J/A": {"title": "MacBook Air", "price": "1円", "url": "url"}},
            "kb": {"FDH74J/A": True},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = os.path.join(temp_dir, "state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)

            with mock.patch.object(check, "STATE_FILE", state_file):
                loaded = check.load_state()

        self.assertEqual(loaded, state)

    def test_load_legacy_state_and_main_does_not_renotify_existing_item(self):
        tile = mini_tile()
        old_items = {
            tile["partNumber"]: {
                "title": tile["title"],
                "price": tile["price"]["currentPrice"]["amount"],
                "url": "https://www.apple.com/jp/shop/product/test1j/a",
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = os.path.join(temp_dir, "state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(old_items, f, ensure_ascii=False)

            with mock.patch.object(check, "STATE_FILE", state_file):
                self.assertEqual(check.load_state(), {"items": old_items, "kb": {}})
                with mock.patch("check.fetch_tiles", side_effect=[[tile], []]):
                    with mock.patch("check.notify_discord") as notify:
                        check.main()

                notify.assert_not_called()
                with open(state_file, encoding="utf-8") as f:
                    saved = json.load(f)

        self.assertEqual(saved["items"], old_items)
        self.assertEqual(saved["kb"], {})


if __name__ == "__main__":
    unittest.main()

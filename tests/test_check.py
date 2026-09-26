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
        "filters": {"dimensions": {"refurbClearModel": "macbookair", "dimensionScreensize": "13inch", "tsMemorySize": "24gb"}},
    }


def pro_tile(part="TEST2J/A", title="13インチMacBook Pro"):
    return {
        "partNumber": part,
        "productDetailsUrl": "/jp/shop/product/test2j/a?fnode=example",
        "title": title,
        "price": {"currentPrice": {"amount": "248,800円（税込）"}},
        "filters": {"dimensions": {"refurbClearModel": "macbookpro", "dimensionScreensize": "13inch", "tsMemorySize": "24gb"}},
    }


def mini_tile(part="TEST1J/A"):
    # Mac mini監視は停止済み。マッチしないことの確認用に残している
    return {
        "partNumber": part,
        "productDetailsUrl": "/jp/shop/product/test1j/a?fnode=example",
        "title": "Mac mini Apple M4チップ",
        "price": {"currentPrice": {"amount": "84,800円（税込）"}},
        "filters": {"dimensions": {"refurbClearModel": "macmini"}},
    }


class KeyboardDetectionTests(unittest.TestCase):
    def test_model_filter_uses_dimension_and_falls_back_to_title(self):
        tile = air_tile(title="MacBook Air - USキーボード")
        self.assertTrue(check.matches_model(tile, "macbookair"))
        self.assertFalse(check.matches_model(tile, "macbookpro"))
        tile.pop("filters")
        self.assertTrue(check.matches_model(tile, "macbookair"))
        self.assertFalse(check.matches_model(tile, "macbookpro"))

    def test_jis_labels_are_recognized(self):
        for label in ("JISキーボード", "ＪＩＳ配列準拠キーボード", "日本語キーボード"):
            with self.subTest(label=label), mock.patch("check.fetch_product_page") as fetch:
                self.assertTrue(check.is_macbook_jis(air_tile(title=label), {}))
                fetch.assert_not_called()

    def test_unknown_and_conflicting_layouts_are_not_jis(self):
        for html in ("バックライトキーボード", "ドイツ語キーボード", "USキーボード / JISキーボード"):
            with self.subTest(html=html), mock.patch("check.fetch_product_page", return_value=html):
                self.assertFalse(check.is_macbook_jis(air_tile(), {}))

    def test_air_us_and_jis_share_detail_request_even_on_failure(self):
        for html in ("JIS配列準拠キーボード", "配列不明のキーボード"):
            with self.subTest(html=html), mock.patch("check.fetch_product_page", return_value=html) as fetch:
                kb = {}
                check.extract_items([air_tile()], check.is_macbook_us, kb)
                check.extract_items([air_tile()], check.is_macbook_jis, kb)
                fetch.assert_called_once()

    def test_tile_us_label_uses_fast_path_without_detail_request(self):
        tile = air_tile(title="13インチMacBook Air - USキーボード")
        kb = {}

        with mock.patch("check.fetch_product_page") as fetch_product_page:
            result = check.is_macbook_us(tile, kb)

        self.assertTrue(result)
        self.assertEqual(kb[tile["partNumber"]], "us")
        fetch_product_page.assert_not_called()

    def test_jis_detail_is_not_us_and_is_cached(self):
        tile = air_tile()
        html = "<html>ファンクションキー（フルハイト）を含むJIS配列準拠キーボード</html>"

        with mock.patch("check.time.sleep"), mock.patch(
            "check.urllib.request.urlopen", return_value=MockResponse(html)
        ) as urlopen:
            result = check.is_macbook_us(tile, kb := {})

        self.assertFalse(result)
        self.assertEqual(kb[tile["partNumber"]], "jis")
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
            result = check.is_macbook_us(tile, kb := {})

        self.assertTrue(result)
        self.assertEqual(kb[tile["partNumber"]], "us")

    def test_cached_part_does_not_request_detail(self):
        tile = air_tile()

        with mock.patch("check.fetch_product_page") as fetch_product_page:
            result = check.is_macbook_us(tile, {tile["partNumber"]: "jis"})

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
                items = check.extract_items([tile], check.is_macbook_us, kb)

        self.assertEqual(items, {})
        self.assertIsNone(kb[tile["partNumber"]])
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
                items = check.extract_items([tile], check.is_macbook_us, kb)

        self.assertEqual(items, {})
        self.assertIsNone(kb[tile["partNumber"]])
        self.assertTrue(stderr.getvalue())

    def test_pro_us_detail_is_us_and_is_cached(self):
        tile = pro_tile()
        html = "<html>US配列準拠キーボードを搭載</html>"

        with mock.patch("check.time.sleep"), mock.patch(
            "check.urllib.request.urlopen", return_value=MockResponse(html)
        ):
            result = check.is_macbook_us(tile, kb := {})

        self.assertTrue(result)
        self.assertEqual(kb[tile["partNumber"]], "us")

    def test_pro_tile_us_label_uses_fast_path_without_detail_request(self):
        tile = pro_tile(title="14インチMacBook Pro - USキーボード")

        with mock.patch("check.fetch_product_page") as fetch_product_page:
            result = check.is_macbook_us(tile, {})

        self.assertTrue(result)
        fetch_product_page.assert_not_called()

    def test_mac_mini_does_not_match_and_skips_detail_request(self):
        tile = mini_tile()

        with mock.patch("check.fetch_product_page") as fetch_product_page:
            result = check.is_macbook_us(tile, {})

        self.assertFalse(result)
        fetch_product_page.assert_not_called()

    def test_multiple_detail_requests_sleep_once_between_requests(self):
        tiles = [air_tile("FIRSTJ/A"), air_tile("SECONDJ/A")]
        responses = [
            MockResponse("<html>JIS配列準拠キーボード</html>"),
            MockResponse("<html>US配列準拠キーボード</html>"),
        ]

        with mock.patch("check.time.sleep") as sleep, mock.patch(
            "check.urllib.request.urlopen", side_effect=responses
        ):
            items = check.extract_items(tiles, check.is_macbook_us, {})

        sleep.assert_called_once_with(1)
        self.assertEqual(set(items), {"SECONDJ/A"})


class SpecificationTests(unittest.TestCase):
    def test_only_13_inch_with_at_least_24gb_matches(self):
        for screen in ("13inch", "13.3inch", "13.6inch", "14inch", "15inch", "16inch", None):
            for memory in ("8gb", "16gb", "24gb", "32gb", "64gb", None, "unknown"):
                tile = air_tile()
                tile["filters"]["dimensions"].update(dimensionScreensize=screen, tsMemorySize=memory)
                expected = screen in ("13inch", "13.3inch", "13.6inch") and memory in ("24gb", "32gb", "64gb")
                with self.subTest(screen=screen, memory=memory):
                    self.assertEqual(check.matches_specs(tile), expected)

    def test_rejected_specs_never_fetch_detail_or_notify_for_air_and_pro(self):
        tiles = []
        for factory in (air_tile, pro_tile):
            for screen, memory in (("13inch", "16gb"), ("14inch", "24gb"), ("15inch", "32gb"), ("16inch", "64gb"), ("13inch", None)):
                tile = factory()
                tile["filters"]["dimensions"].update(dimensionScreensize=screen, tsMemorySize=memory)
                tiles.append(tile)
        with mock.patch("check.fetch_tiles", return_value=tiles), mock.patch("check.load_state", return_value={"items": {}, "kb": {}}):
            with mock.patch("check.fetch_product_page") as detail, mock.patch("check.notify_discord") as notify, mock.patch("check.save_state"):
                check.main()
                detail.assert_not_called()
                notify.assert_not_called()


class StateTests(unittest.TestCase):
    def test_legacy_boolean_cache_is_migrated_without_assuming_false_is_jis(self):
        state = {"items": {}, "kb": {"US": True, "NON_US": False, "JIS": "jis"}}
        with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(state))):
            self.assertEqual(check.load_state()["kb"], {"US": "us", "JIS": "jis"})

    def test_failed_detection_is_not_persisted_and_retries_next_run(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(check, "STATE_FILE", os.path.join(tmp, "state.json")):
            check.save_state({"items": {}, "kb": {"FDH74J/A": None}})
            kb = check.load_state()["kb"]
            self.assertEqual(kb, {})
            with mock.patch("check.fetch_product_page", return_value="JISキーボード") as fetch:
                self.assertTrue(check.is_macbook_jis(air_tile(), kb))
                fetch.assert_called_once()

    def test_mixed_catalog_notifies_only_air_us_jis_and_pro_us_once(self):
        air_us = air_tile("AIR_US", "MacBook Air - USキーボード")
        air_jis = air_tile("AIR_JIS", "MacBook Air - JISキーボード")
        pro_us = pro_tile("PRO_US", "MacBook Pro - USキーボード")
        pro_jis = pro_tile("PRO_JIS", "MacBook Pro - JISキーボード")
        tiles = [air_us, air_jis, pro_us, pro_jis, mini_tile()]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(check, "STATE_FILE", os.path.join(tmp, "state.json")):
            with mock.patch("check.fetch_tiles", return_value=tiles) as fetch, mock.patch("check.notify_discord") as notify:
                check.main()
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual([set(c.args[0]) for c in notify.call_args_list], [{"AIR_US"}, {"AIR_JIS"}, {"PRO_US"}])
                self.assertIn("JIS", notify.call_args_list[1].args[1])
                self.assertEqual(set(check.load_state()["items"]), {"AIR_US", "AIR_JIS", "PRO_US"})
                notify.reset_mock()
                check.main()
                notify.assert_not_called()
                # 在庫が消えてから戻った商品は再入荷通知する。
                fetch.return_value = [air_us, pro_us]
                check.main()
                notify.assert_not_called()
                fetch.return_value = tiles
                check.main()
                notify.assert_called_once()
                self.assertEqual(set(notify.call_args.args[0]), {"AIR_JIS"})

    def test_load_new_state_keeps_items_and_keyboard_cache(self):
        state = {
            "items": {"FDH74J/A": {"title": "MacBook Air", "price": "1円", "url": "url"}},
            "kb": {"FDH74J/A": "us"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = os.path.join(temp_dir, "state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)

            with mock.patch.object(check, "STATE_FILE", state_file):
                loaded = check.load_state()

        self.assertEqual(loaded, state)

    def test_load_legacy_state_and_main_does_not_renotify_existing_item(self):
        tile = air_tile(title="13インチMacBook Air - USキーボード")
        old_items = {
            tile["partNumber"]: {
                "title": tile["title"],
                "price": tile["price"]["currentPrice"]["amount"],
                "url": "https://www.apple.com/jp/shop/product/fdh74j/a",
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
        # USラベル付きタイルはfast pathでkbにキャッシュされる
        self.assertEqual(saved["kb"], {tile["partNumber"]: "us"})

    def test_mac_mini_in_old_state_is_dropped_without_notification(self):
        # 監視停止したMac miniが旧stateに残っていても、通知されず次回保存で消えること
        mini = mini_tile()
        old_state = {
            "items": {
                mini["partNumber"]: {
                    "title": mini["title"],
                    "price": mini["price"]["currentPrice"]["amount"],
                    "url": "https://www.apple.com/jp/shop/product/test1j/a",
                }
            },
            "kb": {},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = os.path.join(temp_dir, "state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(old_state, f, ensure_ascii=False)

            with mock.patch.object(check, "STATE_FILE", state_file):
                with mock.patch("check.fetch_tiles", side_effect=[[], []]):
                    with mock.patch("check.notify_discord") as notify:
                        check.main()

                notify.assert_not_called()
                with open(state_file, encoding="utf-8") as f:
                    saved = json.load(f)

        self.assertEqual(saved["items"], {})


if __name__ == "__main__":
    unittest.main()

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
        "title": title + " Apple M5チップ",
        "price": {"currentPrice": {"amount": "123,800円（税込）"}},
        "filters": {"dimensions": {"refurbClearModel": "macbookair", "dimensionScreensize": "13inch", "tsMemorySize": "32gb", "dimensionCapacity": "1tb"}},
    }


def pro_tile(part="TEST2J/A", title="14インチMacBook Pro"):
    return {
        "partNumber": part,
        "productDetailsUrl": "/jp/shop/product/test2j/a?fnode=example",
        "title": title + " Apple M5チップ",
        "price": {"currentPrice": {"amount": "248,800円（税込）"}},
        "filters": {"dimensions": {"refurbClearModel": "macbookpro", "dimensionScreensize": "14inch", "tsMemorySize": "32gb", "dimensionCapacity": "1tb"}},
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


def air_with(memory="32gb", storage="1tb", screen="13inch", chip="M5"):
    """購入構成の境界テスト用。メモリ・ストレージ・画面・チップだけ差し替えたAirタイルを作る。"""
    tile = air_tile()
    tile["title"] = f"13インチMacBook Air Apple {chip}チップ"
    dims = tile["filters"]["dimensions"]
    dims.update(dimensionScreensize=screen, tsMemorySize=memory, dimensionCapacity=storage)
    if storage is None:
        dims.pop("dimensionCapacity")
    return tile


class SpecificationTests(unittest.TestCase):
    def test_target_configuration_constants(self):
        # 購入構成（13インチAir・32GB・1TB）を決めた値。変えるときはREADMEも直すこと
        self.assertEqual(check.TARGET_MEMORY_GB, 32)
        self.assertEqual(check.TARGET_STORAGE, "1tb")

    def test_air_m5_32gb_1tb_matches(self):
        self.assertTrue(check.matches_specs(air_with()))
        for screen in ("13inch", "13.3inch", "13.6inch"):
            with self.subTest(screen=screen):
                self.assertTrue(check.matches_specs(air_with(screen=screen)))

    def test_memory_must_be_exactly_32gb(self):
        for memory in ("8gb", "16gb", "24gb", "64gb", None, "unknown"):
            with self.subTest(memory=memory):
                self.assertFalse(check.matches_specs(air_with(memory=memory)))

    def test_storage_must_be_exactly_1tb(self):
        # 512GB・2TBは対象外。値が無い・不明な場合も対象外（推測しない）
        for storage in ("256gb", "512gb", "2tb", "4tb", None, "", "unknown"):
            with self.subTest(storage=storage):
                self.assertFalse(check.matches_specs(air_with(storage=storage)))

    def test_only_13_inch_air_screen_matches(self):
        for screen in ("14inch", "14.2inch", "15inch", "15.3inch", "16inch", None):
            with self.subTest(screen=screen):
                self.assertFalse(check.matches_specs(air_with(screen=screen)))

    def test_pro_is_never_matched_even_with_target_configuration(self):
        # 14インチProは2026-11-17に監視停止。32GB/1TBでも通知対象にしない
        tile = pro_tile()
        self.assertEqual(tile["filters"]["dimensions"]["tsMemorySize"], "32gb")
        self.assertEqual(tile["filters"]["dimensions"]["dimensionCapacity"], "1tb")
        self.assertFalse(check.matches_specs(tile))
        for screen in ("13inch", "14inch", "14.2inch", "16inch"):
            tile["filters"]["dimensions"]["dimensionScreensize"] = screen
            with self.subTest(screen=screen):
                self.assertFalse(check.matches_specs(tile))

    def test_m5_or_later_including_future_generations(self):
        for chip, expected in (("M1", False), ("M4", False), ("M4 Max", False), ("M5", True), ("M5 Pro", True), ("M5 Max", True), ("M6", True), ("M10", True), ("Intel", False), ("", False)):
            with self.subTest(chip=chip):
                self.assertEqual(check.matches_specs(air_with(chip=chip)), expected)

    def test_m4_32gb_1tb_is_rejected_and_m6_air_is_accepted(self):
        self.assertFalse(check.matches_specs(air_with(chip="M4")))
        self.assertTrue(check.matches_specs(air_with(chip="M6")))

    def test_rejected_specs_never_fetch_detail_or_notify(self):
        tiles = [
            air_with(memory="24gb"), air_with(memory="16gb"),
            air_with(storage="512gb"), air_with(storage="2tb"), air_with(storage=None),
            air_with(screen="15inch"), air_with(chip="M4"),
            pro_tile(), pro_tile("PRO2"),
        ]
        with mock.patch("check.fetch_tiles", return_value=tiles), mock.patch("check.load_state", return_value={"items": {}, "kb": {}}):
            with mock.patch("check.fetch_product_page") as detail, mock.patch("check.notify_discord") as notify, mock.patch("check.save_state"):
                check.main()
                detail.assert_not_called()
                notify.assert_not_called()

    def test_watches_only_contain_air_us_and_jis(self):
        self.assertEqual([w["model"] for w in check.WATCHES], ["macbookair", "macbookair"])
        self.assertEqual([w["matches"] for w in check.WATCHES], [check.is_macbook_us, check.is_macbook_jis])
        for w in check.WATCHES:
            self.assertIn("32GB", w["header"])
            self.assertIn("1TB", w["header"])
            self.assertNotIn("Pro", w["header"])
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

    def test_mixed_catalog_notifies_air_us_jis_once_and_ignores_pro(self):
        air_us = air_tile("AIR_US", "MacBook Air - USキーボード")
        air_jis = air_tile("AIR_JIS", "MacBook Air - JISキーボード")
        pro_us = pro_tile("PRO_US", "MacBook Pro - USキーボード")
        pro_jis = pro_tile("PRO_JIS", "MacBook Pro - JISキーボード")
        tiles = [air_us, air_jis, pro_us, pro_jis, mini_tile()]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(check, "STATE_FILE", os.path.join(tmp, "state.json")):
            with mock.patch("check.fetch_tiles", return_value=tiles) as fetch, mock.patch("check.notify_discord") as notify:
                check.main()
                # 監視URLはAirページ1つだけ（Proページはもう取得しない）
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual([set(c.args[0]) for c in notify.call_args_list], [{"AIR_US"}, {"AIR_JIS"}])
                self.assertIn("JIS", notify.call_args_list[1].args[1])
                self.assertNotIn("MacBook Pro", notify.call_args_list[1].args[1])
                self.assertEqual(set(check.load_state()["items"]), {"AIR_US", "AIR_JIS"})
                notify.reset_mock()
                check.main()
                notify.assert_not_called()
                # 在庫が消えてから戻った商品は再入荷通知する。
                fetch.return_value = [air_us, pro_us]
                check.main()
                notify.assert_not_called()
                fetch.return_value = tiles
                check.main()
                self.assertEqual([set(c.args[0]) for c in notify.call_args_list], [{"AIR_JIS"}])

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

        # 既存商品は再通知せず、保存時に通知用の仕様（specs）だけが追加される
        self.assertEqual(
            {k: {f: v for f, v in item.items() if f != "specs"} for k, item in saved["items"].items()},
            old_items,
        )
        self.assertEqual(saved["items"][tile["partNumber"]]["specs"]["keyboard"], "US配列")
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

    def test_pro_and_non_target_air_in_old_state_are_dropped_without_notification(self):
        # 監視停止したPro（14インチ）や条件外のAir（24GB）が旧stateに残っていても、
        # 一覧に載り続けていて通知されず、次回保存で消えること。条件内のAirだけが残る
        pro = pro_tile("OLD_PRO", "MacBook Pro - USキーボード")
        air24 = air_with(memory="24gb")
        air24["partNumber"] = "OLD_AIR24"
        target = air_tile("TARGET_AIR", "MacBook Air - USキーボード")

        def old_item(tile):
            return {"title": tile["title"], "price": tile["price"]["currentPrice"]["amount"], "url": "https://www.apple.com/jp/shop/product/x"}

        old_state = {
            "items": {t["partNumber"]: old_item(t) for t in (pro, air24, target)},
            "kb": {"OLD_PRO": "us", "TARGET_AIR": "us"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = os.path.join(temp_dir, "state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(old_state, f, ensure_ascii=False)

            with mock.patch.object(check, "STATE_FILE", state_file):
                with mock.patch("check.fetch_tiles", return_value=[pro, air24, target]):
                    with mock.patch("check.notify_discord") as notify:
                        check.main()

                notify.assert_not_called()
                with open(state_file, encoding="utf-8") as f:
                    saved = json.load(f)

        self.assertEqual(set(saved["items"]), {"TARGET_AIR"})


if __name__ == "__main__":
    unittest.main()


class NotificationFormatTests(unittest.TestCase):
    """通知を開く前に出品内容（チップ・メモリ・ストレージ・配列）が分かるかを確認する。"""

    def pro_m5_pro_tile(self):
        return {
            "partNumber": "FGDN4J/A",
            "productDetailsUrl": "/jp/shop/product/fgdn4j/a?fnode=example",
            "title": "14インチMacBook Pro [整備済製品] 15コアCPUと16コアGPUを搭載したApple M5 Proチップ、Nano-textureディスプレイ - シルバー",
            "price": {"currentPrice": {"amount": "363,800円"}},
            "filters": {"dimensions": {"refurbClearModel": "macbookpro", "dimensionScreensize": "14inch", "tsMemorySize": "24gb", "dimensionCapacity": "1tb"}},
        }

    def test_specs_are_extracted_from_listing_tile(self):
        specs = check.describe_specs(self.pro_m5_pro_tile(), "jis")
        self.assertEqual(specs["model"], "MacBook Pro")
        self.assertEqual(specs["screen"], "14インチ")
        self.assertEqual(specs["chip"], "M5 Pro")
        self.assertEqual((specs["cpu_cores"], specs["gpu_cores"]), (15, 16))
        self.assertEqual((specs["memory"], specs["storage"]), ("24GB", "1TB"))
        self.assertEqual(specs["keyboard"], "JIS配列（日本語）")
        self.assertEqual(specs["color"], "シルバー")
        self.assertTrue(specs["nano_texture"])

    def test_plain_m5_and_m5_pro_are_distinguished(self):
        tile = pro_tile()
        tile["title"] = "14インチMacBook Pro [整備済製品] 10コアCPUと10コアGPUを搭載したApple M5 チップ - スペースブラック"
        self.assertEqual(check.describe_specs(tile, "us")["chip"], "M5")
        tile["title"] = "14インチMacBook Pro Apple M5Maxチップ"
        self.assertEqual(check.describe_specs(tile, "us")["chip"], "M5 Max")

    def test_embed_title_summarizes_specs_and_links_to_product(self):
        tile = self.pro_m5_pro_tile()
        items = check.extract_items([tile], check.is_macbook_jis, {"FGDN4J/A": "jis"})
        embed = check.item_embed(items["FGDN4J/A"])
        self.assertEqual(embed["title"], "14インチ MacBook Pro｜M5 Pro（15コアCPU・16コアGPU）｜メモリ24GB｜SSD 1TB｜JIS配列｜シルバー｜Nano-texture")
        self.assertEqual(embed["url"], "https://www.apple.com/jp/shop/product/fgdn4j/a")
        self.assertIn("363,800円", embed["description"])
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertEqual(fields["🧠 チップ"], "M5 Pro\n15コアCPU / 16コアGPU")
        self.assertEqual(fields["💾 メモリ（VRAM共用）"], "24GB")
        self.assertEqual(fields["🗄️ ストレージ"], "SSD 1TB")
        self.assertEqual(fields["⌨️ キーボード"], "JIS配列（日本語）")
        self.assertIn("Nano-texture", fields["🎨 カラー"])

    def test_missing_specs_are_shown_as_unknown_and_test_notification_still_works(self):
        tile = air_tile()  # 一覧JSONにストレージ容量もコア数も無いケース（通知文の「不明」表示の確認）
        tile["filters"]["dimensions"].pop("dimensionCapacity")
        embed = check.item_embed({"title": "x", "price": "1円", "url": "u", "specs": check.describe_specs(tile, "us")})
        self.assertEqual(embed["title"], "13インチ MacBook Air｜M5｜メモリ32GB｜SSD 不明｜US配列")
        legacy = check.item_embed({"title": "テスト", "price": "説明", "url": "u"})
        self.assertEqual(legacy, {"title": "テスト", "url": "u", "description": "**説明**", "color": 0x2ECC71})

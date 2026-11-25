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


def air_with(memory="32gb", storage="1tb", screen="13inch", chip="M5", part="AIR_X", kb="US"):
    """境界テスト用。メモリ・ストレージ・画面・チップ・配列だけ差し替えたAirタイルを作る。

    配列はタイトルに「USキーボード」等を入れて、詳細ページ取得なしで判定できるようにしている。
    """
    tile = air_tile(part)
    tile["title"] = f"{screen}MacBook Air Apple {chip}チップ - {kb}キーボード"
    dims = tile["filters"]["dimensions"]
    dims.update(dimensionScreensize=screen, tsMemorySize=memory, dimensionCapacity=storage)
    for key, value in (("tsMemorySize", memory), ("dimensionCapacity", storage)):
        if value is None:
            dims.pop(key)
    return tile


def pro_with(memory="16gb", storage="1tb", screen="14inch", chip="M5", part="PRO_X", kb="US"):
    """air_with のPro版（14インチMacBook Pro）。"""
    tile = pro_tile(part)
    tile["title"] = f"{screen}MacBook Pro Apple {chip}チップ - {kb}キーボード"
    dims = tile["filters"]["dimensions"]
    dims.update(dimensionScreensize=screen, tsMemorySize=memory, dimensionCapacity=storage)
    for key, value in (("tsMemorySize", memory), ("dimensionCapacity", storage)):
        if value is None:
            dims.pop(key)
    return tile


def run_main(tiles_by_url):
    """main() を実行し、(通知された [(ウォッチ見出し, {part}), ...], 取得したURL一覧, 詳細ページ取得回数) を返す。"""
    def fake_fetch_tiles(url):
        return tiles_by_url[url]

    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(check, "STATE_FILE", os.path.join(tmp, "state.json")):
        with mock.patch("check.fetch_tiles", side_effect=fake_fetch_tiles) as fetch, \
                mock.patch("check.fetch_product_page", return_value="") as detail, \
                mock.patch("check.notify_discord") as notify:
            check.main()
    notified = [(c.args[1], set(c.args[0])) for c in notify.call_args_list]
    return notified, [c.args[0] for c in fetch.call_args_list], detail.call_count


def watch_name_of(header):
    return next(w["name"] for w in check.WATCHES if w["header"] == header)


def notified_by_watch(tiles):
    """Air・Proの両ページに同じタイル群を返し、{ウォッチ名: {part}} を得る（機種違いは matches_model が除く）。"""
    notified, _, _ = run_main({check.AIR_URL: tiles, check.PRO_URL: tiles})
    return {watch_name_of(h): parts for h, parts in notified}


AIR_MAIN_US = "MacBook Air 本命 (USキーボード)"
AIR_MAIN_JIS = "MacBook Air 本命 (JISキーボード)"
AIR_32_US = "MacBook Air 32GB以上 (USキーボード)"
PRO_US = "MacBook Pro 32GB以上 (USキーボード)"
PRO_32_JIS = "MacBook Pro 32GB以上 (JISキーボード)"


class SpecificationTests(unittest.TestCase):
    def test_constants(self):
        # 本命構成（13インチAir・32GB・1TB）と32GB以上の下限。変えるときはREADMEも直すこと
        self.assertEqual(check.TARGET_MEMORY_GB, 32)
        self.assertEqual(check.TARGET_STORAGE, "1tb")
        self.assertEqual(check.MIN_MEMORY_GB, 32)

    def test_tile_facts_reads_screen_memory_storage_chip(self):
        facts = check.tile_facts(air_with(memory="24gb", storage="512gb", screen="13.6inch", chip="M5 Pro"))
        self.assertEqual(facts, {"screen": 13, "memory": 24, "storage": "512gb", "chip": 5})
        unknown = check.tile_facts(air_with(memory=None, storage=None, screen="unknown", chip=""))
        self.assertEqual(unknown, {"screen": None, "memory": None, "storage": None, "chip": None})

    def test_watches_are_the_five_expected_in_order(self):
        self.assertEqual(
            [(w["name"], w["model"], w["matches"]) for w in check.WATCHES],
            [
                (AIR_MAIN_US, "macbookair", check.is_macbook_us),
                (AIR_MAIN_JIS, "macbookair", check.is_macbook_jis),
                (AIR_32_US, "macbookair", check.is_macbook_us),
                (PRO_US, "macbookpro", check.is_macbook_us),
                (PRO_32_JIS, "macbookpro", check.is_macbook_jis),
            ],
        )
        self.assertEqual(
            [w["url"] for w in check.WATCHES],
            [check.AIR_URL] * 3 + [check.PRO_URL] * 2,
        )
        self.assertEqual(check.PRO_URL, "https://www.apple.com/jp/shop/refurbished/mac/macbook-pro")
        for w in check.WATCHES:
            self.assertTrue(callable(w["specs"]))
        self.assertTrue(check.WATCHES[0]["header"].startswith("⭐ **【本命】"))
        self.assertTrue(check.WATCHES[1]["header"].startswith("⭐ **【本命】"))
        self.assertIn("メモリ32GB以上・USキーボードの整備済MacBook Air", check.WATCHES[2]["header"])
        self.assertIn("14インチ・M5以降・メモリ32GB以上・USキーボードの整備済MacBook Pro", check.WATCHES[3]["header"])
        self.assertIn("メモリ32GB以上・JISキーボードの整備済MacBook Pro", check.WATCHES[4]["header"])

    def test_air_main_spec_is_exactly_32gb_1tb_13inch(self):
        self.assertTrue(check.specs_air_main(air_with()))
        for screen in ("13inch", "13.3inch", "13.6inch"):
            with self.subTest(screen=screen):
                self.assertTrue(check.specs_air_main(air_with(screen=screen)))
        for memory in ("16gb", "24gb", "64gb", None, "unknown"):
            with self.subTest(memory=memory):
                self.assertFalse(check.specs_air_main(air_with(memory=memory)))
        for storage in ("512gb", "2tb", None, "", "unknown"):
            with self.subTest(storage=storage):
                self.assertFalse(check.specs_air_main(air_with(storage=storage)))

    def test_air_min_memory_excludes_main_and_requires_known_memory(self):
        for memory, storage, expected in (
            ("24gb", "512gb", False), ("24gb", "1tb", False), ("24gb", None, False),  # 24GBは対象外
            ("32gb", "512gb", True), ("32gb", "2tb", True), ("32gb", None, True),  # 32GBでも1TB以外は「本命ではない」
            ("64gb", "1tb", True),
            ("32gb", "1tb", False),  # 本命はウォッチ1・2が担当
            ("16gb", "1tb", False), ("8gb", "512gb", False), (None, "1tb", False), ("unknown", "1tb", False),
        ):
            with self.subTest(memory=memory, storage=storage):
                self.assertEqual(check.specs_air_min_memory(air_with(memory=memory, storage=storage)), expected)

    def test_pro_specs(self):
        # ウォッチ4・5共通: 14インチProは32GB以上（メモリ不明は対象外）
        for memory, expected in (
            ("16gb", False), ("24gb", False), ("32gb", True), ("64gb", True), (None, False), ("unknown", False),
        ):
            with self.subTest(memory=memory):
                self.assertEqual(check.specs_pro14_min_memory(pro_with(memory=memory)), expected)

    def test_screen_size_limits(self):
        for screen, air, pro in (
            ("13inch", True, False), ("13.6inch", True, False), ("14inch", False, True), ("14.2inch", False, True),
            ("15inch", False, False), ("15.3inch", False, False), ("16inch", False, False), (None, False, False),
        ):
            with self.subTest(screen=screen):
                self.assertEqual(check.specs_air_main(air_with(screen=screen)), air)
                self.assertEqual(check.specs_air_min_memory(air_with(memory="32gb", storage="512gb", screen=screen)), air)
                self.assertEqual(check.specs_pro14_min_memory(pro_with(memory="32gb", screen=screen)), pro)

    def test_m5_or_later_including_future_generations(self):
        for chip, expected in (("M1", False), ("M4", False), ("M4 Max", False), ("M5", True), ("M5 Pro", True), ("M5 Max", True), ("M6", True), ("M10", True), ("Intel", False), ("", False)):
            with self.subTest(chip=chip):
                self.assertEqual(check.specs_air_main(air_with(chip=chip)), expected)
                self.assertEqual(check.specs_air_min_memory(air_with(memory="32gb", storage="512gb", chip=chip)), expected)
                self.assertEqual(check.specs_pro14_min_memory(pro_with(memory="32gb", chip=chip)), expected)

    def test_other_models_never_match(self):
        mini = mini_tile()
        mini["filters"]["dimensions"].update(dimensionScreensize="13inch", tsMemorySize="32gb", dimensionCapacity="1tb")
        # Proタイルは画面・メモリが合ってもAir系に、Airタイルは Pro系に合わない
        self.assertFalse(check.specs_air_main(pro_with(screen="13inch", memory="32gb")))
        self.assertFalse(check.specs_pro14_min_memory(air_with(screen="14inch", memory="32gb")))
        self.assertFalse(check.matches_specs(mini))

    def test_matches_specs_is_any_watch_condition(self):
        self.assertTrue(check.matches_specs(air_with()))
        self.assertTrue(check.matches_specs(air_with(memory="32gb", storage="512gb")))
        self.assertTrue(check.matches_specs(pro_with(memory="64gb")))
        self.assertFalse(check.matches_specs(air_with(memory="24gb", storage="512gb")))
        self.assertFalse(check.matches_specs(pro_with(memory="16gb")))
        self.assertFalse(check.matches_specs(pro_with(memory=None)))
        self.assertFalse(check.matches_specs(air_with(memory="16gb")))
        self.assertFalse(check.matches_specs(pro_with(screen="16inch")))


class WatchBoundaryTests(unittest.TestCase):
    """5ウォッチを通した通知の境界（どのウォッチで通知されるか／されないか）。"""

    def test_air_us_32gb_512gb_goes_to_watch3_only(self):
        self.assertEqual(notified_by_watch([air_with(memory="32gb", storage="512gb", part="A")]), {AIR_32_US: {"A"}})

    def test_air_us_main_goes_to_watch1_only_not_watch3(self):
        self.assertEqual(notified_by_watch([air_with(part="A")]), {AIR_MAIN_US: {"A"}})

    def test_air_jis_main_goes_to_watch2_only(self):
        self.assertEqual(notified_by_watch([air_with(kb="JIS", part="A")]), {AIR_MAIN_JIS: {"A"}})

    def test_air_jis_non_main_is_not_notified(self):
        self.assertEqual(notified_by_watch([air_with(memory="32gb", storage="512gb", kb="JIS")]), {})
        self.assertEqual(notified_by_watch([air_with(memory="24gb", kb="JIS")]), {})

    def test_air_us_24gb_and_16gb_are_not_notified(self):
        self.assertEqual(notified_by_watch([air_with(memory="24gb", storage="512gb"), air_with(memory="24gb", storage="1tb")]), {})
        self.assertEqual(notified_by_watch([air_with(memory="16gb")]), {})

    def test_pro_us_below_32gb_or_unknown_is_not_notified(self):
        for memory in ("16gb", "24gb", None):
            with self.subTest(memory=memory):
                self.assertEqual(notified_by_watch([pro_with(memory=memory)]), {})

    def test_pro_jis_below_32gb_is_not_notified(self):
        self.assertEqual(notified_by_watch([pro_with(memory="16gb", kb="JIS"), pro_with(memory="24gb", kb="JIS")]), {})

    def test_pro_us_64gb_goes_to_watch4_only(self):
        self.assertEqual(notified_by_watch([pro_with(memory="64gb", part="P")]), {PRO_US: {"P"}})

    def test_pro_jis_64gb_goes_to_watch5_only(self):
        self.assertEqual(notified_by_watch([pro_with(memory="64gb", kb="JIS", part="P")]), {PRO_32_JIS: {"P"}})

    def test_pro_us_32gb_goes_to_watch4_only(self):
        self.assertEqual(notified_by_watch([pro_with(memory="32gb", part="P")]), {PRO_US: {"P"}})

    def test_16inch_pro_15inch_air_and_m4_are_not_notified(self):
        tiles = [
            pro_with(memory="32gb", screen="16inch"), pro_with(memory="32gb", screen="16inch", kb="JIS"),
            air_with(screen="15inch"), air_with(screen="15inch", kb="JIS"),
            air_with(chip="M4"), air_with(memory="32gb", storage="512gb", chip="M4"), pro_with(chip="M4"), pro_with(memory="64gb", chip="M4", kb="JIS"),
            mini_tile(),
        ]
        self.assertEqual(notified_by_watch(tiles), {})

    def test_no_listing_is_notified_twice(self):
        # 全パターンを並べ、同じpartが複数のウォッチで通知されないこと
        tiles = [
            air_with(part="A_MAIN_US"), air_with(kb="JIS", part="A_MAIN_JIS"),
            air_with(memory="24gb", storage="512gb", part="A_24_US"), air_with(memory="32gb", storage="512gb", part="A_32_512_US"),
            air_with(memory="64gb", storage="2tb", part="A_64_US"),
            air_with(memory="32gb", storage="512gb", kb="JIS", part="A_32_512_JIS"),
            pro_with(memory="16gb", part="P_16_US"), pro_with(memory="24gb", part="P_24_US"), pro_with(memory="32gb", part="P_32_US"),
            pro_with(memory="64gb", kb="JIS", part="P_64_JIS"), pro_with(memory="24gb", kb="JIS", part="P_24_JIS"),
        ]
        result = notified_by_watch(tiles)
        self.assertEqual(result, {
            AIR_MAIN_US: {"A_MAIN_US"}, AIR_MAIN_JIS: {"A_MAIN_JIS"},
            AIR_32_US: {"A_32_512_US", "A_64_US"}, PRO_US: {"P_32_US"}, PRO_32_JIS: {"P_64_JIS"},
        })
        all_parts = [p for parts in result.values() for p in parts]
        self.assertEqual(len(all_parts), len(set(all_parts)))

    def test_rejected_specs_never_fetch_detail_or_notify(self):
        # スペック条件に合わないタイルは、配列判定（詳細ページ取得）に進まない。
        # 配列表記の無いタイトルにして、判定に進めば必ず詳細ページを取りに行く状況にしている
        def plain(tile):
            tile["title"] = tile["title"].rsplit(" - ", 1)[0]
            return tile

        tiles = [
            plain(air_with(memory="16gb")), plain(air_with(memory=None)), plain(air_with(screen="15inch")),
            plain(air_with(chip="M4")), plain(pro_with(screen="16inch")), plain(pro_with(chip="M4")),
            mini_tile(),
        ]
        notified, _, detail_calls = run_main({check.AIR_URL: tiles, check.PRO_URL: tiles})
        self.assertEqual(notified, [])
        self.assertEqual(detail_calls, 0)

    def test_matching_spec_without_keyboard_label_does_fetch_detail(self):
        # 対照実験: スペックが合えば（配列表記が無い場合）詳細ページを取りに行く
        tile = air_with(part="A")
        tile["title"] = tile["title"].rsplit(" - ", 1)[0]
        _, _, detail_calls = run_main({check.AIR_URL: [tile], check.PRO_URL: []})
        self.assertEqual(detail_calls, 1)

    def test_main_fetches_air_and_pro_pages_once_each(self):
        _, fetched, _ = run_main({check.AIR_URL: [], check.PRO_URL: []})
        self.assertEqual(sorted(fetched), sorted([check.AIR_URL, check.PRO_URL]))


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

    def test_mixed_catalog_notifies_each_listing_once_then_renotifies_on_restock(self):
        air_us = air_with(part="AIR_US")
        air_jis = air_with(kb="JIS", part="AIR_JIS")
        air_24 = air_with(memory="32gb", storage="512gb", part="AIR_24")
        pro_us = pro_with(memory="32gb", part="PRO_US")
        pro_jis_24 = pro_with(memory="64gb", kb="JIS", part="PRO_JIS24")
        pro_jis_16 = pro_with(memory="24gb", kb="JIS", part="PRO_JIS16")  # 通知対象外
        air_tiles = [air_us, air_jis, air_24, mini_tile()]
        pro_tiles = [pro_us, pro_jis_24, pro_jis_16]
        pages = {check.AIR_URL: air_tiles, check.PRO_URL: pro_tiles}
        expected_parts = [{"AIR_US"}, {"AIR_JIS"}, {"AIR_24"}, {"PRO_US"}, {"PRO_JIS24"}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(check, "STATE_FILE", os.path.join(tmp, "state.json")):
            with mock.patch("check.fetch_tiles", side_effect=lambda url: pages[url]) as fetch, mock.patch("check.notify_discord") as notify:
                check.main()
                self.assertEqual(fetch.call_count, 2)  # AirページとProページ
                self.assertEqual([set(c.args[0]) for c in notify.call_args_list], expected_parts)
                self.assertEqual([c.args[1] for c in notify.call_args_list], [w["header"] for w in check.WATCHES])
                self.assertEqual(set(check.load_state()["items"]), {"AIR_US", "AIR_JIS", "AIR_24", "PRO_US", "PRO_JIS24"})
                notify.reset_mock()
                check.main()
                notify.assert_not_called()
                # 在庫が消えてから戻った商品は再入荷通知する。
                pages[check.AIR_URL] = [air_us]
                pages[check.PRO_URL] = []
                check.main()
                notify.assert_not_called()
                pages[check.AIR_URL] = air_tiles
                pages[check.PRO_URL] = pro_tiles
                check.main()
                self.assertEqual([set(c.args[0]) for c in notify.call_args_list], expected_parts[1:])

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

    def test_out_of_scope_listings_in_old_state_are_dropped_without_notification(self):
        # 旧stateに残っている条件外の出品（16GB/24GBのAir・JIS Air・32GB未満のUS Pro・16インチPro・24GBのJIS Pro）は
        # 一覧に載り続けていても通知されず、次回保存で消える。条件内の出品だけが残る
        out_of_scope = [
            air_with(memory="16gb", part="OLD_AIR16"),
            air_with(memory="24gb", storage="512gb", part="OLD_AIR24_US"),
            air_with(memory="24gb", kb="JIS", part="OLD_AIR24_JIS"),
            pro_with(memory="16gb", part="OLD_PRO16_US"),
            pro_with(memory="24gb", part="OLD_PRO24_US"),
            pro_with(memory="32gb", screen="16inch", part="OLD_PRO16IN"),
            pro_with(memory="24gb", kb="JIS", part="OLD_PRO24_JIS"),
        ]
        in_scope = [air_with(part="TARGET_AIR"), pro_with(memory="32gb", part="TARGET_PRO")]

        def old_item(tile):
            return {"title": tile["title"], "price": tile["price"]["currentPrice"]["amount"], "url": "https://www.apple.com/jp/shop/product/x"}

        old_state = {
            "items": {t["partNumber"]: old_item(t) for t in out_of_scope + in_scope},
            "kb": {},
        }
        pages = {check.AIR_URL: [t for t in out_of_scope + in_scope if "MacBook Air" in t["title"]],
                 check.PRO_URL: [t for t in out_of_scope + in_scope if "MacBook Pro" in t["title"]]}

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = os.path.join(temp_dir, "state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(old_state, f, ensure_ascii=False)

            with mock.patch.object(check, "STATE_FILE", state_file):
                with mock.patch("check.fetch_tiles", side_effect=lambda url: pages[url]):
                    with mock.patch("check.notify_discord") as notify:
                        check.main()

                notify.assert_not_called()
                with open(state_file, encoding="utf-8") as f:
                    saved = json.load(f)

        self.assertEqual(set(saved["items"]), {"TARGET_AIR", "TARGET_PRO"})


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
        self.assertEqual(embed["title"], check.US_TITLE_PREFIX + "13インチ MacBook Air｜M5｜メモリ32GB｜SSD 不明｜US配列")
        legacy = check.item_embed({"title": "テスト", "price": "説明", "url": "u"})
        self.assertEqual(legacy, {"title": "テスト", "url": "u", "description": "**説明**", "color": 0x2ECC71})


class UsKeyboardAlertTests(unittest.TestCase):
    """USキーボードの出品は見逃さないよう、通知をド派手にする。JISは従来どおり。"""

    def item(self, layout):
        return {"title": "x", "price": "297,800円", "url": "u", "specs": check.describe_specs(air_tile(), layout)}

    def test_us_embed_is_red_with_prefix_and_alert(self):
        embed = check.item_embed(self.item("us"))
        self.assertEqual(embed["color"], check.US_ALERT_COLOR)
        self.assertTrue(embed["title"].startswith(check.US_TITLE_PREFIX))
        self.assertIn("USキーボードの出品です", embed["description"])
        self.assertIn("297,800円", embed["description"])
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertIn("US配列", fields["⌨️ キーボード"])
        self.assertIn("🇺🇸", fields["⌨️ キーボード"])

    def test_jis_embed_stays_normal(self):
        embed = check.item_embed(self.item("jis"))
        self.assertEqual(embed["color"], check.NORMAL_COLOR)
        self.assertFalse(embed["title"].startswith(check.US_TITLE_PREFIX))
        self.assertNotIn("USキーボードの出品です", embed["description"])

    def notified_content(self, items):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
            with mock.patch("builtins.print") as printed:
                check.notify_discord(items, "見出し")
        payloads = [json.loads(c.args[0]) for c in printed.call_args_list if c.args and c.args[0].startswith("{")]
        return payloads[0]["content"]

    def test_message_gets_big_heading_only_when_us_item_included(self):
        us_content = self.notified_content({"A": self.item("us")})
        self.assertTrue(us_content.startswith(check.US_ALERT_HEADING))
        self.assertIn(f"<@{check.MENTION_USER_ID}> 見出し", us_content)
        jis_content = self.notified_content({"B": self.item("jis")})
        self.assertEqual(jis_content, f"<@{check.MENTION_USER_ID}> 見出し")

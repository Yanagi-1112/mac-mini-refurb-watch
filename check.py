"""Apple整備済製品ページを監視し、新着をDiscordに通知する。

監視対象:
  共通条件: 13インチ・メモリ24GB以上
  - MacBook Air（US・JISキーボード搭載モデル）
  - MacBook Pro（USキーボード搭載モデルのみ）

Mac mini監視は2026-08-26に停止（M6搭載の新型が発売され整備済品を待つ必要がなくなったため）。
復活させる場合はgit履歴の is_mac_mini と WATCHES のMac miniエントリを参照。

DISCORD_WEBHOOK_URL 未設定時はドライラン（通知内容を標準出力に表示するだけ）。
"""

import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MENTION_USER_ID = "1028502587311403008"  # 通知時にメンションするDiscordユーザー
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 「USキーボード」「英語（米国）キーボード」「ＵＳキーボード」などの表記ゆれを拾う
# 大文字小文字を区別する（小文字の us がHTML属性名等に紛れて誤検知するのを防ぐ）
US_KEYBOARD_RE = re.compile(r"(US|ＵＳ|英語|米国)[^、。]{0,12}キーボード")
JIS_KEYBOARD_RE = re.compile(r"(JIS|ＪＩＳ|日本語)[^、。]{0,12}キーボード")


def tile_model(tile):
    return tile.get("filters", {}).get("dimensions", {}).get("refurbClearModel", "")


def is_macbook(tile):
    # MacBook Air / MacBook Pro のタイルか（"MacBook" はAir/Pro両方のタイトルに含まれる）
    return tile_model(tile) in ("macbookair", "macbookpro") or "MacBook" in tile.get(
        "title", ""
    )


def fetch_product_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def keyboard_layout(text):
    us = bool(US_KEYBOARD_RE.search(text))
    jis = bool(JIS_KEYBOARD_RE.search(text))
    # 両方の表記があるページや配列不明の商品は通知しない。
    if us != jis:
        return "us" if us else "jis"
    return None


def macbook_keyboard(tile, kb_cache):
    if not is_macbook(tile):
        return None
    part = tile.get("partNumber")
    # 将来タイル側にキーボード情報が追加された場合は、詳細ページを取得せず判定する
    layout = keyboard_layout(json.dumps(tile, ensure_ascii=False))
    if layout:
        if part:
            kb_cache[part] = layout
        return layout

    if not part:
        print("WARNING: partNumberがないためキーボード配列を判定できません", file=sys.stderr)
        return None
    if part in kb_cache:
        return kb_cache[part]

    # 同じ実行内でAirのUS/JIS判定が詳細取得を繰り返さないようにする。
    # 不明・取得失敗のNoneは保存時に除外し、次回実行で再試行する。
    kb_cache[part] = None
    path = tile.get("productDetailsUrl", "").split("?")[0]
    url = "https://www.apple.com" + path
    try:
        html = fetch_product_page(url)
    except Exception as e:
        print(f"WARNING: 商品詳細ページの取得に失敗しました ({part}): {e}", file=sys.stderr)
        return None
    layout = keyboard_layout(html)
    if layout is None:
        print(
            f"WARNING: 商品詳細ページのキーボード配列を判定できません ({part})",
            file=sys.stderr,
        )
        return None

    kb_cache[part] = layout
    return layout


def is_macbook_us(tile, kb_cache):
    return macbook_keyboard(tile, kb_cache) == "us"


def is_macbook_jis(tile, kb_cache):
    return macbook_keyboard(tile, kb_cache) == "jis"


def matches_model(tile, model):
    # Appleの一覧JSONはURLで指定した機種以外も含むため、必ず機種で絞る。
    actual = tile_model(tile)
    if actual:
        return actual == model
    title = tile.get("title", "")
    model_name = {"macbookair": "MacBook Air", "macbookpro": "MacBook Pro"}.get(model)
    return bool(model_name and model_name in title)


def matches_specs(tile):
    dimensions = tile.get("filters", {}).get("dimensions", {})
    screen = str(dimensions.get("dimensionScreensize", "")).strip().lower()
    memory = str(dimensions.get("tsMemorySize", "")).strip().lower()
    # Appleの13インチカテゴリ（13.3/13.6インチを含む）だけを対象にする。
    # SSD容量からメモリを推測せず、仕様不明の商品も除外する。
    ram = re.fullmatch(r"(\d+)\s*gb", memory)
    return bool(re.fullmatch(r"13(?:\.\d+)?\s*inch", screen) and ram and int(ram[1]) >= 24)


WATCHES = [
    {
        "name": "MacBook Air (USキーボード)",
        "model": "macbookair",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-air",
        "header": "⌨️ **13インチ・メモリ24GB以上・USキーボードの整備済MacBook Airが出品されました！**",
        "matches": is_macbook_us,
    },
    {
        "name": "MacBook Air (JISキーボード)",
        "model": "macbookair",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-air",
        "header": "⌨️ **13インチ・メモリ24GB以上・JISキーボードの整備済MacBook Airが出品されました！**",
        "matches": is_macbook_jis,
    },
    {
        "name": "MacBook Pro (USキーボード)",
        "model": "macbookpro",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-pro",
        "header": "💻 **13インチ・メモリ24GB以上・USキーボードの整備済MacBook Proが出品されました！**",
        "matches": is_macbook_us,
    },
]


def fetch_tiles(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        html = res.read().decode("utf-8")
    m = re.search(r"window\.REFURB_GRID_BOOTSTRAP = (\{.*\})", html)
    if not m:
        print(f"ERROR: REFURB_GRID_BOOTSTRAP not found at {url} (page layout changed?)", file=sys.stderr)
        sys.exit(1)
    data = json.loads(m.group(1))
    return data.get("tiles") or []


def extract_items(tiles, matches, kb_cache):
    items = {}
    fetched_detail = False
    for t in tiles:
        part = t.get("partNumber")
        needs_detail = (
            matches in (is_macbook_us, is_macbook_jis)
            and is_macbook(t)
            and bool(part)
            and part not in kb_cache
            and not keyboard_layout(json.dumps(t, ensure_ascii=False))
        )
        if needs_detail and fetched_detail:
            time.sleep(1)
        if not matches(t, kb_cache):
            if needs_detail:
                fetched_detail = True
            continue
        if needs_detail:
            fetched_detail = True
        part = part or t.get("title", "")
        url = "https://www.apple.com" + t.get("productDetailsUrl", "").split("?")[0]
        price = t.get("price", {}).get("currentPrice", {}).get("amount", "?")
        items[part] = {"title": t.get("title", ""), "price": price, "url": url}
    return items


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": {}, "kb": {}}
    if "items" not in state or "kb" not in state:
        return {"items": state, "kb": {}}
    # 旧形式のFalseは「非US」であり、JISとは限らないため再判定する。
    state["kb"] = {
        part: "us" if layout is True else layout
        for part, layout in state["kb"].items()
        if layout is True or layout in ("us", "jis")
    }
    return state


def save_state(state):
    state = dict(state, kb={k: v for k, v in state["kb"].items() if v in ("us", "jis")})
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def notify_discord(new_items, header):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    embeds = [
        {
            "title": item["title"],
            "url": item["url"],
            "description": f"**{item['price']}**",
            "color": 0x2ECC71,
        }
        for item in new_items.values()
    ]
    payload_base = {"content": f"<@{MENTION_USER_ID}> {header}"}
    # Discordのembedは1メッセージ10件まで
    for i in range(0, len(embeds), 10):
        payload = dict(payload_base, embeds=embeds[i : i + 10])
        if i > 0:
            payload.pop("content")
        if not webhook:
            print("[dry-run] would post to Discord:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            continue
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            print(f"Discord webhook: HTTP {res.status}")


def main():
    # 先に全ページを取得（途中で失敗した場合に通知だけ飛んでstateが残らない事故を防ぐ）
    pages = {}
    for w in WATCHES:
        if w["url"] not in pages:
            pages[w["url"]] = fetch_tiles(w["url"])

    state = load_state()
    previous = state["items"]
    kb_cache = state["kb"]
    current = {}
    for w in WATCHES:
        tiles = pages[w["url"]]
        model_tiles = [t for t in tiles if matches_model(t, w["model"]) and matches_specs(t)]
        items = extract_items(model_tiles, w["matches"], kb_cache)
        new_items = {k: v for k, v in items.items() if k not in previous}
        print(f"{w['name']}: tiles: {len(tiles)}, hit: {len(items)}, new: {len(new_items)}")
        current.update(items)
        if new_items:
            notify_discord(new_items, w["header"])
    save_state({"items": current, "kb": kb_cache})


if __name__ == "__main__":
    main()

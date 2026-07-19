"""Apple整備済製品ページを監視し、新着をDiscordに通知する。

監視対象:
  - Mac mini（全モデル）
  - MacBook Air（USキーボード搭載モデルのみ）

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


def tile_model(tile):
    return tile.get("filters", {}).get("dimensions", {}).get("refurbClearModel", "")


def is_mac_mini(tile, kb_cache=None):
    return tile_model(tile) == "macmini" or "Mac mini" in tile.get("title", "")


def fetch_product_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def is_macbook_air_us(tile, kb_cache):
    if tile_model(tile) != "macbookair" and "MacBook Air" not in tile.get("title", ""):
        return False
    part = tile.get("partNumber")
    # 将来タイル側にキーボード情報が追加された場合は、詳細ページを取得せず判定する
    if US_KEYBOARD_RE.search(json.dumps(tile, ensure_ascii=False)):
        if part:
            kb_cache[part] = True
        return True

    if not part:
        print("WARNING: partNumberがないためキーボード配列を判定できません", file=sys.stderr)
        return False
    if part in kb_cache:
        return kb_cache[part]

    path = tile.get("productDetailsUrl", "").split("?")[0]
    url = "https://www.apple.com" + path
    try:
        html = fetch_product_page(url)
    except Exception as e:
        print(f"WARNING: 商品詳細ページの取得に失敗しました ({part}): {e}", file=sys.stderr)
        return False
    if "キーボード" not in html:
        print(
            f"WARNING: 商品詳細ページにキーボード情報がありません ({part})",
            file=sys.stderr,
        )
        return False

    is_us = bool(US_KEYBOARD_RE.search(html))
    kb_cache[part] = is_us
    return is_us


WATCHES = [
    {
        "name": "Mac mini",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/mac-mini",
        "header": "🖥️ **整備済Mac miniが出品されました！**",
        "matches": is_mac_mini,
    },
    {
        "name": "MacBook Air (USキーボード)",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-air",
        "header": "⌨️ **USキーボードの整備済MacBook Airが出品されました！**",
        "matches": is_macbook_air_us,
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
        is_air = tile_model(t) == "macbookair" or "MacBook Air" in t.get("title", "")
        needs_detail = (
            matches is is_macbook_air_us
            and is_air
            and bool(part)
            and part not in kb_cache
            and not US_KEYBOARD_RE.search(json.dumps(t, ensure_ascii=False))
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
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def notify_discord(new_items, header="🖥️ **整備済Mac miniが出品されました！**"):
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
        items = extract_items(tiles, w["matches"], kb_cache)
        new_items = {k: v for k, v in items.items() if k not in previous}
        print(f"{w['name']}: tiles: {len(tiles)}, hit: {len(items)}, new: {len(new_items)}")
        current.update(items)
        if new_items:
            notify_discord(new_items, w["header"])
    save_state({"items": current, "kb": kb_cache})


if __name__ == "__main__":
    main()

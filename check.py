"""Apple整備済製品ページを監視し、Mac miniの新着をDiscordに通知する。

DISCORD_WEBHOOK_URL 未設定時はドライラン（通知内容を標準出力に表示するだけ）。
"""

import json
import os
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "https://www.apple.com/jp/shop/refurbished/mac/mac-mini"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def fetch_tiles():
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        html = res.read().decode("utf-8")
    m = re.search(r"window\.REFURB_GRID_BOOTSTRAP = (\{.*\})", html)
    if not m:
        print("ERROR: REFURB_GRID_BOOTSTRAP not found (page layout changed?)", file=sys.stderr)
        sys.exit(1)
    data = json.loads(m.group(1))
    return data.get("tiles") or []


def extract_minis(tiles):
    items = {}
    for t in tiles:
        model = t.get("filters", {}).get("dimensions", {}).get("refurbClearModel", "")
        title = t.get("title", "")
        if model != "macmini" and "Mac mini" not in title:
            continue
        part = t.get("partNumber") or title
        url = "https://www.apple.com" + t.get("productDetailsUrl", "").split("?")[0]
        price = t.get("price", {}).get("currentPrice", {}).get("amount", "?")
        items[part] = {"title": title, "price": price, "url": url}
    return items


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(items):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def notify_discord(new_items):
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
    payload_base = {"content": "🖥️ **整備済Mac miniが出品されました！**"}
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
    tiles = fetch_tiles()
    current = extract_minis(tiles)
    previous = load_state()
    new_items = {k: v for k, v in current.items() if k not in previous}

    print(f"tiles: {len(tiles)}, Mac mini: {len(current)}, new: {len(new_items)}")
    if new_items:
        notify_discord(new_items)
    save_state(current)


if __name__ == "__main__":
    main()

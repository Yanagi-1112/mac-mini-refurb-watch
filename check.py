"""Apple整備済製品ページを監視し、新着をDiscordに通知する。

監視対象:
  共通条件: M5以降・メモリ24GB以上
  - 13インチMacBook Air（US・JISキーボード搭載モデル）
  - 14インチMacBook Pro（US・JISキーボード搭載モデル）

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
    # Airは13インチカテゴリ（13.3/13.6）、Proは14インチ（14.2）を対象にする。
    # SSD容量からメモリを推測せず、仕様不明の商品も除外する。
    if matches_model(tile, "macbookair"):
        size = "13"
    elif matches_model(tile, "macbookpro"):
        size = "14"
    else:
        return False
    ram = re.fullmatch(r"(\d+)\s*gb", memory)
    chip = re.search(r"\bM(\d+)(?:\s+(?:Pro|Max|Ultra))?\s*チップ", tile.get("title", ""))
    return bool(
        re.fullmatch(rf"{size}(?:\.\d+)?\s*inch", screen)
        and ram and int(ram[1]) >= 24
        and chip and int(chip[1]) >= 5
    )


CHIP_RE = re.compile(
    r"(?:(\d+)コアCPUと(\d+)コアGPUを搭載した)?Apple\s*(M\d+(?:\s*(?:Pro|Max|Ultra))?)\s*チップ"
)
KEYBOARD_LABELS = {"us": "US配列", "jis": "JIS配列（日本語）"}
MODEL_LABELS = {"macbookair": "MacBook Air", "macbookpro": "MacBook Pro"}


def format_size(value):
    # Appleの一覧JSONは "24gb" / "1tb" のような小文字表記なので "24GB" / "1TB" に整える
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(gb|tb)", str(value).strip().lower())
    return f"{m[1]}{m[2].upper()}" if m else None


def describe_specs(tile, layout):
    """通知に載せる仕様（チップ・メモリ・ストレージ・配列など）を一覧タイルから取り出す。

    クリックせずに出品内容を見分けられるよう、Discordの通知文に使う。
    一覧JSONに無い項目はNoneのまま返し、通知側で「不明」と表示する。
    """
    title = tile.get("title", "")
    dimensions = tile.get("filters", {}).get("dimensions", {})
    chip = CHIP_RE.search(title)
    screen = re.match(r"(\d+)", str(dimensions.get("dimensionScreensize", "")))
    color = title.rsplit(" - ", 1)[1].strip() if " - " in title else None
    return {
        "model": MODEL_LABELS.get(tile_model(tile))
        or next((v for v in MODEL_LABELS.values() if v in title), "Mac"),
        "screen": f"{screen[1]}インチ" if screen else None,
        # M5 / M5 Pro / M5 Max の区別が付くよう、"M5Pro" のような表記ゆれも空白入りに揃える
        "chip": re.sub(r"(M\d+)\s*", r"\1 ", chip[3]).strip() if chip else None,
        "cpu_cores": int(chip[1]) if chip and chip[1] else None,
        "gpu_cores": int(chip[2]) if chip and chip[2] else None,
        "memory": format_size(dimensions.get("tsMemorySize", "")),
        "storage": format_size(dimensions.get("dimensionCapacity", "")),
        "keyboard": KEYBOARD_LABELS.get(layout),
        "color": color,
        "nano_texture": "Nano-texture" in title,
    }


WATCHES = [
    {
        "name": "MacBook Air (USキーボード)",
        "model": "macbookair",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-air",
        "header": "⌨️ **13インチ・M5以降・メモリ24GB以上・USキーボードの整備済MacBook Airが出品されました！**",
        "matches": is_macbook_us,
    },
    {
        "name": "MacBook Air (JISキーボード)",
        "model": "macbookair",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-air",
        "header": "⌨️ **13インチ・M5以降・メモリ24GB以上・JISキーボードの整備済MacBook Airが出品されました！**",
        "matches": is_macbook_jis,
    },
    {
        "name": "MacBook Pro (USキーボード)",
        "model": "macbookpro",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-pro",
        "header": "💻 **14インチ・M5以降・メモリ24GB以上・USキーボードの整備済MacBook Proが出品されました！**",
        "matches": is_macbook_us,
    },
    {
        "name": "MacBook Pro (JISキーボード)",
        "model": "macbookpro",
        "url": "https://www.apple.com/jp/shop/refurbished/mac/macbook-pro",
        "header": "💻 **14インチ・M5以降・メモリ24GB以上・JISキーボードの整備済MacBook Proが出品されました！**",
        "matches": is_macbook_jis,
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
        items[part] = {
            "title": t.get("title", ""),
            "price": price,
            "url": url,
            "specs": describe_specs(t, kb_cache.get(t.get("partNumber"))),
        }
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


def item_embed(item):
    """1出品ぶんのDiscord embedを作る。

    タイトル（=リンク）に「機種・チップ・メモリ・ストレージ・配列」を並べ、
    通知一覧を流し見しただけでどれをクリックすればよいか分かるようにする。
    specs が無い呼び出し（Actionsのテスト通知など）は従来どおり商品名と価格だけ表示する。
    """
    specs = item.get("specs")
    if not specs:
        return {
            "title": item["title"],
            "url": item["url"],
            "description": f"**{item['price']}**",
            "color": 0x2ECC71,
        }

    unknown = "不明"
    chip = specs.get("chip")
    cores = [
        f"{specs['cpu_cores']}コアCPU" if specs.get("cpu_cores") else None,
        f"{specs['gpu_cores']}コアGPU" if specs.get("gpu_cores") else None,
    ]
    cores_text = " / ".join(c for c in cores if c)
    # 同じM5 Proでも15コア/18コアCPUの別モデルがあるため、タイトルにもコア数を出す
    chip_summary = chip or "チップ不明"
    if cores_text:
        chip_summary += f"（{cores_text.replace(' / ', '・')}）"
    summary = [
        " ".join(x for x in (specs.get("screen"), specs.get("model")) if x),
        chip_summary,
        f"メモリ{specs.get('memory') or unknown}",
        f"SSD {specs.get('storage') or unknown}",
        (specs.get("keyboard") or "配列不明").split("（")[0],
    ]
    # 色違い・Nano-texture違いで同じタイトルが並ばないよう、外観も末尾に付ける
    if specs.get("color"):
        summary.append(specs["color"])
    if specs.get("nano_texture"):
        summary.append("Nano-texture")
    chip_text = chip or unknown
    if cores_text:
        chip_text += f"\n{cores_text}"
    appearance = specs.get("color") or unknown
    if specs.get("nano_texture"):
        appearance += "\nNano-textureディスプレイ"
    return {
        # 例: "14インチ MacBook Pro｜M5 Pro（15コアCPU・16コアGPU）｜メモリ24GB｜SSD 1TB｜JIS配列｜シルバー"
        "title": "｜".join(summary)[:256],
        "url": item["url"],
        "description": f"💴 **{item['price']}**　👉 タイトルをクリックで商品ページへ",
        "color": 0x2ECC71,
        "fields": [
            {"name": "🧠 チップ", "value": chip_text, "inline": True},
            # Apple シリコンはメモリをGPUと共有するため、このメモリ量がVRAMとしても使われる
            {"name": "💾 メモリ（VRAM共用）", "value": specs.get("memory") or unknown, "inline": True},
            {"name": "🗄️ ストレージ", "value": f"SSD {specs.get('storage') or unknown}", "inline": True},
            {"name": "⌨️ キーボード", "value": specs.get("keyboard") or unknown, "inline": True},
            {"name": "🎨 カラー", "value": appearance, "inline": True},
        ],
    }


def notify_discord(new_items, header):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    embeds = [item_embed(item) for item in new_items.values()]
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

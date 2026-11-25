"""Apple整備済製品ページを監視し、新着をDiscordに通知する。

監視対象（互いに重ならない5つのウォッチ。共通条件は「M5以降」。メモリ・画面サイズが読めないものは対象外）:
  1. MacBook Air 本命 US配列 : 13インチ・メモリ32GB・SSD 1TB
  2. MacBook Air 本命 JIS配列: 同上
  3. MacBook Air 32GB以上 US配列: 13インチ・メモリ32GB以上で、本命（32GB/1TB）ではないもの（SSD不問）
  4. MacBook Pro US配列  : 14インチ・メモリ32GB以上
  5. MacBook Pro JIS配列 : 14インチ・メモリ32GB以上

経緯: 2026-11-17に購入構成を「13インチAir・32GB・1TB」の1つに絞ったが、
2026-11-23にユーザーが「本命より少し条件の低いものも知りたい」と希望したため、近い構成も通知するよう拡張した。
本命だけは見出しに⭐【本命】を付けて見分けられるようにしている。
2026-11-25にユーザーの希望で全ウォッチのメモリ下限を32GB以上に引き上げた（Proのメモリ不問も廃止）。
32GB未満、JISのAirで本命以外、15インチAir・16インチPro、M4以前は通知しない。

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


# 「本命」の購入構成（ユーザーが13インチAir・32GB・1TBに決めたため。2026-11-17）。
# 2026-11-23に「本命より少し条件の低いものも知りたい」との希望で、近い構成（US配列Air・14インチPro）も
# 別ウォッチとして通知するようにした。本命はこの2つ「ちょうど一致」で判定し、他のウォッチと重複通知しない基準にも使う。
# 値はAppleの一覧JSONの表記（小文字）に合わせる。変えたい場合は下の定数を書き換えるだけでよい。
TARGET_MEMORY_GB = 32  # 本命: tsMemorySize が "32gb" のものだけ
TARGET_STORAGE = "1tb"  # 本命: filters.dimensions.dimensionCapacity が "1tb" のものだけ
MIN_MEMORY_GB = 32  # 本命以外のウォッチ（3〜5）の下限（32GB以上。24GB以下・メモリ不明は通知しない）
MIN_CHIP_GENERATION = 5  # M5以降（M5 Pro/Max・M6以降も含む。チップ世代の数字で判定）


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


def tile_facts(tile):
    """スペック判定に使う値を一覧タイルから取り出す。読めない項目はNone（推測しない）。

    screen: 画面インチの整数部（13 / 13.3 / 13.6 → 13、14 / 14.2 → 14）
    memory: メモリGB（整数）  storage: SSD容量（"1tb" など小文字） chip: チップ世代の数字（M5 → 5）
    """
    dimensions = tile.get("filters", {}).get("dimensions", {})
    screen = re.fullmatch(
        r"(\d+)(?:\.\d+)?\s*inch", str(dimensions.get("dimensionScreensize", "")).strip().lower()
    )
    ram = re.fullmatch(r"(\d+)\s*gb", str(dimensions.get("tsMemorySize", "")).strip().lower())
    chip = re.search(r"\bM(\d+)(?:\s+(?:Pro|Max|Ultra))?\s*チップ", tile.get("title", ""))
    return {
        "screen": int(screen[1]) if screen else None,
        "memory": int(ram[1]) if ram else None,
        "storage": str(dimensions.get("dimensionCapacity", "")).strip().lower() or None,
        "chip": int(chip[1]) if chip else None,
    }


def _is_target(tile, model, screen):
    # 機種・画面インチ・M5以降を満たすか（5つのウォッチ共通の土台）。facts も一緒に返す
    f = tile_facts(tile)
    ok = (
        matches_model(tile, model)
        and f["screen"] == screen
        and f["chip"] is not None
        and f["chip"] >= MIN_CHIP_GENERATION
    )
    return ok, f


def _is_main_config(f):
    # 本命構成（32GB・1TBちょうど）。SSDが不明（None）なら本命とは見なさない
    return f["memory"] == TARGET_MEMORY_GB and f["storage"] == TARGET_STORAGE


def specs_air_main(tile):
    # ウォッチ1・2: 13インチAir・本命（32GB/1TB）
    ok, f = _is_target(tile, "macbookair", 13)
    return ok and _is_main_config(f)


def specs_air_min_memory(tile):
    # ウォッチ3: 13インチAir・32GB以上。本命は別ウォッチで通知するので除く（1出品が2回通知されないように）。
    # SSD容量は不問（不明でも可）。メモリが読めないものは対象外
    ok, f = _is_target(tile, "macbookair", 13)
    return ok and f["memory"] is not None and f["memory"] >= MIN_MEMORY_GB and not _is_main_config(f)


def specs_pro14_min_memory(tile):
    # ウォッチ4・5: 14インチPro・32GB以上（メモリが読めないものは対象外）。
    # US/JISの振り分けはキーボード配列の判定で行うので、2ウォッチで同じ条件を共用しても重複通知にならない
    ok, f = _is_target(tile, "macbookpro", 14)
    return ok and f["memory"] is not None and f["memory"] >= MIN_MEMORY_GB


def matches_specs(tile):
    """どれかのウォッチのスペック条件に合うか（キーボード配列は見ない）。"""
    return any(w["specs"](tile) for w in WATCHES)


CHIP_RE = re.compile(
    r"(?:(\d+)コアCPUと(\d+)コアGPUを搭載した)?Apple\s*(M\d+(?:\s*(?:Pro|Max|Ultra))?)\s*チップ"
)
KEYBOARD_LABELS = {"us": "US配列", "jis": "JIS配列（日本語）"}

# USキーボードの出品はめったに出ない（2026-11時点で一度も観測なし）ので、見逃さないよう通知をド派手にする。
# embedの色を赤にし、タイトル・説明・キーボード欄を目立たせ、メッセージ本文の先頭に大見出しを付ける。
NORMAL_COLOR = 0x2ECC71
US_ALERT_COLOR = 0xFF0000
US_TITLE_PREFIX = "🚨🇺🇸【USキーボード】🇺🇸🚨 "
US_ALERT_HEADING = "# 🚨🚨🚨 USキーボードの整備済MacBookが出ました！ 🚨🚨🚨\n## 🇺🇸 めったに出ないので今すぐ確認を！ 🇺🇸\n"


# 「本命」（13インチAir・32GB・1TB）の出品は数時間で売り切れることがある（2026-11-25に実例）ので、こちらも目立たせる。
# embedの色を金色にし、タイトル先頭に冠を付け、メッセージ本文の先頭に大見出しを付ける。
# US配列の本命は、US用の見出しも重ねて付け、色はUSの赤を優先する。
MAIN_ALERT_COLOR = 0xFFD700
MAIN_TITLE_PREFIX = "👑⭐【本命】⭐👑 "
MAIN_ALERT_HEADING = "# 👑⭐ 本命のMacBook Airが出ました！ ⭐👑\n## 13インチ・M5以降・32GB・1TB ── 売り切れる前に今すぐ確認を！\n"


def is_us_item(item):
    specs = item.get("specs") or {}
    return specs.get("keyboard") == KEYBOARD_LABELS["us"]
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


# 監視ウォッチ5件（互いに重ならない条件。この順で通知する）。
# "specs" はタイルのスペック条件、"matches" はキーボード配列の判定（詳細ページ取得を伴う）。
# main() は先に specs で絞ってから配列判定に進むので、条件外のタイルで詳細ページは取得しない。
AIR_URL = "https://www.apple.com/jp/shop/refurbished/mac/macbook-air"
PRO_URL = "https://www.apple.com/jp/shop/refurbished/mac/macbook-pro"
WATCHES = [
    {
        "name": "MacBook Air 本命 (USキーボード)",
        "model": "macbookair",
        "url": AIR_URL,
        "header": "⭐ **【本命】13インチ・M5以降・メモリ32GB・SSD 1TB・USキーボードの整備済MacBook Airが出品されました！**",
        "specs": specs_air_main,
        "matches": is_macbook_us,
        "main": True,
    },
    {
        "name": "MacBook Air 本命 (JISキーボード)",
        "model": "macbookair",
        "url": AIR_URL,
        "header": "⭐ **【本命】13インチ・M5以降・メモリ32GB・SSD 1TB・JISキーボードの整備済MacBook Airが出品されました！**",
        "specs": specs_air_main,
        "matches": is_macbook_jis,
        "main": True,
    },
    {
        "name": "MacBook Air 32GB以上 (USキーボード)",
        "model": "macbookair",
        "url": AIR_URL,
        "header": "⌨️ **13インチ・M5以降・メモリ32GB以上・USキーボードの整備済MacBook Airが出品されました！**",
        "specs": specs_air_min_memory,
        "matches": is_macbook_us,
    },
    {
        "name": "MacBook Pro 32GB以上 (USキーボード)",
        "model": "macbookpro",
        "url": PRO_URL,
        "header": "💻 **14インチ・M5以降・メモリ32GB以上・USキーボードの整備済MacBook Proが出品されました！**",
        "specs": specs_pro14_min_memory,
        "matches": is_macbook_us,
    },
    {
        "name": "MacBook Pro 32GB以上 (JISキーボード)",
        "model": "macbookpro",
        "url": PRO_URL,
        "header": "💻 **14インチ・M5以降・メモリ32GB以上・JISキーボードの整備済MacBook Proが出品されました！**",
        "specs": specs_pro14_min_memory,
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


def item_embed(item, main=False):
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
            "color": NORMAL_COLOR,
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
    us = is_us_item(item)
    title = "｜".join(summary)
    description = f"💴 **{item['price']}**　👉 タイトルをクリックで商品ページへ"
    keyboard_text = specs.get("keyboard") or unknown
    if main:
        title = MAIN_TITLE_PREFIX + title
        description = "👑 **本命の構成です！売り切れる前にすぐ確認を！** 👑\n" + description
    if us:
        title = US_TITLE_PREFIX + title
        description = "🚨 **USキーボードの出品です！売り切れる前にすぐ確認を！** 🚨\n" + description
        keyboard_text = "🇺🇸 **US配列** 🇺🇸"
    return {
        # 例: "14インチ MacBook Pro｜M5 Pro（15コアCPU・16コアGPU）｜メモリ24GB｜SSD 1TB｜JIS配列｜シルバー"
        # US配列なら先頭に US_TITLE_PREFIX が付き、色が赤になる
        "title": title[:256],
        "url": item["url"],
        "description": description,
        "color": US_ALERT_COLOR if us else MAIN_ALERT_COLOR if main else NORMAL_COLOR,
        "fields": [
            {"name": "🧠 チップ", "value": chip_text, "inline": True},
            # Apple シリコンはメモリをGPUと共有するため、このメモリ量がVRAMとしても使われる
            {"name": "💾 メモリ（VRAM共用）", "value": specs.get("memory") or unknown, "inline": True},
            {"name": "🗄️ ストレージ", "value": f"SSD {specs.get('storage') or unknown}", "inline": True},
            {"name": "⌨️ キーボード", "value": keyboard_text, "inline": True},
            {"name": "🎨 カラー", "value": appearance, "inline": True},
        ],
    }


def notify_discord(new_items, header, main=False):
    """main=True は本命ウォッチ（13インチAir・32GB・1TB）の通知。見出しと色で目立たせる。"""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    embeds = [item_embed(item, main=main) for item in new_items.values()]
    heading = (MAIN_ALERT_HEADING if main else "") + (
        US_ALERT_HEADING if any(is_us_item(item) for item in new_items.values()) else ""
    )
    payload_base = {"content": f"{heading}<@{MENTION_USER_ID}> {header}"}
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
        model_tiles = [t for t in tiles if matches_model(t, w["model"]) and w["specs"](t)]
        items = extract_items(model_tiles, w["matches"], kb_cache)
        new_items = {k: v for k, v in items.items() if k not in previous}
        print(f"{w['name']}: tiles: {len(tiles)}, hit: {len(items)}, new: {len(new_items)}")
        current.update(items)
        if new_items:
            notify_discord(new_items, w["header"], main=w.get("main", False))
    save_state({"items": current, "kb": kb_cache})


if __name__ == "__main__":
    main()

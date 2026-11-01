#!/usr/bin/env python3
"""城プロRE編成補助: wikiから全城娘一覧と能力値を取得し、編成補助ツール(HTML)を作り直す。
標準ライブラリだけで動く。使い方: python3 build.py [--offline]
  --offline  取得をせず raw/ にある保存済みHTMLだけで作り直す
"""
import html.parser, json, os, re, sys, time, datetime, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "raw")
OUT = os.path.join(BASE, "城プロ編成補助.html")
LOG = os.path.join(BASE, "update.log")
WEAPON_PAGES = ["ステータス一覧/" + w for w in "刀 槍 槌 盾 拳 鎌 戦棍 双剣 ランス 弓 石弓 鉄砲 大砲 歌舞 法術 鈴 杖 祓串 本 投剣 鞭 陣貝 軍船 茶器 その他".split()]
PAGES = ["全城娘一覧", "ステータス一覧/能力値", "編成特技", "特殊能力", "城娘一覧/改弐"] + WEAPON_PAGES
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

def fetch():
    os.makedirs(RAW, exist_ok=True)
    for i, page in enumerate(PAGES):
        if i: time.sleep(3)
        url = "https://scre.swiki.jp/index.php?" + urllib.parse.quote(page)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            if page not in body[:5000]:
                raise RuntimeError("期待したページが返ってきませんでした")
        except Exception as e:
            # 武器種別ページは補助なので、取れなくても前回保存分で続行する
            if page in WEAPON_PAGES or page == "城娘一覧/改弐": print(f"{page}: 取得失敗（前回分を使用）: {e}"); continue
            raise RuntimeError(f"{page}: {e}")
        with open(os.path.join(RAW, page.replace("/", "__") + ".html"), "w", encoding="utf-8") as f:
            f.write(body)

# ---- 表の読み取り（入れ子のない表だけを対象にする） ----
class Tables(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.done = [], []
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.stack: self.stack[-1]["nested"] = True
            self.stack.append({"rows": [], "nested": False, "cell": None})
        elif not self.stack: return
        elif tag == "tr": self.stack[-1]["rows"].append([])
        elif tag in ("td", "th"):
            t = self.stack[-1]
            if not t["rows"]: t["rows"].append([])
            t["cell"] = []; t["rows"][-1].append(t["cell"])
    def handle_endtag(self, tag):
        if tag == "table" and self.stack:
            t = self.stack.pop()
            if not t["nested"]: self.done.append([["\n".join(c) for c in r] for r in t["rows"]])
        elif tag in ("td", "th") and self.stack: self.stack[-1]["cell"] = None
    def handle_data(self, data):
        if self.stack and self.stack[-1]["cell"] is not None:
            s = data.strip()
            if s: self.stack[-1]["cell"].append(s)

def tables(name):
    path = os.path.join(RAW, name.replace("/", "__") + ".html")
    if not os.path.exists(path): return []
    p = Tables()
    with open(path, encoding="utf-8") as f: p.feed(f.read())
    return p.done

def parse():
    units = {}
    for t in tables("全城娘一覧"):
        if not t or "城娘" not in t[0]: continue
        for r in t:
            if len(r) != 10 or not re.fullmatch(r"\d+", r[0]): continue
            no, name, kai, rar, attr, wep, skill, form, special, strat = r
            units.setdefault(no, dict(no=no, name=name, kai=kai, rarity=int(rar) if rar.isdigit() else 0,
                attr=[a for a in re.split(r"[/\n]", attr) if a], weapon=wep, skill=skill, form=form, special=special, strat=strat))
    # 全城娘一覧は改弐が反映されていないことがあるため、武器種別ページの改築段階ごとの行から最大段階を採用する
    RANK = {"": 0, "壱": 1, "弐": 2}
    for page in WEAPON_PAGES:
        for t in tables(page):
            if not t or "城娘" not in t[0]: continue
            for r in t:
                if len(r) != 10 or not re.fullmatch(r"\d+", r[0]) or r[0] not in units: continue
                u = units[r[0]]
                if RANK.get(r[2], 0) > RANK.get(u["kai"], 0) or (r[2] == u["kai"] and not u.get("_wp")):
                    u.update(kai=r[2], skill=r[6], form=r[7], special=r[8], strat=r[9], _wp=True)
    stats = {}
    for t in tables("ステータス一覧/能力値"):
        head = " ".join(c for r in t[:2] for c in r)
        kai2 = "[改弐]" in head and "[無印]" not in head
        for r in t:
            if len(r) < 15 or not re.fullmatch(r"\d+", r[0]): continue
            vals = [int(x) for x in r[10:] if re.fullmatch(r"\d+", x)]
            d = stats.setdefault(r[0], {})
            if kai2: d["弐"] = vals[:5]
            else:
                d["無"] = vals[:5]
                if len(vals) >= 10: d["壱"] = vals[5:10]
    return units, stats

def skill_pages():
    """編成特技・特殊能力ページの表から {城娘名: [(名称, 効果)]} を作る"""
    res = {}
    for page in ("編成特技", "特殊能力"):
        d = res[page] = {}
        for t in tables(page):
            if not t or "効果" not in t[0] or "城娘" not in t[0]: continue
            h = t[0]; ie, iu = h.index("効果"), h.index("城娘")
            for r in t[1:]:
                if len(r) != len(h): continue
                for un in r[iu].split("\n"):
                    if re.fullmatch(r"\[改.\]|★\d|その他|/", un): continue
                    d.setdefault(un, []).append((r[1], r[ie]))
    return res

# ---- 効果の読み取り ----
WEAPONS = "刀 槍 槌 盾 拳 鎌 戦棍 双剣 ランス 弓 石弓 鉄砲 大砲 歌舞 法術 鈴 杖 祓串 本 投剣 鞭 陣貝 軍船 茶器".split()
FAR = "弓 石弓 鉄砲 大砲 歌舞 法術 鈴 杖 祓串 本".split()
BOTH = "投剣 鞭 陣貝 軍船 茶器".split()
ATTRS = {"平": "平", "平山": "平山", "山": "山", "水": "水", "地獄": "地獄", "無": "無", "無属性": "無"}
STAT = r"(?:攻撃速度|攻撃後の隙|与えるダメージ|与ダメージ|被ダメージ|移動速度|攻撃|防御|耐久|射程|回復)"
PAIR = re.compile(r"(" + STAT + r"(?:(?:と|や|、|/)" + STAT + r")*)(?:が|を|は)?(?:\d+秒間)?(\d+(?:\.\d+)?)(?![\d.]*(?:秒|回|体|段))(%|倍)?(?!の値|分)")
VERB = re.compile(r"上昇|低下|短縮|軽減|延長|増加|減少|無視")
SUBJ = [
  (re.compile(r"(?:伏兵の|対象の)?(?:射程|範囲)内の(?:全ての)?敵(?:全て)?の|攻撃した敵の|全ての敵の|敵の"), "enemy"),
  (re.compile(r"自身(?:と自身)?(?:と全ての伏兵|と自身の伏兵)?の"), "self"),
  (re.compile(r"(?:伏兵の|対象の)?(?:射程|範囲)内の?(?:全ての)?(?:城娘|味方)(?:全て)?の"), "inrange"),
  (re.compile(r"(?:全|全ての)(?:城娘|味方)の"), "all"),
  (re.compile(r"(?:部隊の|全ての|全)([^の。\s]{1,20}?)(?:城娘|城)の"), "group"),
  (re.compile(r"対象の"), "target"),
  (re.compile(r"([^の、。\s]{1,14}?)城娘の"), "group"),
]

def group_target(g):
    parts = [x for x in re.split(r"[、と・/]", g.replace("全ての", "")) if x]
    if len(parts) > 1 and all(x in WEAPONS for x in parts): return "weapon:" + "|".join(parts)
    g = g.replace("全ての", "").replace("属性", "")
    if g == "近接": return "near"
    if g == "遠隔": return "far"
    if g in WEAPONS: return "weapon:" + g
    if g in ATTRS: return "attr:" + ATTRS[g]
    return "other:" + g

def segments(text):
    out, prev = [], None
    for sent in re.split(r"[。\n　 ]+", text):
        if not sent: continue
        hits = sorted(((m.start(), m.end(), kind, m) for rx, kind in SUBJ for m in rx.finditer(sent)), key=lambda h: (h[0], -h[1]))
        chosen, last = [], -1
        for h in hits:
            if h[0] >= last: chosen.append(h); last = h[1]
        if not chosen:
            out.append((prev[0], prev[1], sent) if prev else ("none", None, sent)); continue
        prev = (chosen[-1][2], chosen[-1][3])
        for i, (s, e, kind, m) in enumerate(chosen):
            end = chosen[i + 1][0] if i + 1 < len(chosen) else len(sent)
            out.append((kind, m, sent[e:end]))
    return out

def classify(enemy, stat, val, unit, verb):
    pct = unit == "%"; mult = unit == "倍"
    if mult: val = round((val - 1) * 100, 1); pct = True
    if enemy:
        if verb in ("低下", "減少"):
            if pct: return {"攻撃": "enemy_atk", "防御": "enemy_def", "移動速度": "enemy_slow", "射程": "enemy_rng", "与ダメージ": "enemy_dealt"}.get(stat), val
            return ("enemy_def_flat" if stat == "防御" else None), val
        if verb in ("上昇", "増加") and stat == "被ダメージ": return "enemy_taken", val
        return None, val
    if verb in ("上昇", "増加"):
        m = {"攻撃": ("atk_pct", "atk_flat"), "防御": ("def_pct", "def_flat"), "耐久": ("hp_pct", "hp_flat"), "射程": ("rng_pct", "rng_flat"),
             "回復": ("heal_pct", "heal_flat"), "攻撃速度": ("speed", None), "与ダメージ": ("dmg_up", None), "与えるダメージ": ("dmg_up2", None)}.get(stat)
        if not m: return None, val
        return (m[0] if pct else m[1]), val
    if verb == "短縮" and stat == "攻撃後の隙": return "gap", val
    if verb == "軽減" and stat == "被ダメージ": return "dmg_cut", val
    return None, val

def num(v): return int(v) if float(v).is_integer() else v

def effects_of(text):
    effs = []
    if not text or text == "なし": return effs
    text = re.sub(r"与ダメ(?!ージ)", "与ダメージ", re.sub(r"被ダメ(?!ージ)", "被ダメージ", text))
    selfonly = "自分のみ" in text
    for kind, m, seg in segments(text):
        if kind == "none": continue
        target = group_target(m.group(1)) if kind == "group" else ("self" if selfonly else "target") if kind == "target" else kind
        cond = bool(re.search(r"度に|毎に|ずつ|時間経過|撃破時|被攻撃時|計略中|発動中", seg))
        giant = "巨大化する度に" in seg or "巨大化毎に" in seg
        cap = re.search(r"(?:上限|最大)(\d+)%", seg)
        stack = bool(re.search(r"重複(?!なし|しない)", seg))
        di = re.search(r"防御を(\d+)%無視", seg)
        if di: effs.append(dict(type="def_ignore", value=int(di.group(1)), target="self"))
        elif "防御無視" in seg or "防御を無視" in seg:
            e = dict(type="def_ignore", value=100, target="self")
            if cond: e["cond"] = True
            effs.append(e)
        for p in PAIR.finditer(seg):
            v = VERB.search(seg, p.end())
            val = float(p.group(2)); unit = p.group(3) or ""
            verb = v.group(0) if v else None
            # 「1.5倍」のように動詞を伴わない倍率は上昇として扱う
            if unit == "倍" and (not v or v.start() - p.end() > 8): verb = "上昇"
            if not verb: continue
            if giant: val *= 5
            if cap and unit == "%": val = float(cap.group(1))
            for stat in re.findall(STAT, p.group(1)):
                t, vv = classify(target == "enemy", stat, val, unit, verb)
                if not t: continue
                e = dict(type=t, value=num(vv), target=target)
                if stack: e["stack"] = True
                if cond or giant: e["cond"] = True
                effs.append(e)
    seen, out = set(), []
    for e in effs:
        k = (e["type"], e["target"], e["value"])
        if k not in seen: seen.add(k); out.append(e)
    return out

# ---- 能力値依存のバフ（鼓舞など）: 「自身の攻撃の35%の値を射程内の城娘に加算」 ----
RSTAT = {"攻撃": "atk", "防御": "def", "耐久": "hp", "現在耐久": "hp", "最大耐久": "hp", "射程": "rng", "回復": "heal"}
RS = r"(?:現在耐久|最大耐久|攻撃|防御|耐久|射程|回復)"
RLIST = r"((?:" + RS + r"(?:と" + RS + r")*の\d+(?:\.\d+)?%(?:の値)?、?)+)"
RSRC = r"(自身の|対象の|各城娘の)?"
REF_A = re.compile(RSRC + RLIST + r"の?値?を(?:自身を除く|自身以外の|対象を除く)?([^、。\s]{0,30}?)に加算")
REF_B = re.compile(r"([^、。\s]{0,30}?)に" + RSRC + RLIST + r"の?値?を?加算")
REF_C = re.compile(r"([^、。\s]{0,30}?)に(自身の|対象の)(\d+(?:\.\d+)?)%の値を加算")
REF_E = re.compile(r"敵(?:全て)?の(" + RS + r"(?:と" + RS + r")*)が" + RSRC + RLIST + r"の?値?(?:と\d+)?(?:減少|低下)")

def ref_items(lst):
    out = []
    for m in re.finditer(r"(" + RS + r"(?:と" + RS + r")*)の(\d+(?:\.\d+)?)%", lst):
        for st in re.findall(RS, m.group(1)): out.append((RSTAT[st], num(float(m.group(2)))))
    return out

def ref_dest(d, selfonly):
    """加算先の文字列 → (対象, 加算先の能力リスト or None, 自身を除くか)"""
    ex = bool(re.search(r"自身を除く|自身以外|対象を除く|\(自身を除く\)", d))
    d = re.sub(r"【[^】]*】|自身を除く|自身以外の|対象を除く|全ての|全て", "", d)
    stats = None
    m = re.search(r"の?(" + RS + r"(?:と" + RS + r")*)$", d)
    if m and m.start() > 0 or (m and m.start() == 0):
        stats = [RSTAT[x] for x in re.findall(RS, m.group(1))]; d = d[:m.start()]
    d = d.rstrip("の")
    if "伏兵" in d and not re.search(r"城娘|味方", d): return None, stats, ex
    if d in ("", "自身", "自分"): return ("self", stats, ex)
    if d == "対象": return ("self" if selfonly else "target", stats, ex)
    if re.search(r"(射程|範囲)内|鼓舞対象", d): return "inrange", stats, ex
    if re.fullmatch(r"全?(城娘|味方)|伏兵以外の全?味方", d): return "all", stats, ex
    g = re.fullmatch(r"全?([^の]{1,10}?)(?:城娘|城)", d)
    if g: return group_target(g.group(1)), stats, ex
    return "other:" + d, stats, ex

def refs_of(text):
    out = []
    if not text or text == "なし": return out
    selfonly = "自分のみ" in text
    for sent in re.split(r"[。\n]+", text):
        kobu = "鼓舞" in sent
        cond = bool(re.search(r"度に|毎に|ずつ|最大化時|撃破時|被攻撃時", sent))
        done = []
        for rx, order in ((REF_B, "B"), (REF_A, "A")):
            for m in rx.finditer(sent):
                if any(m.start() < e and s < m.end() for s, e in done): continue
                done.append((m.start(), m.end()))
                if order == "A": src, lst, dest = m.group(1), m.group(2), m.group(3)
                else: dest, src, lst = m.group(1), m.group(2), m.group(3)
                # 「自身の攻撃に防御の50%」のように加算先が自身なら参照元も自身
                frm = "recv" if src == "各城娘の" else "giver"
                tgt, dstats, ex = ref_dest(dest, selfonly)
                if not tgt: continue
                items = ref_items(lst)
                for st, pct in items:
                    for ds in (dstats or [st]):
                        e = dict(type=ds + "_flat", value=0, target=tgt, ref=dict(stat=st, pct=pct, frm=frm))
                        if ex or (tgt == "inrange" and re.search(r"除く|以外", sent)): e["exSelf"] = True
                        if kobu: e["kobu"] = True
                        if cond: e["cond"] = True
                        out.append(e)
        for m in REF_C.finditer(sent):
            if any(m.start() < e and s < m.end() for s, e in done): continue
            tgt, dstats, ex = ref_dest(m.group(1), selfonly)
            if not tgt or not dstats: continue
            for ds in dstats:
                e = dict(type=ds + "_flat", value=0, target=tgt, ref=dict(stat=ds, pct=num(float(m.group(3))), frm="giver"))
                if ex or re.search(r"除く|以外", sent): e["exSelf"] = True
                if kobu: e["kobu"] = True
                if cond: e["cond"] = True
                out.append(e)
        km = re.search(r"鼓舞(?:効果|の加算値)(?:と[^がを]{1,10})?が(\d+(?:\.\d+)?)倍", sent)
        if km: out.append(dict(type="kobu_mult", value=num(round((float(km.group(1)) - 1) * 100, 1)), target="self"))
        for m in REF_E.finditer(sent):
            for es in re.findall(RS, m.group(1)):
                t = {"atk": "enemy_atk_flat", "def": "enemy_def_flat"}.get(RSTAT[es])
                if not t: continue
                for st, pct in ref_items(m.group(3)):
                    e = dict(type=t, value=0, target="enemy", ref=dict(stat=st, pct=pct, frm="giver"))
                    if cond or "巨大化" in sent: e["cond"] = True
                    out.append(e)
    return out

# ---- 特殊効果タグ ----
N = r"(\d+)"
TAGS = [
  ("隠密無効",         r"隠密(?:状態|効果)?を?無効|攻撃対象にならない効果を無効|敵の隠密状態を無効"),
  ("敵から狙われない", r"敵(?:から|に)狙われ(?:ず|ない|なく)|飛行敵以外(?:の敵)?に狙われ|攻撃対象にならない(?!効果)|攻撃対象とならず|隠密状態に"),
  ("敵を引きつける",   r"優先(?:して)?(?:狙われ|攻撃対象)"),
  ("状態異常無効",     r"状態異常(?:付与)?を?(?:回復し)?無効|全状態異常を回復し無効|全ての状態異常を無効"),
  ("状態異常回復",     r"状態異常を回復|」を回復"),
  ("火傷無効",         r"「火傷」(?:を|付与を)?(?:回復し)?無効|と「火傷」を回復し無効"),
  ("猛毒無効",         r"「猛毒」(?:を|と「火傷」を)?(?:回復し)?無効"),
  ("氷結無効",         r"「?氷結」?(?:を)?無効(?!化されない)"),
  ("足止め数増加",     r"足止め(?:数)?が?" + N + r"増加|攻撃対象と足止め数が" + N + r"増加"),
  ("攻撃対象数増加",   r"攻撃対象(?:数)?が?" + N + r"増加|攻撃対象と足止め数が" + N + r"増加"),
  ("連続攻撃",         N + r"連続|" + N + r"連撃"),
  ("範囲・貫通攻撃",   r"範囲攻撃|周囲(?:に|を|の敵)|貫通|射程内の全(?:て)?の?敵(?:に|を)攻撃|全ての敵を攻撃"),
  ("後退",             r"後退させ"),
  ("移動停止",         r"移動速度を?(?:少しの間|\d+秒間)?0に|移動速度0"),
  ("防御0化",          r"防御が?0に"),
  ("氷結付与",         r"「氷結」(?:状態)?に(?:する|し)"),
  ("火傷付与",         r"「火傷(?:\(弱\))?」(?:状態)?に(?:する|し|な)|｢火傷｣状態にする"),
  ("猛毒付与",         r"「猛毒」(?:状態)?に(?:する|し)"),
  ("反射",             r"反射"),
  ("反撃",             r"反撃"),
  ("ダメージ無効化",   r"\d+(?:まで|以下)のダメージを無効|受けるダメージを\d+まで無効"),
  ("大破しない",       r"大破(?:扱いに)?(?:せず|しない|ならな)"),
  ("与ダメージ吸収",   r"与ダメージの\d+%(?:耐久が)?回復|耐久が与ダメージの\d+%回復"),
  ("味方の耐久回復",   r"(?:城娘|殿|味方)(?:と殿|と城娘)?(?:全て)?(?:に|を)?(?:継続的に)?(?:\S{0,8}で)?回復(?:を行|する|し)"),
  ("気増加",           r"気が(?:徐々に|追加で)?\d*増加|気の自然(?:増加|回復)量|獲得気が\d+増加|撃破気が?\d*増加|撃破獲得気"),
  ("計略短縮",         r"計略(?:再使用時間|使用までの時間)(?:が|を)?\d+(?:%|秒)短縮"),
  ("巨大化気軽減",     r"巨大化気を?\d+%?軽減|巨大化(?:に必要な)?気が?\d*%?(?:減少|軽減)"),
  ("対飛行",           r"飛行敵?(?:に対して|に対する|には|に)(?:の)?(?:攻撃|\d)|飛行敵?(?:への攻撃|に\d)"),
  ("対妖怪",           r"妖怪(?:に対して|に対し|には|への攻撃|に\d)|妖怪に半減されない|妖怪に攻撃を半減されず"),
  ("術攻撃",           r"術攻撃(?:に|を行|となり|化)|術ダメージを与え"),
  ("伏兵",             r"伏兵を配置|伏兵\(|伏兵（"),
  ("特殊攻撃ゲージ",   r"特殊攻撃ゲージ|ゲージ蓄積"),
  ("配置・移動",       r"全マス|マスに移動|移動可|配置可能"),
]
TAG_RX = [(t, re.compile(p)) for t, p in TAGS]

def tags_of(text):
    out = []
    if not text or text == "なし": return out
    for t, rx in TAG_RX:
        ms = list(rx.finditer(text))
        if not ms: continue
        nums = [int(g) for m in ms for g in m.groups() if g]
        out.append({"tag": t, "value": max(nums)} if nums else {"tag": t})
    return out

def block(text, eff_text=None):
    b = {"text": text}
    if eff_text is not None: b["effects"] = effects_of(eff_text) + refs_of(eff_text)
    tg = tags_of(text)
    if tg: b["tags"] = tg
    return b

def kai2_names():
    """城娘一覧/改弐 ページに載っている（改弐が実装済みの）城娘名"""
    names = set()
    for t in tables("城娘一覧/改弐"):
        for r in t:
            for c in r:
                for n in c.split("\n"):
                    n = n.strip()
                    if n and n not in ("*", "/") and not re.match(r"^(★\d|\d{4}/|\[改弐\])", n): names.add(n)
    return names

def build_units():
    units, stats = parse()
    has_kai2 = kai2_names()
    pages = skill_pages()
    out = []
    for no, u in units.items():
        st = stats.get(no, {})
        stage = {"弐": "弐", "壱": "壱"}.get(u["kai"], "無")
        if u["name"] in has_kai2 and "弐" in st: stage = "弐"
        vals = st.get(stage) or st.get("壱") or st.get("無")
        vals = vals if vals and len(vals) >= 5 else [None] * 5
        form_l, held_l = [], []
        for line in u["form"].split("\n"):
            if line: (held_l if line.startswith("[所持]") else form_l).append(line)
        fp = pages["編成特技"].get(u["name"])
        if fp:
            form_text = "\n".join(f"【{n}】{e}" for n, e in fp)
            form_eff = "\n".join(e for n, e in fp)
        else:
            form_text = "\n".join(form_l)
            form_eff = "\n".join(l.replace("[編成]", "") for l in form_l)
        sp = pages["特殊能力"].get(u["name"], [])
        strat_lines = [l for l in u["strat"].split("\n") if l]
        first = strat_lines[0] if strat_lines else "なし"
        # 複数武器は分割し、標準の武器種以外（コラボ等）は「その他」にまとめる
        weapons = list(dict.fromkeys(w if w in WEAPONS else "その他" for w in u["weapon"].split("/") if w))
        far = any(w in FAR for w in weapons) or any(w in BOTH for w in weapons)
        near = any(w not in FAR for w in weapons)
        rng_kind = "両" if (far and near) or any(w in BOTH for w in weapons) else "遠" if far else "近"
        out.append(dict(id=no, name=u["name"], rarity=u["rarity"], kai=u["kai"], attr=u["attr"],
            weapon="/".join(weapons), weapons=weapons, weaponRaw=u["weapon"], range=rng_kind,
            hp=vals[0], atk=vals[1], **{"def": vals[2]}, rng=vals[3], heal=vals[4],
            skill=block(u["skill"], u["skill"]),
            strategy=block(u["strat"], re.sub(r"^\[\d+s\]", "", first)),
            formation=block(form_text, form_eff),
            held=block("\n".join(held_l), "\n".join(l.replace("[所持]", "") for l in held_l)),
            specialAttack=block(u["special"]),
            kai2Missing=(u["name"] in has_kai2 and u["kai"] != "弐") or None,
            specialAbility=block("\n".join(f"【{n}】{e}" for n, e in sp), "\n".join(e for n, e in sp))))
    for u in out:
        for k in ("skill", "strategy", "formation", "held", "specialAbility"):
            for e in u[k].get("effects", []):
                r = e.get("ref")
                if r and r["frm"] == "giver" and u.get(r["stat"]) is not None:
                    e["value"] = int(u[r["stat"]] * r["pct"] / 100)
    return out


# ---- 公開用（GitHub Pages）: 説明文を効果の要約に置き換えて書き出す ----
EFF_LABEL = {"atk_pct": ("攻撃", "%", "+"), "atk_flat": ("攻撃", "", "+"), "def_pct": ("防御", "%", "+"), "def_flat": ("防御", "", "+"),
    "hp_pct": ("耐久", "%", "+"), "hp_flat": ("耐久", "", "+"), "rng_pct": ("射程", "%", "+"), "rng_flat": ("射程", "", "+"),
    "heal_pct": ("回復", "%", "+"), "heal_flat": ("回復", "", "+"), "dmg_up": ("与ダメージ", "%", "+"), "dmg_up2": ("与えるダメージ", "%", "+"),
    "speed": ("攻撃速度", "%", "+"), "gap": ("隙短縮", "%", ""), "dmg_cut": ("被ダメ軽減", "%", ""), "def_ignore": ("防御無視", "%", ""),
    "kobu_mult": ("鼓舞効果", "%", "+"), "enemy_taken": ("被ダメ上昇", "%", ""), "enemy_def": ("防御低下", "%", ""), "enemy_def_flat": ("防御低下", "", ""),
    "enemy_atk": ("攻撃低下", "%", ""), "enemy_atk_flat": ("攻撃低下", "", ""), "enemy_dealt": ("与ダメ低下", "%", ""),
    "enemy_slow": ("移動速度低下", "%", ""), "enemy_rng": ("射程低下", "%", "")}
STAT_JA = {"atk": "攻撃", "def": "防御", "hp": "耐久", "rng": "射程", "heal": "回復"}
TARGET_JA = {"self": "自身", "all": "全体", "inrange": "射程内", "near": "近接", "far": "遠隔", "target": "対象", "enemy": "敵"}

def target_ja(t):
    if t in TARGET_JA: return TARGET_JA[t]
    if t.startswith("weapon:"): return t[7:].replace("|", "・") + "城娘"
    if t.startswith("attr:"): return t[5:] + "属性"
    if t.startswith("other:"): return t[6:]
    return t

def summarize(block):
    text = (block or {}).get("text") or ""
    if not text or text == "なし": return text
    parts = []
    for e in block.get("effects") or []:
        lab = EFF_LABEL.get(e["type"])
        if not lab: continue
        name, unit, sign = lab
        if e.get("ref"):
            r = e["ref"]
            who = "各自" if r["frm"] == "recv" else "提供者"
            body = f"{name}{'+' if sign else ''}（{who}の{STAT_JA[r['stat']]}の{r['pct']}%）"
            if e.get("kobu"): body = "鼓舞 " + body
        elif e["type"] == "def_ignore" and e["value"] >= 100: body = "防御無視"
        else: body = f"{name}{sign}{e['value']}{unit}" if sign else f"{name} {e['value']}{unit}"
        parts.append(f"{target_ja(e.get('target') or 'self')} {body}" + ("（重複）" if e.get("stack") else "") + ("（条件付き）" if e.get("cond") else ""))
    tags = [t["tag"] + (str(t["value"]) if t.get("value") else "") for t in block.get("tags") or []]
    cd = re.match(r"\[(\d+)s\]", text)
    out = (f"[{cd.group(1)}s]" if cd else "") + "、".join(parts)
    if tags: out += ("／" if parts else "") + "、".join(tags)
    return out or "（数値化できない効果。詳細はwikiを参照）"

def public_units(units):
    out = []
    for u in units:
        v = dict(u)
        for k in ("skill", "strategy", "formation", "held", "specialAbility", "specialAttack"):
            b = u.get(k) or {}
            nb = {"text": summarize(b)}
            if b.get("effects"): nb["effects"] = b["effects"]
            if b.get("tags"): nb["tags"] = b["tags"]
            v[k] = nb
        out.append(v)
    return out

PWA_MANIFEST = {"name": "城プロRE 編成補助", "short_name": "城プロ編成", "start_url": "./", "scope": "./", "display": "standalone",
    "background_color": "#f6f4ef", "theme_color": "#8a3b2e", "lang": "ja",
    "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
              {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}

PWA_SW = r"""// 自動生成: build.py --pwa
const CACHE = "shiro-__HASH__";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-192.png", "icon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  const isData = new URL(req.url).pathname.endsWith("/data.json");
  if (isData) {   // データは新しいものを優先し、圏外なら前回のものを使う
    e.respondWith(fetch(req, { cache: "no-cache" }).then(r => { const c = r.clone(); caches.open(CACHE).then(x => x.put(req, c)); return r; })
      .catch(() => caches.match(req)));
    return;
  }
  e.respondWith(caches.match(req).then(hit => {
    const net = fetch(req).then(r => { if (r.ok) { const c = r.clone(); caches.open(CACHE).then(x => x.put(req, c)); } return r; }).catch(() => hit);
    return hit || net;
  }));
});
"""

def build_pwa(units, outdir):
    import hashlib
    os.makedirs(outdir, exist_ok=True)
    pub = public_units(units)
    body = json.dumps(pub, ensure_ascii=False, separators=(",", ":"))
    h = hashlib.md5(body.encode("utf-8")).hexdigest()[:8]
    dpath = os.path.join(outdir, "data.json")
    prev = None
    if os.path.exists(dpath):
        try: prev = json.load(open(dpath, encoding="utf-8"))
        except Exception: prev = None
    changed = not (prev and prev.get("hash") == h)
    if changed:
        old_ids = {u["id"] for u in prev["units"]} if prev else set()
        added = [u["name"] for u in pub if prev and u["id"] not in old_ids][:30]
        meta = {"version": datetime.date.today().isoformat() + "-" + h, "hash": h, "built": datetime.date.today().isoformat(), "count": len(pub),
                "added": added, "units": pub}
        with open(dpath, "w", encoding="utf-8") as f: json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    else:
        meta = prev
    html_p = (TEMPLATE_HTML
        .replace("const WIKI_UNITS = /*DATA*/[];", "let WIKI_UNITS = []; const PWA_MODE = true;")
        .replace("<title>城プロRE 編成補助</title>", '<title>城プロRE 編成補助</title>\n<link rel="manifest" href="manifest.webmanifest">\n<meta name="theme-color" content="#8a3b2e">\n<link rel="icon" href="icon-192.png">\n<link rel="apple-touch-icon" href="icon-192.png">')
        .replace("データ: 城プロRE攻略wiki（scre.swiki.jp）の全城娘一覧・ステータス一覧/能力値（DATA_DATE 取得）。効果は説明文から自動で読み取ったもので、読み違いがあり得ます。",
                 "データ: 城プロRE攻略wiki（scre.swiki.jp）より（" + meta["built"] + " 取得）。特技・計略などは効果の要約で、原文はwikiを参照してください。効果は自動で読み取ったもので、読み違いがあり得ます。非公式の個人制作ツールです。"))
    assert "PWA_MODE = true" in html_p and "manifest.webmanifest" in html_p and "非公式の個人制作" in html_p
    hh = hashlib.md5((html_p + PWA_SW).encode("utf-8")).hexdigest()[:8]
    def w(name, text):
        p = os.path.join(outdir, name)
        if os.path.exists(p) and open(p, encoding="utf-8").read() == text: return
        with open(p, "w", encoding="utf-8") as f: f.write(text)
    w("index.html", html_p)
    w("sw.js", PWA_SW.replace("__HASH__", hh))
    w("manifest.webmanifest", json.dumps(PWA_MANIFEST, ensure_ascii=False, indent=1))
    w(".nojekyll", "")
    return meta, changed

def main():
    if "--offline" not in sys.argv: fetch()
    units = build_units()
    if len(units) < 500: raise RuntimeError(f"城娘が{len(units)}体しか読み取れませんでした。wikiの表の形が変わった可能性があります")
    data = json.dumps(units, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html_t = TEMPLATE_HTML.replace("/*DATA*/[]", data).replace("DATA_DATE", datetime.date.today().isoformat())
    prev = None
    if os.path.exists(OUT):
        m = re.search(r"const WIKI_UNITS = (\[.*?\]);\n</script>", open(OUT, encoding="utf-8").read(), re.S)
        if m: prev = {u["id"] for u in json.loads(m.group(1).replace("<\\/", "</"))}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write(html_t)
    os.replace(tmp, OUT)
    added = [u["name"] for u in units if prev is not None and u["id"] not in prev]
    if "--pwa" in sys.argv:
        pdir = sys.argv[sys.argv.index("--pwa") + 1]
        meta, chg = build_pwa(units, pdir)
        print(f"PWA: {pdir} に書き出し（データ{'更新' if chg else '変更なし'}、{meta['count']}体）")
    msg = f"{datetime.datetime.now():%Y-%m-%d %H:%M} {len(units)}体を書き出し" + (f"、新規 {len(added)}体: " + "、".join(added) if added else "")
    print(msg)
    with open(LOG, "a", encoding="utf-8") as f: f.write(msg + "\n")
    if added and sys.platform == "darwin":
        note = ("新しい城娘: " + "、".join(added[:5]) + (" ほか" if len(added) > 5 else "")).replace('"', "")
        os.system(f"osascript -e 'display notification \"{note}\" with title \"城プロ編成補助を更新しました\"' >/dev/null 2>&1")

def _run():
    try:
        main()
    except Exception as e:
        with open(LOG, "a", encoding="utf-8") as f: f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} 失敗: {e}\n")
        raise


# ---- ツールの画面（データ部分は /*DATA*/[] に差し込む） ----
TEMPLATE_HTML = r'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>城プロRE 編成補助</title>
<style>
  :root {
    --bg: #f6f4ef; --panel: #fff; --ink: #222; --muted: #6b6b6b; --line: #ddd8cc;
    --accent: #8a3b2e; --ok: #2f7a43; --warn: #b26a00; --bad: #b3261e;
    --attr-平: #7a8f3a; --attr-平山: #5f7d55; --attr-山: #7b5a36; --attr-水: #2e6fa8; --attr-地獄: #6d2b8f; --attr-無: #777;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, "Hiragino Sans", "Noto Sans JP", sans-serif; background: var(--bg); color: var(--ink); font-size: 14px; }
  header { padding: 12px 20px; background: var(--accent); color: #fff; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  header h1 { font-size: 18px; margin: 0; }
  header .note { font-size: 12px; opacity: .85; }
  .top { padding: 16px 16px 0; }
  .top section.panel { margin-bottom: 0; }
  main { display: grid; grid-template-columns: 400px 1fr; gap: 16px; padding: 16px; }
  @media (max-width: 1000px) { main { grid-template-columns: minmax(0, 1fr); } }
  main > div { min-width: 0; }
  .unit-row .grow > div { overflow-wrap: anywhere; }
  .unit-row .tag { white-space: normal; }
  section.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; margin-bottom: 16px; }
  section.panel h2 { font-size: 15px; margin: 0 0 10px; border-left: 4px solid var(--accent); padding-left: 8px; }
  .filters { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; }
  .filters input, .filters select, select, input[type=number] { width: 100%; padding: 5px 6px; border: 1px solid var(--line); border-radius: 4px; font: inherit; background: #fff; }
  .filters .full { grid-column: 1 / -1; }
  button { font: inherit; padding: 5px 10px; border: 1px solid var(--accent); background: #fff; color: var(--accent); border-radius: 4px; cursor: pointer; }
  button.primary { background: var(--accent); color: #fff; }
  button:disabled { opacity: .4; cursor: default; }
  button.small { padding: 2px 7px; font-size: 12px; }
  .btnlike { display: inline-block; padding: 5px 10px; border: 1px solid var(--accent); background: var(--accent); color: #fff; border-radius: 4px; cursor: pointer; }
  .unit-list { max-height: 65vh; overflow: auto; border-top: 1px solid var(--line); }
  .unit-row { display: flex; align-items: center; gap: 8px; padding: 6px 2px; border-bottom: 1px solid var(--line); }
  .unit-row .name { font-weight: 600; }
  .unit-row .meta { color: var(--muted); font-size: 12px; }
  .unit-row .grow { flex: 1; min-width: 0; }
  .tag { display: inline-block; font-size: 11px; padding: 0 6px; border-radius: 10px; color: #fff; margin-right: 3px; line-height: 18px; white-space: nowrap; }
  .tag.plain { background: #eee; color: #444; }
  .tag.eff { background: #f3ebe0; color: #5a3a10; }
  .tag.eff.enemy { background: #e8eef7; color: #1f4470; }
  .tag.eff.cond { border: 1px dashed #b08a50; }
  .tag.sp { background: #e6f2e8; color: #1d5a2c; }
  .gap-item.info { border-left: 5px solid #9aa7b5; }
  .gap-item.have { border-left: 5px solid var(--ok); }
  #update-banner { margin: 12px 16px 0; padding: 8px 12px; border: 1px solid var(--ok); background: #e9f4ec; border-radius: 8px; font-size: 13px; display: flex; gap: 8px; align-items: flex-start; }
  #update-banner[hidden] { display: none; }
  #update-banner button { margin-left: auto; flex: none; }
  .buff-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 8px; }
  .bcard { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; font-size: 12.5px; min-width: 0; }
  .bcard h3 { margin: 0 0 4px; font-size: 13.5px; }
  .bline { padding: 3px 0; border-top: 1px dotted var(--line); overflow-wrap: anywhere; }
  .bline .k { display: inline-block; min-width: 5.5em; font-weight: 600; margin-right: 6px; }
  .src { color: var(--muted); font-size: 11.5px; }
  .down { color: var(--bad); font-weight: 600; }
  .sp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 8px; }
  .slots { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  @media (max-width: 700px) { .slots { grid-template-columns: repeat(2, 1fr); } }
  .slot { border: 1px dashed var(--line); border-radius: 6px; padding: 8px; min-height: 74px; font-size: 12px; position: relative; }
  .slot.filled { border-style: solid; background: #fcfbf8; }
  .slot .name { font-weight: 600; font-size: 13px; padding-right: 20px; }
  .slot .x { position: absolute; top: 4px; right: 4px; }
  .slot label { display: block; margin-top: 4px; color: var(--muted); }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { border: 1px solid var(--line); padding: 5px 6px; vertical-align: top; text-align: left; }
  th { background: #f1ede4; white-space: nowrap; }
  td.num, th.num { text-align: right; white-space: nowrap; }
  td.txt { min-width: 180px; }
  .scroll { overflow-x: auto; }
  .up { color: var(--ok); font-weight: 600; }
  .muted { color: var(--muted); }
  .over { text-decoration: line-through; color: var(--muted); }
  .gap-item { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
  .gap-item.missing { border-left: 5px solid var(--bad); }
  .gap-item.partial { border-left: 5px solid var(--warn); }
  .gap-item.ok { border-left: 5px solid var(--ok); }
  .gap-item h3 { margin: 0 0 4px; font-size: 13.5px; }
  .cand { display: flex; gap: 8px; align-items: center; padding: 3px 0; font-size: 12.5px; flex-wrap: wrap; }
  .settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px 16px; }
  .settings label { display: flex; gap: 6px; align-items: center; }
  .settings label input[type=number] { width: 90px; }
  textarea { width: 100%; min-height: 300px; font-family: ui-monospace, monospace; font-size: 12px; border: 1px solid var(--line); border-radius: 4px; padding: 6px; }
  dialog { border: 1px solid var(--line); border-radius: 8px; width: min(900px, 95vw); }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  details summary { cursor: pointer; }
  a { color: var(--accent); }
  ul.rules { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: var(--muted); }
  @media (max-width: 700px) {
    body { font-size: 13px; }
    header { padding: 8px 12px; }
    header .note { font-size: 11px; }
    .top { padding: 8px 8px 0; }
    main { padding: 8px; gap: 8px; }
    section.panel { padding: 10px; margin-bottom: 8px; }
    .unit-list { max-height: 55vh; }
    .slot { min-height: 0; }
    button.small { padding: 4px 9px; }
  }
</style>
</head>
<body>
<header>
  <h1>城プロRE 編成補助</h1>
  <span class="note">データ: 城プロRE攻略wiki（scre.swiki.jp）の全城娘一覧・ステータス一覧/能力値（DATA_DATE 取得）。効果は説明文から自動で読み取ったもので、読み違いがあり得ます。</span>
</header>

<div id="update-banner" hidden></div>
<div class="top">
  <section class="panel">
    <h2>編成（最大8体）</h2>
    <div class="row" style="margin-bottom:8px">
      <label id="shot-wrap" hidden><span class="btnlike">スクショから読み込む</span><input type="file" id="shot" accept="image/*" hidden></label>
      <input id="bulk" placeholder="名前をまとめて入力（読点・改行区切り）" style="flex:1;min-width:200px;padding:5px 6px;border:1px solid var(--line);border-radius:4px;font:inherit">
      <button id="bulk-go">名前で読み込む</button>
      <button id="clear-party">編成を空にする</button>
    </div>
    <div id="import-msg" class="muted" style="font-size:12px;margin-bottom:6px"></div>
    <div class="slots" id="slots"></div>
  </section>
</div>
<main>
  <div>
    <section class="panel">
      <h2>城娘を探す</h2>
      <div class="filters">
        <input id="f-name" class="full" placeholder="名前・特技/計略の文章で検索">
        <select id="f-attr"></select>
        <select id="f-weapon"></select>
        <select id="f-range"><option value="">近/遠: すべて</option><option>近</option><option>遠</option><option>両</option></select>
        <select id="f-rarity"></select>
        <select id="f-effect" class="full"></select>
        <select id="f-tag" class="full"></select>
        <select id="f-target" class="full">
          <option value="">効果の対象: すべて</option>
          <option value="team">味方全体・射程内に効くもの</option>
          <option value="self">自身のみ</option>
          <option value="enemy">敵へのデバフ</option>
        </select>
        <select id="f-sort" class="full">
          <option value="no">並び: 図鑑No.</option>
          <option value="name">並び: 名前</option>
          <option value="atk">並び: 攻撃（高い順）</option>
          <option value="def">並び: 防御（高い順）</option>
          <option value="hp">並び: 耐久（高い順）</option>
          <option value="rng">並び: 射程（長い順）</option>
          <option value="rarity">並び: レア度（高い順）</option>
          <option value="effect">並び: 選んだ効果の値（高い順）</option>
        </select>
      </div>
      <div class="muted" id="list-count"></div>
      <div class="unit-list" id="unit-list"></div>
    </section>

    <section class="panel">
      <h2>データ管理</h2>
      <div class="row">
        <button id="btn-edit">JSONを編集 / 読み込み</button>
        <button id="btn-export">JSONを書き出し</button>
        <button id="btn-copy">JSONをコピー</button>
        <button id="btn-reset">wikiデータに戻す</button>
      </div>
      <p class="muted" style="font-size:12px">効果の読み違いを直したいときは「JSONを編集」で該当城娘の effects を書き換えてください。編集したデータはこのブラウザに保存されます。</p>
    </section>
  </div>

  <div>
    <section class="panel">
      <h2>一覧</h2>
      <div class="scroll"><table id="overview"></table></div>
      <p class="muted" style="font-size:12px;margin-bottom:0">茶色・青のタグが計算に使っている効果、緑のタグが隠密無効や足止め数などの特殊効果です（点線枠は「〜する度に」などの条件付きで、上限値で計算）。</p>
    </section>

    <section class="panel">
      <h2>各城娘に実際にかかるバフ（全員が互いの射程内にいる前提）</h2>
      <p class="muted" style="font-size:12px;margin-top:0">範囲バフと単体バフのうち計算式どおり有効になるものだけを、提供元と一緒に表示します。割合は同系統で一番高いもの（範囲より高い単体バフがあればそちら）、固定値と「+（〇〇の攻撃の35%）」の変換・鼓舞は全て加算です。</p>
      <div class="buff-grid" id="buffs"></div>
      <h3 style="font-size:14px;margin:14px 0 6px">敵へのデバフ（全て適用した値）</h3>
      <div id="debuffs"></div>
    </section>

    <section class="panel">
      <h2>計略のオン/オフによる変化</h2>
      <div id="strat-sum" class="scroll"></div>
      <div id="strat-diff" style="margin-top:8px"></div>
    </section>

    <section class="panel">
      <h2>参考: 初期値での能力値計算</h2>
      <details><summary style="font-size:12px">初期値（Lv・武器・巨大化なし）で計算した実数値を見る</summary>
      <div class="scroll" style="margin-top:6px"><table id="calc"></table></div></details>
      <details style="margin-top:8px">
        <summary>適用されたバフ/デバフの内訳（重複・上書きの判定）</summary>
        <div id="breakdown" style="margin-top:8px"></div>
      </details>
    </section>

    <section class="panel">
      <h2>不足しているバフ/デバフと補える候補</h2>
      <div class="row" style="margin-bottom:8px">
        <label>候補の属性:
          <select id="g-attr" style="width:auto"></select>
        </label>
        <label>候補の最低レア:
          <select id="g-rar" style="width:auto"><option value="0">指定なし</option><option>5</option><option>6</option><option>7</option></select>
        </label>
      </div>
      <div id="gaps"></div>
    </section>

    <section class="panel">
      <h2>計算ルールと設定</h2>
      <div class="settings">
        <label>敵の防御 <input type="number" id="s-edef" min="0"></label>
        <label>敵の攻撃 <input type="number" id="s-eatk" min="0"></label>
        <label>巨大化回数（鎌の防御無視に使用） <input type="number" id="s-giant" min="0" max="5"></label>
        <label><input type="checkbox" id="s-cond"> 条件付き効果（〜する度に、撃破時など）も上限値で含める</label>
        <label><input type="checkbox" id="s-target"> 計略の「対象の〜」を発動者自身に掛けたものとして扱う</label>
      </div>
      <h3 style="font-size:13.5px;margin:12px 0 4px">スクショ読み取り（任意）</h3>
      <div class="settings">
        <label>Anthropic APIキー <input type="password" id="s-key" autocomplete="off" placeholder="sk-ant-..." style="width:100%"></label>
        <label>モデル <select id="s-model" style="width:auto"><option value="claude-haiku-5-5">Haiku 5.5（安い・1回0.03円ほど）</option><option value="claude-sonnet-5-5">Sonnet 5.5（高精度・1回1円弱）</option></select></label>
      </div>
      <p class="muted" style="font-size:12px;margin:4px 0 0">キーはこの端末のブラウザにだけ保存され、スクショを読み取るときにAnthropicへ直接送られます（このツールの運営側には送られません）。キーは専用のものを作り、Consoleで使用量を確認できる状態にしておくのがおすすめです。</p>
      <ul class="rules">
        <li>同じ種類の割合バフ/デバフは、一番高いものだけ有効（説明文に「重複」とあるものは加算）。固定値は全て加算。</li>
        <li>編成特技・所持特技・特技/計略は別系統なので、割合バフは系統ごとに掛け算で重なる。</li>
        <li>攻撃 = ((初期攻撃×(1+編成%)＋編成固定)×(1+所持%)) ×(1+特技計略%)＋固定値、その後に計略などの攻撃倍率。乗算ごとに端数切り捨て。</li>
        <li>ダメージ = (攻撃 − 敵防御) ×(1+与ダメ増)×(1+敵の被ダメ増)×(1+与えるダメージ増)。最低20。法術・鈴・杖・祓串は防御無視。</li>
        <li>敵防御 = (防御×(1−特技計略の防御低下%) − 固定値低下) ×(1−防御無視%)。防御無視は特技計略の最大値＋鎌の武器種特性を加算。</li>
        <li>変換バフ（「攻撃に防御の50%の値を加算」）と鼓舞バフ（「自身の攻撃の35%の値を射程内の城娘に加算」）は、割合・固定値の後に加算。加算元は他のバフ適用後の値。鼓舞は提供者自身には掛からないものとして計算。</li>
        <li>攻撃速度・隙短縮は系統ごとに乗算。射程の位置関係は考慮せず、「射程内」の効果は全員に届くものとして扱う。</li>
        <li>能力値は改壱・改弐のある城娘は一番上の段階の初期値。特殊能力は「特殊能力発動中」にチェックしたときだけ計算に入る。</li>
        <li>出典: wiki「検証」ページの「ステータス計算式」「ダメージ計算式」「特技・計略・武器の重複、競合」。巨大化補正・地形・装備・武器効果は未反映。</li>
      </ul>
    </section>
  </div>
</main>

<dialog id="dlg">
  <h3 style="margin-top:0">ユニットデータ（JSON）</h3>
  <details>
    <summary>データ形式の説明</summary>
<pre id="fmt" style="font-size:12px;white-space:pre-wrap">配列の各要素が1体です。
{ "id": "図鑑No.", "name": "名前", "rarity": 7, "kai": "壱",
  "attr": ["平山","水"], "weapon": "弓", "range": "遠",   // range は 近 / 遠 / 両
  "hp": 1000, "atk": 200, "def": 80, "rng": 260, "heal": 10, // 初期値
  "skill":     { "text": "特技の説明", "effects": [ ... ] },
  "strategy":  { "text": "計略の説明", "effects": [ ... ] },
  "formation": { "text": "編成特技", "effects": [ ... ] },
  "held":      { "text": "所持特技", "effects": [ ... ] },
  "specialAttack": { "text": "大破特技・特殊攻撃" },
  "specialAbility": { "text": "特殊能力", "effects": [ ... ] } }
各ブロックの "tags": [{ "tag": "足止め数増加", "value": 2 }] は隠密無効などの特殊効果です。
effects の各要素: { "type": 種類, "value": 数値, "target": 対象, "stack": 重複するなら true, "cond": 条件付きなら true }
種類: EFFECT_LIST
対象: self(自身) / all(全城娘) / inrange(射程内) / near(近接) / far(遠隔) / target(計略の対象) / enemy(敵)
      / weapon:弓|鉄砲 / attr:水 / other:地域名など(計算対象外)</pre>
  </details>
  <textarea id="dlg-text"></textarea>
  <div class="row" style="justify-content:flex-end;margin-top:8px">
    <span id="dlg-err" style="color:var(--bad)"></span>
    <button id="dlg-cancel">閉じる</button>
    <button class="primary" id="dlg-save">保存して読み込む</button>
  </div>
</dialog>

<script>
const WIKI_UNITS = /*DATA*/[];
</script>
<script>
// ---- 効果の定義 ----
const EFFECTS = {
  atk_pct:     { label: "攻撃上昇",           unit: "%" },
  atk_flat:    { label: "攻撃上昇(固定)",     unit: "" },
  atk_mult:    { label: "攻撃倍率",           unit: "%" },
  def_pct:     { label: "防御上昇",           unit: "%" },
  def_flat:    { label: "防御上昇(固定)",     unit: "" },
  hp_pct:      { label: "耐久上昇",           unit: "%" },
  hp_flat:     { label: "耐久上昇(固定)",     unit: "" },
  rng_pct:     { label: "射程上昇",           unit: "%" },
  rng_flat:    { label: "射程上昇(固定)",     unit: "" },
  heal_pct:    { label: "回復上昇",           unit: "%" },
  heal_flat:   { label: "回復上昇(固定)",     unit: "" },
  dmg_up:      { label: "与ダメージ上昇",     unit: "%" },
  dmg_up2:     { label: "与えるダメージ上昇", unit: "%" },
  speed:       { label: "攻撃速度上昇",       unit: "%" },
  gap:         { label: "攻撃後の隙短縮",     unit: "%" },
  dmg_cut:     { label: "被ダメージ軽減",     unit: "%" },
  def_ignore:  { label: "防御無視",           unit: "%" },
  kobu_mult:   { label: "鼓舞効果上昇",       unit: "%" },
  enemy_taken: { label: "敵の被ダメージ上昇", unit: "%", enemy: true },
  enemy_def:   { label: "敵の防御低下",       unit: "%", enemy: true },
  enemy_def_flat: { label: "敵の防御低下(固定)", unit: "", enemy: true },
  enemy_atk_flat: { label: "敵の攻撃低下(固定)", unit: "", enemy: true },
  enemy_atk:   { label: "敵の攻撃低下",       unit: "%", enemy: true },
  enemy_dealt: { label: "敵の与ダメージ低下", unit: "%", enemy: true },
  enemy_slow:  { label: "敵の移動速度低下",   unit: "%", enemy: true },
  enemy_rng:   { label: "敵の射程低下",       unit: "%", enemy: true },
};
const GAP_CHECKS = [
  { types: ["atk_pct"],                 why: "火力の土台。全体・射程内の割合攻撃バフ" },
  { types: ["dmg_up"],                  why: "攻撃上昇とは別系統で掛け算になるため、攻撃上昇だけより伸びが大きい" },
  { types: ["enemy_taken"],             why: "敵側のデバフ。与ダメージ上昇とも別系統で掛け算" },
  { types: ["enemy_def", "enemy_def_flat"], why: "防御の高い敵への実ダメージを大きく伸ばす（術攻撃の城娘には不要）" },
  { types: ["speed", "gap"],            why: "手数を増やす。攻撃速度と隙短縮は重複する" },
  { types: ["dmg_cut", "enemy_atk", "enemy_dealt"], why: "耐久面。被ダメージ軽減か、敵の攻撃・与ダメージ低下" },
  { types: ["heal_flat", "heal_pct"],   why: "長期戦の維持" },
];
const SOURCES = [["skill","特技"],["strategy","計略"],["formation","編成特技"],["held","所持特技"],["specialAbility","特殊能力"]];
const TAG_SOURCES = [...SOURCES, ["specialAttack","大破・特殊攻撃"]];
const GROUP_OF = { skill: "normal", strategy: "normal", formation: "formation", held: "held", specialAbility: "normal" };
// 不足チェックで有無を見る特殊効果
const SP_CHECKS = [
  { tags: ["隠密無効"],                 why: "隠密状態の敵を攻撃できるようにする" },
  { tags: ["状態異常無効", "状態異常回復", "火傷無効", "猛毒無効", "氷結無効"], why: "火傷・猛毒・氷結などへの対策" },
  { tags: ["足止め数増加"],             why: "近接城娘がより多くの敵を止められる" },
  { tags: ["範囲・貫通攻撃"],           why: "敵の群れをまとめて処理する" },
  { tags: ["攻撃対象数増加"],           why: "一度に複数の敵を攻撃する" },
  { tags: ["敵から狙われない"],         why: "隠密状態（攻撃対象にならない）で被害を避ける" },
  { tags: ["味方の耐久回復", "与ダメージ吸収"], why: "耐久の回復手段" },
  { tags: ["計略短縮"],                 why: "計略の回転を早める" },
  { tags: ["気増加", "巨大化気軽減"],   why: "気の確保・巨大化を早める" },
  { tags: ["対飛行"],                   why: "飛行敵への対策" },
  { tags: ["対妖怪", "術攻撃"],         why: "妖怪（物理半減）への対策" },
];
const MAGIC = ["法術", "鈴", "杖", "祓串"];
const WIKI = "https://scre.swiki.jp/index.php?";

// ---- 状態 ----
const LS_UNITS = "shiroRe.v2.units", LS_PARTY = "shiroRe.v2.party", LS_SET = "shiroRe.v2.settings";
let units = loadJSON(LS_UNITS) || WIKI_UNITS;
let party = loadJSON(LS_PARTY) || [];
let settings = Object.assign({ edef: 300, eatk: 1000, giant: 5, cond: true, target: true }, loadJSON(LS_SET) || {});
let edited = !!loadJSON(LS_UNITS);

function loadJSON(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } }
function save() {
  try {
    localStorage.setItem(LS_PARTY, JSON.stringify(party));
    localStorage.setItem(LS_SET, JSON.stringify(settings));
    if (edited) localStorage.setItem(LS_UNITS, JSON.stringify(units)); else localStorage.removeItem(LS_UNITS);
  } catch {}
}
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const byId = id => units.find(u => u.id === id);
const attrColor = a => getComputedStyle(document.documentElement).getPropertyValue("--attr-" + a).trim() || "#999";
const attrTags = u => (u.attr || []).map(a => `<span class="tag" style="background:${attrColor(a)}">${esc(a)}</span>`).join("");
const STAT_JA = { atk: "攻撃", def: "防御", hp: "耐久", rng: "射程", heal: "回復" };
const fmtVal = e => e.type === "def_ignore" && e.value >= 100 ? "" : " " + e.value + (EFFECTS[e.type]?.unit ?? "");
const refText = e => `${e.ref.frm === "recv" ? "各自" : "提供者"}の${STAT_JA[e.ref.stat]}の${e.ref.pct}%${e.kobu ? "（鼓舞）" : ""}`;
const effText = e => e.ref ? `${(EFFECTS[e.type]?.label ?? e.type).replace("(固定)", "")} ${refText(e)}` : `${EFFECTS[e.type]?.label ?? e.type}${fmtVal(e)}${e.stack ? "（重複）" : ""}`;
const targetText = t => ({ self:"自身", all:"全体", inrange:"射程内", near:"近接", far:"遠隔", target:"対象1体", enemy:"敵" }[t]
  ?? t.replace("weapon:", "").replace(/\|/g, "・").replace("attr:", "").replace("other:", "") + "城娘");
const effTag = e => `<span class="tag eff${EFFECTS[e.type]?.enemy ? " enemy" : ""}${e.cond ? " cond" : ""}">${esc(targetText(e.target || "self"))}:${esc(effText(e))}</span>`;
const fl = Math.floor;
const weaponsOf = u => u.weapons || String(u.weapon || "").split("/");
const isMagic = u => weaponsOf(u).some(w => MAGIC.includes(w));
const k2Tag = u => u.kai2Missing ? `<span class="tag" style="background:#fbe3e1;color:#8a1c14" title="wikiの全城娘一覧に改弐の特技・計略が載っていないため、改壱の内容で計算しています">改弐の特技未取得</span>` : "";
const spTag = t => `<span class="tag sp">${esc(t.tag)}${t.value ? " " + t.value : ""}</span>`;
function allTags(u) {
  const out = [];
  for (const [key, label] of TAG_SOURCES) for (const t of (u[key]?.tags || [])) out.push({ ...t, source: key, sourceLabel: label, from: u });
  if (isMagic(u) && !out.some(t => t.tag === "術攻撃")) out.push({ tag: "術攻撃", source: "weapon", sourceLabel: "武器種", from: u });
  return out;
}

function allEffects(u) {
  const out = [];
  for (const [key, label] of SOURCES) for (const e of (u[key]?.effects || []))
    if (EFFECTS[e.type] && (settings.cond || !e.cond)) out.push({ ...e, source: key, sourceLabel: label, group: GROUP_OF[key], from: u });
  return out;
}

function hits(e, giver, recv) {
  let t = e.target || "self";
  if (t === "target") t = settings.target ? "self" : "none";
  // 鼓舞は陣貝城娘自身には掛からない
  if ((e.exSelf || e.kobu) && giver === recv) return false;
  if (t === "self") return giver === recv;
  if (t === "all" || t === "inrange") return true;
  if (t === "near") return recv.range === "近" || recv.range === "両";
  if (t === "far") return recv.range === "遠" || recv.range === "両";
  if (t.startsWith("weapon:")) return t.slice(7).split("|").some(w => weaponsOf(recv).includes(w));
  if (t.startsWith("attr:")) return (recv.attr || []).includes(t.slice(5));
  return false;
}

// 系統ごとに: 非重複の割合は最大値、重複・固定値は加算
function resolve(effs, type, group) {
  const list = effs.filter(e => e.type === type && (!group || e.group === group));
  const isFlat = type.endsWith("_flat");
  let total = 0; const used = new Set();
  list.filter(e => e.stack || isFlat).forEach(e => { total += e.value; used.add(e); });
  const others = list.filter(e => !(e.stack || isFlat));
  if (others.length) { const best = others.reduce((a, b) => (b.value > a.value ? b : a)); total += best.value; used.add(best); }
  return { total, used, list };
}
function byGroups(effs, type) {
  const g = {}; let used = new Set(), list = [];
  for (const k of ["formation", "held", "normal"]) { g[k] = resolve(effs, type, k); g[k].used.forEach(x => used.add(x)); list = list.concat(g[k].list); }
  return { ...g, used, list };
}
// 割合と固定値を、編成→所持→特技計略の順に適用
function applyStat(base, effs, pctType, flatType) {
  const p = byGroups(effs, pctType), f = byGroups(effs, flatType);
  let v = fl(base * (1 + p.formation.total / 100)) + f.formation.total;
  v = fl(v * (1 + p.held.total / 100)) + f.held.total;
  v = fl(v * (1 + p.normal.total / 100)) + f.normal.total;
  return { value: v, p, f };
}
const multGroups = (g, sign) => ["formation", "held", "normal"].reduce((acc, k) => acc * (1 + sign * g[k].total / 100), 1);
// 敵へのデバフ: 編成と所持は競合（高い方）、特技計略とは乗算
const enemyMult = (g, sign) => (1 + sign * Math.max(g.formation.total, g.held.total) / 100) * (1 + sign * g.normal.total / 100);
function enemyStat(base, pg, fg) {
  const v = fl(base * (1 - Math.max(pg.formation.total, pg.held.total) / 100)) - fg.formation.total - fg.held.total;
  return Math.max(0, fl(v * (1 - pg.normal.total / 100)) - fg.normal.total);
}
const STATS = [["atk", "atk_pct", "atk_flat"], ["def", "def_pct", "def_flat"], ["hp", "hp_pct", "hp_flat"], ["rng", "rng_pct", "rng_flat"], ["heal", "heal_pct", "heal_flat"]];

function compute(p = party) {
  const members = p.map(x => ({ ...x, u: byId(x.id) })).filter(m => m.u);
  const active = [];
  for (const m of members) for (const e of allEffects(m.u))
    if ((e.source !== "strategy" || m.strat) && (e.source !== "specialAbility" || m.sp)) active.push(e);
  const plain = active.filter(e => !e.ref), refs = active.filter(e => e.ref);

  // 1) 割合バフ・固定値バフまで（編成→所持→特技計略）
  const base = members.map(m => {
    const u = m.u, mine = plain.filter(e => e.target !== "enemy" && hits(e, e.from, u));
    const st = {};
    for (const [k, pt, ft] of STATS) st[k] = applyStat(u[k] ?? 0, mine, pt, ft);
    return { u, mine, st };
  });
  // 2) 変換バフ・鼓舞バフ（能力値依存）。加算元は他のバフ適用後の値なので、2回まわして互いの加算を反映
  const idx = new Map(base.map((b, i) => [b.u, i]));
  const s1 = () => base.map(b => Object.fromEntries(STATS.map(([k]) => [k, b.st[k].value])));
  let cur = s1(), refUsed = base.map(() => []);
  for (let pass = 0; pass < 2; pass++) {
    const next = s1(); refUsed = base.map(() => []);
    base.forEach((b, i) => {
      for (const e of refs) {
        if (e.target === "enemy" || !hits(e, e.from, b.u)) continue;
        const k = e.type.replace("_flat", "");
        if (!(k in next[i])) continue;
        const src = e.ref.frm === "recv" ? cur[i] : cur[idx.get(e.from)];
        // 「鼓舞効果が1.8倍」は提供者自身に掛かる倍率
        const km = e.kobu ? resolve(base[idx.get(e.from)]?.mine.filter(x => x.from === e.from) || [], "kobu_mult").total : 0;
        const v = fl((src?.[e.ref.stat] ?? 0) * e.ref.pct * (1 + km / 100) / 100);
        next[i][k] += v; refUsed[i].push({ ...e, value: v, pctEff: Math.round(e.ref.pct * (1 + km / 100) * 10) / 10, kmul: 1 + km / 100, orig: e });
      }
    });
    cur = next;
  }

  // 3) 敵へのデバフ（能力値依存のものは提供者の最終値から算出）
  const enemyEffs = plain.filter(e => e.target === "enemy").concat(
    refs.filter(e => e.target === "enemy").map(e => ({ ...e, value: fl((cur[idx.get(e.from)]?.[e.ref.stat] ?? 0) * e.ref.pct / 100), orig: e })));
  const enemy = {};
  for (const t of Object.keys(EFFECTS).filter(t => EFFECTS[t].enemy)) enemy[t] = byGroups(enemyEffs, t);
  const edefBase = enemyStat(settings.edef, enemy.enemy_def, enemy.enemy_def_flat);
  const eatk = enemyStat(settings.eatk, enemy.enemy_atk, enemy.enemy_atk_flat);
  const taken = Math.round((enemyMult(enemy.enemy_taken, 1) - 1) * 100);
  const dealt = Math.round((1 - enemyMult(enemy.enemy_dealt, -1)) * 100);
  const slow = Math.round((1 - enemyMult(enemy.enemy_slow, -1)) * 100);
  const erng = Math.round((1 - enemyMult(enemy.enemy_rng, -1)) * 100);

  const rows = base.map((b, i) => {
    const u = b.u, mine = b.mine.concat(refUsed[i]);
    const mult = resolve(b.mine, "atk_mult");
    const atk = fl(cur[i].atk * (1 + mult.total / 100));
    const ign = resolve(b.mine.filter(e => e.from === u), "def_ignore");
    const scythe = weaponsOf(u).includes("鎌") ? Math.min(100, 10 + 18 * settings.giant) : 0;
    const ignore = Math.min(100, ign.total + scythe);
    const magic = isMagic(u) || ignore >= 100;
    const edef = magic ? 0 : fl(edefBase * (1 - ignore / 100));
    const up = byGroups(b.mine, "dmg_up"), up2 = resolve(b.mine, "dmg_up2"), speed = byGroups(b.mine, "speed"), gap = byGroups(b.mine, "gap"), cut = byGroups(b.mine, "dmg_cut");
    const raw = Math.max(atk - edef, 20);
    const dmg = fl(raw * multGroups(up, 1) * (1 + taken / 100) * (1 + up2.total / 100));
    return { u, mine, st: b.st, refs: refUsed[i], atkS: b.st.atk, mult, atk, def: cur[i].def, hp: cur[i].hp, rng: cur[i].rng, heal: cur[i].heal,
      ign, scythe, ignore, magic, edef, dmg, upG: up, up2, speedG: speed, gapG: gap, cutG: cut,
      dmgUp: Math.round((multGroups(up, 1) - 1) * 100), dmgUp2: up2.total,
      speed: Math.round((multGroups(speed, 1) - 1) * 100), gap: Math.round((1 - multGroups(gap, -1)) * 100),
      cut: Math.round((1 - multGroups(cut, -1)) * 100) };
  });
  return { members, active, enemy, edefBase, eatk, taken, dealt, slow, erng, rows };
}

// ---- 描画 ----
function fill(sel, vals, first) {
  const cur = sel.value;
  sel.innerHTML = `<option value="">${first}</option>` + vals.map(v => `<option>${esc(v)}</option>`).join("");
  sel.value = cur;
}
function renderFilters() {
  const order = ["平", "平山", "山", "水", "地獄", "無"];
  const attrs = [...new Set(units.flatMap(u => u.attr || []))].sort((a, b) => (order.indexOf(a) + 99 * (order.indexOf(a) < 0)) - (order.indexOf(b) + 99 * (order.indexOf(b) < 0)));
  fill($("f-attr"), attrs, "属性: すべて"); fill($("g-attr"), attrs, "指定なし");
  const wl = [...new Set(units.flatMap(weaponsOf))].sort((a, b) => (a === "その他") - (b === "その他"));
  fill($("f-weapon"), wl, "武器種: すべて");
  fill($("f-rarity"), [...new Set(units.map(u => u.rarity))].sort((a, b) => b - a), "レア度: すべて");
  const fe = $("f-effect"), cur = fe.value;
  fe.innerHTML = `<option value="">持っている効果: すべて</option>` + Object.entries(EFFECTS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
  fe.value = cur;
  const tg = $("f-tag"), curT = tg.value;
  const counts = {};
  units.forEach(u => new Set(allTags(u).map(t => t.tag)).forEach(t => counts[t] = (counts[t] || 0) + 1));
  tg.innerHTML = `<option value="">特殊効果: すべて</option>` + Object.keys(counts).map(t => `<option value="${esc(t)}">${esc(t)}（${counts[t]}体）</option>`).join("");
  tg.value = curT;
}

function matchTarget(e, ft) {
  if (!ft) return true;
  if (ft === "enemy") return e.target === "enemy";
  if (ft === "self") return e.target === "self" || e.target === "target";
  return !["self", "target", "enemy"].includes(e.target) && !String(e.target).startsWith("other:");
}
function effectValue(u, type, ft) {
  return Math.max(0, ...allEffects(u).filter(e => e.type === type && matchTarget(e, ft)).map(e => e.value));
}

const LIST_MAX = 200;
function renderList() {
  const q = $("f-name").value.trim(), a = $("f-attr").value, w = $("f-weapon").value, rg = $("f-range").value,
        ra = $("f-rarity").value, ef = $("f-effect").value, ft = $("f-target").value, sort = $("f-sort").value, tgf = $("f-tag").value;
  let list = units.filter(u =>
    (!q || [u.name, u.skill?.text, u.strategy?.text, u.formation?.text, u.held?.text, u.specialAttack?.text, u.specialAbility?.text].join(" ").includes(q)) &&
    (!a || (u.attr || []).includes(a)) && (!w || weaponsOf(u).includes(w)) && (!rg || u.range === rg) &&
    (!ra || String(u.rarity) === ra) && (!tgf || allTags(u).some(t => t.tag === tgf)) &&
    (!(ef || ft) || allEffects(u).some(e => (!ef || e.type === ef) && matchTarget(e, ft))));
  const key = { atk: u => -(u.atk ?? -1), def: u => -(u.def ?? -1), hp: u => -(u.hp ?? -1), rng: u => -(u.rng ?? -1),
                rarity: u => -u.rarity, effect: u => -effectValue(u, ef, ft), no: u => Number(u.id) }[sort];
  list.sort(key ? (x, y) => key(x) - key(y) || Number(x.id) - Number(y.id) : (x, y) => x.name.localeCompare(y.name, "ja"));
  $("list-count").textContent = `${list.length} 体` + (list.length > LIST_MAX ? `（先頭${LIST_MAX}体を表示。条件で絞り込んでください）` : "");
  const full = party.length >= 8;
  $("unit-list").innerHTML = list.slice(0, LIST_MAX).map(u => {
    const inParty = party.some(p => p.id === u.id);
    const effs = allEffects(u).filter(e => (!ef || e.type === ef) && matchTarget(e, ft)).slice(0, 8).map(effTag).join("")
      + [...new Map(allTags(u).filter(t => !tgf || t.tag === tgf).map(t => [t.tag, t])).values()].map(spTag).join("");
    const stat = u.atk == null ? "能力値データなし" : `耐${u.hp} 攻${u.atk} 防${u.def} 射${u.rng}`;
    return `<div class="unit-row">
      <div class="grow">
        <div>${attrTags(u)}<span class="name">${esc(u.name)}</span> <span class="tag plain">★${u.rarity}</span><span class="tag plain">${esc(u.weapon)}</span><span class="tag plain">${esc(u.range)}</span>${k2Tag(u)}</div>
        <div class="meta">${stat}</div>
        <div>${effs}</div>
      </div>
      <button class="small" data-add="${esc(u.id)}" ${inParty || full ? "disabled" : ""}>${inParty ? "編成中" : "追加"}</button>
    </div>`;
  }).join("");
}

function renderSlots() {
  let html = "";
  for (let i = 0; i < 8; i++) {
    const p = party[i], u = p && byId(p.id);
    html += u ? `<div class="slot filled">
        <button class="small x" data-rm="${i}" title="外す">×</button>
        <div>${attrTags(u)}</div><div class="name">${esc(u.name)}</div>
        <div class="muted">★${u.rarity}・${esc(u.weapon)}・${esc(u.range)}</div>${k2Tag(u)}
        <label><input type="checkbox" data-strat="${i}" ${p.strat ? "checked" : ""}> 計略発動中として計算</label>
        ${u.specialAbility?.text ? `<label><input type="checkbox" data-sp="${i}" ${p.sp ? "checked" : ""}> 特殊能力発動中として計算</label>` : ""}
        <div>${[...new Map(allTags(u).map(t => [t.tag, t])).values()].map(spTag).join("")}</div>
      </div>` : `<div class="slot muted">空き</div>`;
  }
  $("slots").innerHTML = html;
}

function cell(block) {
  if (!block || !block.text || block.text === "なし") return '<span class="muted">-</span>';
  const tags = (block.tags || []).map(spTag).join("");
  const has = block.effects?.length || tags;
  // 公開版の text は効果の要約なので、タグがあるときはタグだけを見せる
  const text = typeof PWA_MODE !== "undefined" && has ? esc((block.text.match(/^\[\d+s\]/) || [""])[0]) : esc(block.text).replace(/\n/g, "<br>");
  return text + (has ? "<div>" + (block.effects || []).map(effTag).join("") + tags + "</div>" : "");
}
function renderOverview(res) {
  if (!res.members.length) { $("overview").innerHTML = "<tr><td class='muted'>城娘を追加すると表示されます</td></tr>"; return; }
  $("overview").innerHTML = `<tr><th>名前</th><th>属性</th><th>武器種</th><th>近/遠</th><th>特技</th><th>計略</th><th>編成特技</th><th>所持特技</th><th>大破・特殊攻撃</th><th>特殊能力</th></tr>` +
    res.members.map(({ u }) => `<tr><td><b><a href="${WIKI + encodeURIComponent(u.name)}" target="_blank" rel="noopener">${esc(u.name)}</a></b><br><span class="muted">★${u.rarity}${u.kai ? "・改" + esc(u.kai) : ""}</span>${k2Tag(u)}</td>
      <td>${attrTags(u)}</td><td>${esc(u.weapon)}${u.weaponRaw && u.weaponRaw !== u.weapon ? `<br><span class="muted">${esc(u.weaponRaw)}</span>` : ""}${isMagic(u) ? '<br><span class="muted">術攻撃</span>' : ""}</td><td>${esc(u.range)}</td>
      <td class="txt">${cell(u.skill)}</td><td class="txt">${cell(u.strategy)}</td><td class="txt">${cell(u.formation)}</td>
      <td class="txt">${cell(u.held)}</td><td class="txt">${cell(u.specialAttack)}</td><td class="txt">${cell(u.specialAbility)}</td></tr>`).join("");
}

const pc = v => v ? `<span class="up">+${v}%</span>` : '<span class="muted">-</span>';
function pctBreak(g) {
  const parts = [["編成", g.formation.total], ["所持", g.held.total], ["特技計略", g.normal.total]].filter(x => x[1]);
  return parts.length ? parts.map(([k, v]) => `<span class="up">+${v}%</span><span class="muted" style="font-size:11px">${k}</span>`).join("<br>") : '<span class="muted">-</span>';
}
function renderCalc(res) {
  if (!res.rows.length) { $("calc").innerHTML = "<tr><td class='muted'>城娘を追加すると表示されます</td></tr>"; $("breakdown").innerHTML = ""; return; }
  const e = res.enemy, tot = g => ["formation", "held", "normal"].map(k => g[k].total).filter(Boolean).join("+") || 0;
  $("calc").innerHTML = `<tr><th>名前</th><th class="num">初期攻撃</th><th class="num">攻撃%</th><th class="num">攻撃固定</th><th class="num">変換・鼓舞</th><th class="num">最終攻撃</th>
      <th class="num">最終防御</th><th class="num">最終耐久</th><th class="num">射程</th><th class="num">与ダメ</th><th class="num">攻速</th><th class="num">隙短縮</th><th class="num">被ダメ軽減</th>
      <th class="num">受ける敵防御</th><th class="num">1撃の目安</th></tr>` +
    res.rows.map(x => `<tr><td><b>${esc(x.u.name)}</b>${x.magic ? ' <span class="tag plain">防御無視</span>' : x.ignore ? ` <span class="tag plain">防御${x.ignore}%無視</span>` : ""}</td>
      <td class="num">${x.u.atk ?? "?"}</td><td class="num">${pctBreak(x.atkS.p)}</td>
      <td class="num">${(x.atkS.f.formation.total + x.atkS.f.held.total + x.atkS.f.normal.total) ? '<span class="up">+' + (x.atkS.f.formation.total + x.atkS.f.held.total + x.atkS.f.normal.total) + "</span>" : '<span class="muted">-</span>'}</td>
      <td class="num">${(() => { const v = x.refs.filter(e => e.type === "atk_flat").reduce((a, e) => a + e.value, 0); return v ? '<span class="up">+' + v + "</span>" : '<span class="muted">-</span>'; })()}</td>
      <td class="num"><b>${x.atk}</b></td><td class="num">${x.def}</td><td class="num">${x.hp}</td><td class="num">${x.rng}</td>
      <td class="num">${pc(x.dmgUp)}${x.dmgUp2 ? "<br>" + pc(x.dmgUp2) + '<span class="muted" style="font-size:11px">与える</span>' : ""}</td>
      <td class="num">${pc(x.speed)}</td><td class="num">${pc(x.gap)}</td><td class="num">${pc(x.cut)}</td>
      <td class="num">${x.edef}</td><td class="num"><b>${x.dmg}</b></td></tr>`).join("") +
    `<tr><td colspan="15" class="muted">敵: 防御 ${settings.edef} → ${res.edefBase} ／ 攻撃 ${settings.eatk} → ${res.eatk} ／ 被ダメージ +${res.taken}% ／ 与ダメージ −${res.dealt}% ／ 移動速度 −${res.slow}%。能力値は初期値（Lv・巨大化・装備なし）です。</td></tr>`;

  // 内訳
  const types = Object.keys(EFFECTS).filter(t => res.active.some(a => a.type === t));
  let html = "<table><tr><th>効果</th><th>提供元</th><th>判定</th></tr>";
  for (const t of types) {
    const list = res.active.filter(a => a.type === t);
    const used = EFFECTS[t].enemy ? new Set([...res.enemy[t].used].map(e => e.orig || e)) : new Set(res.rows.flatMap(x => {
      const r = t === "def_ignore" || t === "atk_mult" || t === "dmg_up2" ? resolve(x.mine.filter(e => t !== "def_ignore" || e.from === x.u), t) : byGroups(x.mine, t);
      return [...r.used].map(e => e.orig || e);
    }));
    html += list.map((a, i) => {
      const reach = EFFECTS[t].enemy || res.rows.some(x => x.mine.some(m => m === a || m.orig === a));
      const ok = used.has(a);
      const note = !reach ? "対象の城娘が編成にいない" : ok ? (a.stack || t.endsWith("_flat") ? "加算" : "採用") : "同系統のより高い効果に上書き";
      const grp = { formation: "編成", held: "所持", normal: "特技計略" }[a.group];
      return `<tr>${i === 0 ? `<td rowspan="${list.length}">${EFFECTS[t].label}</td>` : ""}
        <td class="${ok ? "" : "over"}">${esc(a.from.name)}（${a.sourceLabel}・${esc(targetText(a.target || "self"))}）${esc(effText(a))}${a.cond ? "（条件付き）" : ""} <span class="muted">[${grp}]</span></td>
        <td class="${ok ? "up" : "muted"}">${note}</td></tr>`;
    }).join("");
  }
  $("breakdown").innerHTML = html + "</table>";
}

// ---- 各城娘にかかるバフ（実数値ではなく「+60%」「+（〇〇の攻撃の35%）」の形で） ----
const GL = { formation: "編成", held: "所持", normal: "" };
const srcOf = (e, u) => `${esc(e.from.name)}${e.from === u ? "（自身）" : ""}・${e.sourceLabel}`;
const refWho = (e, u) => e.ref.frm === "recv" ? "各自" : e.from === u ? "自身" : esc(e.from.name);
// 1体分の有効なバフを {cat, text} の並びにする（表示と計略オン/オフの比較に共用）
function buffItems(x) {
  const u = x.u, out = [];
  const push = (cat, sign, e, unit, grp) => out.push({ cat, html: `<span class="${sign === "+" ? "up" : "down"}">${sign}${e.value}${unit}</span> <span class="src">${srcOf(e, u)}${grp && GL[grp] ? "［" + GL[grp] + "］" : ""}${e.stack ? "（重複）" : ""}${e.cond ? "（条件付き）" : ""}</span>` });
  const groups = (cat, g, unit) => { for (const k of ["formation", "held", "normal"]) if (g[k]) for (const e of g[k].used) push(cat, "+", e, unit, k); };
  for (const [k, label] of [["atk", "攻撃"], ["def", "防御"], ["hp", "耐久"], ["rng", "射程"], ["heal", "回復"]]) {
    groups(label, x.st[k].p, "%"); groups(label, x.st[k].f, "");
    for (const e of x.refs.filter(e => e.type === k + "_flat"))
      out.push({ cat: label, html: `<span class="up">+（${refWho(e, u)}の${STAT_JA[e.ref.stat]}の${e.pctEff}%）</span> <span class="src">${srcOf(e, u)}${e.kobu ? "・鼓舞" : ""}${e.kmul && e.kmul !== 1 ? `（${e.ref.pct}%×鼓舞効果${e.kmul}倍）` : ""}${e.cond ? "（条件付き）" : ""}</span>` });
  }
  groups("与ダメージ", x.upG, "%");
  for (const e of x.up2.used) push("与えるダメージ", "+", e, "%");
  groups("攻撃速度", x.speedG, "%"); groups("隙短縮", x.gapG, "%"); groups("被ダメ軽減", x.cutG, "%");
  if (isMagic(u)) out.push({ cat: "防御無視", html: `<b>術攻撃</b> <span class="src">武器種</span>` });
  else {
    for (const e of x.ign.used) out.push({ cat: "防御無視", html: e.value >= 100 ? `<b>敵の防御を無視</b> <span class="src">${srcOf(e, u)}</span>` : `<span class="up">+${e.value}%</span> <span class="src">${srcOf(e, u)}</span>` });
    if (x.scythe) out.push({ cat: "防御無視", html: `<span class="up">+${x.scythe}%</span> <span class="src">鎌の武器種特性（巨大化${settings.giant}回）</span>` });
  }
  return out;
}
function enemyItems(res) {
  const out = [], e = res.enemy;
  const add = (cat, g, unit, sign = "−") => { for (const k of ["formation", "held", "normal"]) for (const x of g[k].used)
    out.push({ cat, html: x.ref ? `<span class="down">−（${esc(x.from.name)}の${STAT_JA[x.ref.stat]}の${x.ref.pct}%）</span> <span class="src">${esc(x.from.name)}・${x.sourceLabel}${x.cond ? "（条件付き）" : ""}</span>`
      : `<span class="${sign === "+" ? "up" : "down"}">${sign}${x.value}${unit}</span> <span class="src">${esc(x.from.name)}・${x.sourceLabel}${GL[k] ? "［" + GL[k] + "］" : ""}${x.cond ? "（条件付き）" : ""}</span>` }); };
  add("防御", e.enemy_def, "%"); add("防御", e.enemy_def_flat, ""); add("攻撃", e.enemy_atk, "%"); add("攻撃", e.enemy_atk_flat, "");
  add("被ダメージ", e.enemy_taken, "%", "+"); add("与ダメージ", e.enemy_dealt, "%"); add("移動速度", e.enemy_slow, "%"); add("射程", e.enemy_rng, "%");
  return out;
}
const CATS = ["攻撃", "防御", "耐久", "射程", "回復", "与ダメージ", "与えるダメージ", "攻撃速度", "隙短縮", "被ダメ軽減", "防御無視"];
function itemLines(items, cats, empty) {
  const html = cats.map(c => { const xs = items.filter(i => i.cat === c); return xs.length ? `<div class="bline"><span class="k">${c}</span>${xs.map(i => i.html).join("<br>")}</div>` : ""; }).join("");
  return html || `<div class="muted" style="font-size:12px">${empty}</div>`;
}
function renderBuffs(res) {
  if (!res.rows.length) { $("buffs").innerHTML = "<p class='muted'>城娘を追加すると表示されます</p>"; $("debuffs").innerHTML = ""; return; }
  $("buffs").innerHTML = res.rows.map(x => `<div class="bcard"><h3>${attrTags(x.u)}${esc(x.u.name)} <span class="muted" style="font-weight:normal;font-size:11.5px">${esc(x.u.weapon)}・${esc(x.u.range)}${party.find(p => p.id === x.u.id)?.strat ? "・計略オン" : ""}</span></h3>
    ${itemLines(buffItems(x), CATS, "数値で読み取れたバフはありません")}</div>`).join("");
  $("debuffs").innerHTML = `<div class="bcard">${itemLines(enemyItems(res), ["防御", "攻撃", "被ダメージ", "与ダメージ", "移動速度", "射程"], "数値で読み取れたデバフはありません")}
    <div class="src" style="margin-top:4px">割合デバフは同系統で一番高いものだけ有効（編成と所持は競合、特技計略とは乗算）。固定値は割合の後に引きます。</div></div>`;
}

// ---- 計略のオン/オフ: オンにすると加わるバフ（緑）と、上書きされて無効になるバフ（取り消し線） ----
function renderStrat(res) {
  $("strat-sum").innerHTML = "";
  if (!res.rows.length) { $("strat-diff").innerHTML = "<p class='muted'>城娘を追加すると表示されます</p>"; return; }
  const key = i => i.cat + "|" + i.html;
  const diff = (a, b, cats) => cats.map(c => {
    const A = a.filter(i => i.cat === c), B = b.filter(i => i.cat === c);
    const ka = new Set(A.map(key)), kb = new Set(B.map(key));
    const add = B.filter(i => !ka.has(key(i))).map(i => i.html), gone = A.filter(i => !kb.has(key(i))).map(i => `<span class="over">${i.html.replace(/<[^>]+>/g, "")}</span>`);
    return add.length || gone.length ? `${c} ${[...add, ...gone].join("、")}` : "";
  }).filter(Boolean);
  $("strat-diff").innerHTML = res.members.map(m => {
    const u = m.u;
    if (!u.strategy?.text || u.strategy.text === "なし") return "";
    const alt = compute(party.map(p => p.id === u.id ? { ...p, strat: !p.strat } : p));
    const off = m.strat ? alt : res, on = m.strat ? res : alt;
    const lines = off.rows.map((x, i) => { const d = diff(buffItems(x), buffItems(on.rows[i]), CATS); return d.length ? `<div class="bline"><span class="k">${esc(x.u.name)}</span>${d.join("<br>")}</div>` : ""; }).join("");
    const el = diff(enemyItems(off), enemyItems(on), ["防御", "攻撃", "被ダメージ", "与ダメージ", "移動速度", "射程"]);
    const body = lines + (el.length ? `<div class="bline"><span class="k">敵</span>${el.join("<br>")}</div>` : "");
    return `<div class="gap-item ${body ? "have" : "info"}"><h3>${esc(u.name)}の計略 <span class="muted" style="font-weight:normal">（今: ${m.strat ? "オン" : "オフ"}）</span>
      <label style="font-weight:normal;font-size:12px;margin-left:6px"><input type="checkbox" data-strat2="${esc(u.id)}" ${m.strat ? "checked" : ""}> 発動中</label></h3>
      <div class="src">${esc(u.strategy.text.split("\n")[0])}</div>
      ${body ? `<div style="font-size:12px;margin-top:2px">オンにすると（緑が加わる効果、取り消し線はより高い効果に上書きされて無効になるもの）:</div>${body}` : `<div class="muted" style="font-size:12px">数値で読み取れる効果はありません（足止め数・攻撃対象数などは対象外）。</div>`}</div>`;
  }).join("");
}

function coverage(res, types) {
  if (types.some(t => EFFECTS[t].enemy)) return types.some(t => res.enemy[t]?.used.size) ? "ok" : "missing";
  const got = res.rows.filter(x => types.some(t => x.mine.some(e => e.type === t))).length;
  return got === 0 ? "missing" : got < res.rows.length ? "partial" : "ok";
}
function renderGaps(res) {
  if (!res.members.length) { $("gaps").innerHTML = "<p class='muted'>城娘を追加すると表示されます</p>"; return; }
  const ga = $("g-attr").value, gr = Number($("g-rar").value);
  const inParty = new Set(party.map(p => p.id));
  const allMagic = res.rows.every(x => x.magic);
  $("gaps").innerHTML = GAP_CHECKS.map(c => {
    let st = coverage(res, c.types);
    if (c.types[0] === "enemy_def" && allMagic) st = "ok";
    const label = c.types.map(t => EFFECTS[t].label).join(" / ");
    const head = { ok: "足りています", partial: "一部の城娘にしか届いていません", missing: "不足" }[st];
    let body = "";
    if (st !== "ok") {
      const cands = units.filter(u => !inParty.has(u.id) && (!ga || (u.attr || []).includes(ga)) && u.rarity >= gr)
        .map(u => {
          const es = allEffects(u).filter(e => c.types.includes(e.type) && !["self", "target"].includes(e.target) && !String(e.target).startsWith("other:"));
          if (!es.length) return null;
          const best = es.reduce((a, b) => (b.value > a.value ? b : a));
          return { u, e: best, wide: ["all", "enemy", "inrange"].includes(best.target) };
        }).filter(Boolean)
        .sort((a, b) => (b.wide - a.wide) || (b.e.value - a.e.value) || (b.u.rarity - a.u.rarity)).slice(0, 6);
      body = cands.length ? cands.map(({ u, e }) => `<div class="cand">${attrTags(u)}<b>${esc(u.name)}</b>
          <span class="muted">★${u.rarity}・${esc(u.weapon)}・${esc(u.range)}｜${e.sourceLabel}</span>${effTag(e)}
          <button class="small" data-add="${esc(u.id)}" ${party.length >= 8 ? "disabled" : ""}>追加</button></div>`).join("")
        : `<div class="muted">候補が見つかりません${ga || gr ? "（絞り込みを外すと見つかるかもしれません）" : ""}</div>`;
    }
    return `<div class="gap-item ${st}"><h3>${label}：${head}</h3><div class="muted" style="font-size:12px">${c.why}</div>${body}</div>`;
  }).join("") + `<h3 style="font-size:14px;margin:14px 0 6px">特殊効果（必要に応じて）</h3><div class="sp-grid">` + SP_CHECKS.map(c => {
    const have = res.members.flatMap(({ u }) => allTags(u).filter(t => c.tags.includes(t.tag)));
    const label = c.tags.join(" / ");
    if (have.length) {
      const who = [...new Map(have.map(t => [t.from.name + t.tag, t])).values()]
        .map(t => `${esc(t.from.name)}（${t.sourceLabel}${t.tag !== c.tags[0] || c.tags.length > 1 ? "・" + esc(t.tag) : ""}${t.value ? " " + t.value : ""}）`).join("、");
      return `<div class="gap-item have"><h3>${label}：あり</h3><div style="font-size:12px">${who}</div></div>`;
    }
    const cands = units.filter(u => !inParty.has(u.id) && (!ga || (u.attr || []).includes(ga)) && u.rarity >= gr)
      .map(u => ({ u, t: allTags(u).filter(t => c.tags.includes(t.tag)).sort((a, b) => (b.value || 0) - (a.value || 0))[0] })).filter(x => x.t)
      .sort((a, b) => (b.u.rarity - a.u.rarity) || ((b.t.value || 0) - (a.t.value || 0))).slice(0, 5);
    return `<div class="gap-item info"><h3>${label}：なし</h3><div class="muted" style="font-size:12px">${c.why}</div>
      <details><summary style="font-size:12px">候補を見る（${cands.length}体）</summary>${cands.map(({ u, t }) => `<div class="cand">${attrTags(u)}<b>${esc(u.name)}</b>
        <span class="muted">★${u.rarity}・${esc(u.weapon)}｜${t.sourceLabel}</span>${spTag(t)}
        <button class="small" data-add="${esc(u.id)}" ${party.length >= 8 ? "disabled" : ""}>追加</button></div>`).join("")}</details></div>`;
  }).join("") + "</div>";
}

function renderAll() {
  const res = compute();
  renderList(); renderSlots(); renderOverview(res); renderBuffs(res); renderStrat(res); renderCalc(res); renderGaps(res);
  save();
}

// ---- イベント ----
["f-name", "f-attr", "f-weapon", "f-range", "f-rarity", "f-effect", "f-tag", "f-target", "f-sort"].forEach(id => $(id).addEventListener("input", renderList));
["g-attr", "g-rar"].forEach(id => $(id).addEventListener("input", () => renderGaps(compute())));
document.addEventListener("click", ev => {
  const add = ev.target.closest("[data-add]"), rm = ev.target.closest("[data-rm]");
  if (add && party.length < 8 && !party.some(p => p.id === add.dataset.add)) { party.push({ id: add.dataset.add, strat: true, sp: true }); renderAll(); }
  if (rm) { party.splice(+rm.dataset.rm, 1); renderAll(); }
});
document.addEventListener("change", ev => {
  const s = ev.target.closest("[data-strat]"), sp = ev.target.closest("[data-sp]"), s2 = ev.target.closest("[data-strat2]");
  if (s2) { const p = party.find(p => p.id === s2.dataset.strat2); if (p) { p.strat = s2.checked; renderAll(); } }
  if (s) { party[+s.dataset.strat].strat = s.checked; renderAll(); }
  if (sp) { party[+sp.dataset.sp].sp = sp.checked; renderAll(); }
});
function bindSetting(id, key, num) {
  const el = $(id);
  if (num) el.value = settings[key]; else el.checked = settings[key];
  el.addEventListener("input", () => { settings[key] = num ? Number(el.value) || 0 : el.checked; renderAll(); });
}
bindSetting("s-edef", "edef", true); bindSetting("s-eatk", "eatk", true); bindSetting("s-giant", "giant", true); bindSetting("s-cond", "cond"); bindSetting("s-target", "target");

const dlg = $("dlg");
$("fmt").textContent = $("fmt").textContent.replace("EFFECT_LIST", Object.entries(EFFECTS).map(([k, v]) => `${k}(${v.label})`).join(", "));
$("btn-edit").onclick = () => { $("dlg-text").value = JSON.stringify(units, null, 1); $("dlg-err").textContent = ""; dlg.showModal(); };
$("dlg-cancel").onclick = () => dlg.close();
$("dlg-save").onclick = () => {
  try {
    const data = JSON.parse($("dlg-text").value);
    if (!Array.isArray(data)) throw new Error("配列である必要があります");
    data.forEach((u, i) => { if (!u.id || !u.name) throw new Error(`${i + 1}番目に id か name がありません`); });
    units = data; edited = true; party = party.filter(p => byId(p.id));
    dlg.close(); renderFilters(); renderAll();
  } catch (e) { $("dlg-err").textContent = "読み込めません: " + e.message; }
};
$("btn-export").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(units, null, 1)], { type: "application/json" }));
  a.download = "shiro-re-units.json"; a.click();
};
// confirm() が使えない環境（スマホの埋め込み表示など）でも動くよう、2回押しで確定する
let resetArmed = false;
$("btn-reset").onclick = () => {
  if (!resetArmed) {
    resetArmed = true; $("btn-reset").textContent = "もう一度押すと編集を破棄して戻します";
    setTimeout(() => { resetArmed = false; $("btn-reset").textContent = "wikiデータに戻す"; }, 4000);
    return;
  }
  resetArmed = false; $("btn-reset").textContent = "wikiデータに戻す";
  units = WIKI_UNITS; edited = false; party = party.filter(p => byId(p.id)); renderFilters(); renderAll();
};
$("btn-copy").onclick = async () => {
  try { await navigator.clipboard.writeText(JSON.stringify(units, null, 1)); $("btn-copy").textContent = "コピーしました"; }
  catch { $("btn-copy").textContent = "コピーできませんでした"; }
  setTimeout(() => $("btn-copy").textContent = "JSONをコピー", 2000);
};

// ---- 名前・スクショからの読み込み ----
const norm = s => String(s || "").normalize("NFKC").replace(/\s/g, "").replace(/\[改[壱弐参]?\]|\(改[壱弐参]?\)/g, "")
  .replace(/彊/g, "疆").replace(/[〔【「]/g, "[").replace(/[〕】」]/g, "]");
const bigrams = s => { const a = []; for (let i = 0; i < s.length - 1; i++) a.push(s.slice(i, i + 2)); return a.length ? a : [s]; };
function similarity(a, b) {
  const x = bigrams(a), y = bigrams(b); let hit = 0; const pool = [...y];
  for (const g of x) { const i = pool.indexOf(g); if (i >= 0) { hit++; pool.splice(i, 1); } }
  return 2 * hit / (x.length + y.length);
}
function matchName(raw) {
  const q = norm(raw); if (!q) return null;
  const exact = units.find(u => norm(u.name) === q);
  if (exact) return { u: exact, score: 1 };
  const prefix = (q.match(/^\[[^\]]*\]/) || [""])[0];
  let best = null;
  for (const u of units) {
    const n = norm(u.name);
    let sc = similarity(q, n);
    if (prefix && !n.startsWith(prefix)) sc -= 0.15;
    if (!prefix && n.startsWith("[")) sc -= 0.15;
    if (!best || sc > best.score) best = { u, score: sc };
  }
  return best && best.score >= 0.5 ? best : null;
}
function importNames(names, label) {
  const found = [], miss = [];
  for (const raw of names.slice(0, 8)) {
    const m = matchName(raw);
    if (m && !found.some(f => f.u.id === m.u.id)) found.push({ raw, ...m }); else if (!m) miss.push(raw);
  }
  if (!found.length) { $("import-msg").textContent = `${label}: 城娘を特定できませんでした（${names.join("、")}）`; return; }
  party = found.map(f => ({ id: f.u.id, strat: true, sp: true }));
  $("import-msg").innerHTML = `${label}: ` + found.map(f => f.score < 1 ? `${esc(f.raw)}→<b>${esc(f.u.name)}</b>` : esc(f.u.name)).join("、")
    + (miss.length ? `<br><span style="color:var(--bad)">見つからなかった名前: ${miss.map(esc).join("、")}</span>` : "")
    + "<br>違う城娘が入っていたら × で外して入れ直してください。";
  renderAll();
}
$("bulk-go").onclick = () => importNames($("bulk").value.split(/[、,，\n\/／]+/).map(x => x.trim()).filter(Boolean), "名前から読み込み");
$("clear-party").onclick = () => { party = []; $("import-msg").textContent = ""; renderAll(); };

// ---- スクショ読み取り: claude.ai内ではsample機能、それ以外ではAPIキーで直接呼び出す ----
const LS_KEY = "shiroRe.v2.apikey", LS_MODEL = "shiroRe.v2.apimodel";
const SHOT_PROMPT = "この画像はブラウザゲーム「御城プロジェクト:RE」の部隊編成画面のスクリーンショットです。" +
  "編成されている城娘の名前を、上の行から順に、各行は左から右の順で読み取ってください。" +
  "名前の前の［夏］や[漆磊]のような角括弧の部分は名前に含め、後ろの[改壱][改弐]は除いてください。武器名やレベルは不要です。" +
  "出力はJSON配列だけにしてください。例: [\"崑崙\",\"［漆磊］広島城\"]";
let sampleFn = null;
async function shrinkToJpeg(file, maxEdge = 1568) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((ok, ng) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => ng(new Error("画像を読み込めません")); i.src = url; });
    const k = Math.min(1, maxEdge / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement("canvas"); c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.85).split(",")[1];
  } finally { URL.revokeObjectURL(url); }
}
async function namesViaApi(file) {
  const key = localStorage.getItem(LS_KEY);
  const data = await shrinkToJpeg(file);
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true" },
    body: JSON.stringify({ model: localStorage.getItem(LS_MODEL) || "claude-haiku-5-5", max_tokens: 1024, output_config: { effort: "low" },
      messages: [{ role: "user", content: [{ type: "image", source: { type: "base64", media_type: "image/jpeg", data } }, { type: "text", text: SHOT_PROMPT }] }] }),
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(res.status === 401 ? "APIキーが正しくありません" : res.status === 429 ? "混み合っています。少し待ってから試してください" : (j.error && j.error.message) || ("通信エラー " + res.status));
  return (j.content || []).filter(b => b.type === "text").map(b => b.text).join("");
}
function refreshShotButton() {
  $("shot-wrap").hidden = !(sampleFn || localStorage.getItem(LS_KEY) || typeof PWA_MODE !== "undefined");
}
(async () => {
  try { sampleFn = window.claude && await window.claude.use("sample"); } catch { sampleFn = null; }
  try { if (sampleFn && !(await sampleFn.limits()).images) sampleFn = null; } catch { sampleFn = null; }
  $("s-key").value = localStorage.getItem(LS_KEY) || "";
  $("s-model").value = localStorage.getItem(LS_MODEL) || "claude-haiku-5-5";
  $("s-key").addEventListener("input", () => { localStorage.setItem(LS_KEY, $("s-key").value.trim()); refreshShotButton(); });
  $("s-model").addEventListener("input", () => localStorage.setItem(LS_MODEL, $("s-model").value));
  refreshShotButton();
  $("shot").onchange = async ev => {
    const file = ev.target.files[0]; ev.target.value = "";
    if (!file) return;
    if (!sampleFn && !localStorage.getItem(LS_KEY)) { $("import-msg").textContent = "スクショの読み取りには、下の「計算ルールと設定」でAPIキーを入れてください。名前の入力でも読み込めます。"; return; }
    $("import-msg").textContent = "スクショを読み取っています…";
    try {
      const text = sampleFn ? (await sampleFn(SHOT_PROMPT, { images: [file], modelTier: "default" })).text : await namesViaApi(file);
      const m = (text || "").match(/\[[\s\S]*\]/);
      const names = m ? JSON.parse(m[0]) : [];
      if (!Array.isArray(names) || !names.length) throw new Error("名前を読み取れませんでした");
      importNames(names.map(String), "スクショから読み込み");
    } catch (e) {
      $("import-msg").textContent = e && e.code === "not_granted" ? "Claudeへの画像の送信が許可されませんでした。"
        : e && e.code === "rate_limited" ? "混み合っています。少し待ってから試してください。"
        : "読み取りに失敗しました: " + (e && e.message || e);
    }
  };
})();

// ---- 起動 ----
async function boot() {
  let d = null;
  try { const r = await fetch("data.json", { cache: "no-cache" }); if (r.ok) d = await r.json(); } catch {}
  if (!d) { $("list-count").textContent = "データを読み込めませんでした。通信状況を確認して、再読み込みしてください。"; return; }
  WIKI_UNITS = d.units;
  if (!edited) units = d.units;
  party = party.filter(p => byId(p.id));
  const LS_VER = "shiroRe.v2.dataver", seen = localStorage.getItem(LS_VER);
  if (seen && seen !== d.version) {
    const b = $("update-banner");
    b.innerHTML = `<div>データを更新しました（${esc(d.built)}・${d.count}体）。${d.added && d.added.length ? "新しい城娘: " + d.added.map(esc).join("、") : ""}${edited ? "<br>※編集したデータを使用中のため、新しいデータは「wikiデータに戻す」で反映されます。" : ""}</div><button class="small" id="banner-ok">閉じる</button>`;
    b.hidden = false; $("banner-ok").onclick = () => { b.hidden = true; };
  }
  localStorage.setItem(LS_VER, d.version);
  renderFilters(); renderAll();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}
if (typeof PWA_MODE !== "undefined") boot(); else { renderFilters(); renderAll(); }
</script>
</body>
</html>
'''

if __name__ == "__main__":
    _run()

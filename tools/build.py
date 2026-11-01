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
  (re.compile(r"(?:伏兵の|対象の)?(?:射程|範囲)内の?(?:全ての)?(?:城娘|味方)(?:と伏兵)?(?:全て)?の"), "inrange"),
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

# 「巨大化する度に」以降（「最大化時」か次の効果まで）は巨大化回数分だけ効果が重なる
GIANT_RX = re.compile(r"巨大化(?:する|した)?(?:度|毎|ごと)に|巨大化回数1回につき|巨大化(?:段階|回数)?に応じて(?:更に|さらに)?")
MAXED_RX = re.compile(r"最大化時[、,]?")
def mark_giant(text): return MAXED_RX.sub(" ⟪M⟫ ", GIANT_RX.sub(" ⟪G⟫ ", text))
def giant_at(sent, pos, carry):
    g = carry
    for m in re.finditer(r"⟪([GM])⟫", sent[:pos]): g = m.group(1) == "G"
    return g

SEP = "\n ⟪M⟫ \n"  # 別々の編成特技・特殊能力の区切り（巨大化の効果を持ち越さない）
def max_giants(rarity, text=""):
    """最大化までの巨大化回数（wiki用語集「最大化」: ☆1～2は3回、☆3～5は4回、☆6～7は5回）"""
    m = re.search(r"([一二三四五六七八九十\d]+)回まで巨大化可能", text or "")
    if m:
        k = m.group(1)
        return int(k) if k.isdigit() else "一二三四五六七八九十".index(k) + 1
    r = rarity or 7
    return 3 if r <= 2 else 4 if r <= 5 else 5

def segments(text):
    out, prev, giant = [], None, False
    for sent in re.split(r"([。\n　 ]+)", mark_giant(text)):
        if not sent: continue
        if re.fullmatch(r"[。\n　 ]+", sent): continue
        if sent in ("⟪G⟫", "⟪M⟫"): giant = sent == "⟪G⟫"; continue
        hits = sorted(((m.start(), m.end(), kind, m) for rx, kind in SUBJ for m in rx.finditer(sent)), key=lambda h: (h[0], -h[1]))
        chosen, last = [], -1
        for h in hits:
            if h[0] >= last: chosen.append(h); last = h[1]
        if not chosen:
            out.append((prev[0], prev[1], sent, giant) if prev else ("none", None, sent, giant)); continue
        prev = (chosen[-1][2], chosen[-1][3])
        for i, (s, e, kind, m) in enumerate(chosen):
            end = chosen[i + 1][0] if i + 1 < len(chosen) else len(sent)
            out.append((kind, m, sent[e:end], giant))
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

TAIL_PAIRS = re.compile(r"(?:と\d+(?:\.\d+)?)?[、,/ ]*(?:" + STAT + r"(?:(?:と|や|、)" + STAT + r")*(?:が|を|は)?\d+(?:\.\d+)?(?:%|倍)?(?:と\d+)?[、,/ ]*)*")
GIANT_UPTO = re.compile(r"(?:(" + STAT + r")が?)?巨大化(?:段階)?に応じて(?:更に|さらに)?(?:(" + STAT + r")が?)?上昇[（(]最大(\d+(?:\.\d+)?)(%|倍)?")
def effects_of(text, giants=5):
    effs = []
    if not text or text == "なし": return effs
    text = re.sub(r"与ダメ(?!ージ)", "与ダメージ", re.sub(r"被ダメ(?!ージ)", "被ダメージ", text))
    selfonly = "自分のみ" in text
    segs = segments(text)
    for si, (kind, m, seg, giant) in enumerate(segs):
        if kind == "none": continue
        # 「攻撃と防御が50 被回復量が8%上昇」のように動詞が後ろの区切りにあるときに使う
        ahead = "".join(x[2] for x in segs[si + 1:si + 3])[:40]
        # 「5秒間〜」「ダメージを与え」のような一時的な効果は巨大化で重ならない
        seg_giant = giant
        if giant and re.search(r"秒間|ダメージを与え", seg): giant = False
        target = group_target(m.group(1)) if kind == "group" else ("self" if selfonly else "target") if kind == "target" else kind
        cond = bool(re.search(r"度に|毎に|ずつ|時間経過|撃破時|被攻撃時|計略中|発動中", seg))
        cap = re.search(r"(?:上限|最大)(\d+)%", seg)
        stack = bool(re.search(r"重複(?!なし|しない)", seg))
        di = re.search(r"防御を(\d+)%無視", seg)
        if di:
            e = dict(type="def_ignore", value=int(di.group(1)) * (giants if giant else 1), target="self")
            if giant: e["giant"] = giants
            effs.append(e)
        elif "防御無視" in seg or "防御を無視" in seg:
            e = dict(type="def_ignore", value=100, target="self")
            if cond: e["cond"] = True
            effs.append(e)
        for p in PAIR.finditer(seg):
            giant = seg_giant and not re.search(r"秒間|ダメージを与え", seg[:p.end()])
            val = float(p.group(2)); unit = p.group(3) or ""
            v_in = VERB.search(seg, p.end())
            # 値が区切りの最後にあるときだけ、後ろの区切りの動詞を使う
            tail_empty = bool(TAIL_PAIRS.fullmatch(seg[p.end():]))
            v = v_in or (VERB.search(ahead) if unit != "倍" and tail_empty else None)
            verb = v.group(0) if v else None
            # 「1.5倍」のように動詞を伴わない倍率は上昇として扱う
            if unit == "倍" and (not v_in or v_in.start() - p.end() > 8): verb = "上昇"
            if not verb: continue
            if giant: val *= giants
            if cap and unit == "%": val = float(cap.group(1))
            variants = [(target, val, unit)]
            # 「攻撃と防御が8%と40」: 割合と固定値の両方
            both = re.match(r"と(\d+)(?![\d.%倍])", seg[p.end():])
            if both and unit == "%": variants.append((target, float(both.group(1)) * (giants if giant else 1), ""))
            # 「射程内の城娘の攻撃が8%上昇、自身は10%上昇」: 自身だけ別の値
            sv = re.search(r"自身は(\d+(?:\.\d+)?)%", seg[p.end():])
            if sv and unit == "%" and target != "self" and target != "enemy":
                variants.append(("self", float(sv.group(1)) * (giants if giant else 1), "%"))
            for tg, vl, un in variants:
                for stat in re.findall(STAT, p.group(1)):
                    t, vv = classify(tg == "enemy", stat, vl, un, verb)
                    if not t: continue
                    e = dict(type=t, value=num(vv), target=tg)
                    if stack: e["stack"] = True
                    if cond: e["cond"] = True
                    if giant: e["giant"] = giants
                    effs.append(e)
    # 「攻撃が巨大化段階に応じて上昇(最大600)」: 最大化したときの値
    for mm in GIANT_UPTO.finditer(text):
        stat = mm.group(1) or mm.group(2); val = float(mm.group(3)); unit = mm.group(4) or ""
        pre = text[max(0, text.rfind("。", 0, mm.start()) + 1):mm.start()]
        hits = [(h.start(), kind, h) for rx, kind in SUBJ for h in rx.finditer(pre)]
        target = "self"
        if hits and not selfonly:
            _, kind, h = max(hits, key=lambda x: x[0])
            target = group_target(h.group(1)) if kind == "group" else kind
        t, vv = classify(target == "enemy", stat, val, unit, "上昇")
        if t: effs.append(dict(type=t, value=num(vv), target=target, giant=giants))
    # 「巨大化段階に応じて攻撃がさらに10%ずつ上昇」
    for mm in re.finditer(r"巨大化段階に応じて(" + STAT + r")が(?:さらに|更に)?(\d+(?:\.\d+)?)%ず[つづ]上昇", text):
        t, vv = classify(False, mm.group(1), float(mm.group(2)) * giants, "%", "上昇")
        if t: effs.append(dict(type=t, value=num(vv), target="self" if selfonly else "target", giant=giants))
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

def refs_of(text, giants=5):
    out = []
    if not text or text == "なし": return out
    selfonly = "自分のみ" in text
    carry = False
    pieces = re.split(r"([。\n]+)", mark_giant(text))
    for i in range(0, len(pieces), 2):
        sent = pieces[i]
        start_carry = carry
        carry = giant_at(sent, len(sent), start_carry)
        if not sent: continue
        def gmul(e, pos):
            if giant_at(sent, pos, start_carry):
                e["ref"]["pct"] = num(round(e["ref"]["pct"] * giants, 2)); e["giant"] = giants
            return e
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
                        out.append(gmul(e, m.start()))
        for m in REF_C.finditer(sent):
            if any(m.start() < e and s < m.end() for s, e in done): continue
            tgt, dstats, ex = ref_dest(m.group(1), selfonly)
            if not tgt or not dstats: continue
            for ds in dstats:
                e = dict(type=ds + "_flat", value=0, target=tgt, ref=dict(stat=ds, pct=num(float(m.group(3))), frm="giver"))
                if ex or re.search(r"除く|以外", sent): e["exSelf"] = True
                if kobu: e["kobu"] = True
                if cond: e["cond"] = True
                out.append(gmul(e, m.start()))
        km = re.search(r"鼓舞(?:効果|の加算値)(?:と[^がを]{1,10})?が(\d+(?:\.\d+)?)倍", sent) or (kobu and re.search(r"⟪M⟫\s*は?加算値が?(\d+(?:\.\d+)?)倍", sent))
        if km: out.append(dict(type="kobu_mult", value=num(round((float(km.group(1)) - 1) * 100, 1)), target="self"))
        for m in REF_E.finditer(sent):
            for es in re.findall(RS, m.group(1)):
                t = {"atk": "enemy_atk_flat", "def": "enemy_def_flat"}.get(RSTAT[es])
                if not t: continue
                for st, pct in ref_items(m.group(3)):
                    e = dict(type=t, value=0, target="enemy", ref=dict(stat=st, pct=pct, frm="giver"))
                    if cond: e["cond"] = True
                    out.append(gmul(e, m.start()))
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

def block(text, eff_text=None, giants=5):
    b = {"text": text}
    if eff_text is not None: b["effects"] = effects_of(eff_text, giants) + refs_of(eff_text, giants)
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
            form_eff = SEP.join(e for n, e in fp)
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
        g = max_giants(u["rarity"], u["skill"])
        rng_kind = "両" if (far and near) or any(w in BOTH for w in weapons) else "遠" if far else "近"
        out.append(dict(id=no, name=u["name"], rarity=u["rarity"], kai=u["kai"], attr=u["attr"],
            weapon="/".join(weapons), weapons=weapons, weaponRaw=u["weapon"], range=rng_kind,
            hp=vals[0], atk=vals[1], **{"def": vals[2]}, rng=vals[3], heal=vals[4],
            giants=g,
            skill=block(u["skill"], u["skill"], g),
            strategy=block(u["strat"], re.sub(r"^\[\d+s\]", "", first), g),
            formation=block(form_text, form_eff, g),
            held=block("\n".join(held_l), "\n".join(l.replace("[所持]", "") for l in held_l), g),
            specialAttack=block(u["special"]),
            kai2Missing=(u["name"] in has_kai2 and u["kai"] != "弐") or None,
            specialAbility=block("\n".join(f"【{n}】{e}" for n, e in sp), SEP.join(e for n, e in sp), g)))
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
        parts.append(f"{target_ja(e.get('target') or 'self')} {body}" + ("（重複）" if e.get("stack") else "") + (f"（巨大化{e['giant']}回）" if e.get("giant") else "") + ("（条件付き）" if e.get("cond") else ""))
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
    --near: #d23b32; --far: #2c74d6;
    --attr-平: #7a8f3a; --attr-平山: #5f7d55; --attr-山: #7b5a36; --attr-水: #2e6fa8; --attr-地獄: #6d2b8f; --attr-無: #777;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body { margin: 0; font-family: system-ui, "Hiragino Sans", "Noto Sans JP", sans-serif; background: var(--bg); color: var(--ink); font-size: 14px;
         display: flex; flex-direction: column; height: 100vh; height: 100dvh; overflow: hidden; }
  header { padding: 8px 14px; background: var(--accent); color: #fff; display: flex; align-items: center; gap: 10px; flex: none; }
  header h1 { font-size: 16px; margin: 0; flex: 1; }
  header .count { font-size: 12.5px; opacity: .9; }
  nav.tabs { display: flex; background: #fff; border-bottom: 1px solid var(--line); flex: none; }
  nav.tabs button { flex: 1 1 0; min-width: 0; border: 0; border-radius: 0; background: none; color: var(--muted); padding: 10px 0 7px; font-size: 12px; letter-spacing: -.04em;
                    border-bottom: 3px solid transparent; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  nav.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); font-weight: 700; }
  .pager { flex: 1; min-height: 0; display: flex; overflow-x: auto; overflow-y: hidden; scroll-snap-type: x mandatory; overscroll-behavior-x: contain; scrollbar-width: none; }
  .pager::-webkit-scrollbar { display: none; }
  .page { flex: 0 0 100%; width: 100%; scroll-snap-align: start; scroll-snap-stop: always; overflow-y: auto; overscroll-behavior-y: contain; padding: 10px 10px 48px; }
  .page > .inner { max-width: 1040px; margin: 0 auto; }
  .unit-row .grow > div { overflow-wrap: anywhere; }
  .unit-row .tag { white-space: normal; }
  section.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
  section.panel h2 { font-size: 15px; margin: 0 0 8px; border-left: 4px solid var(--accent); padding-left: 8px; }
  .filters { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin: 6px 0; }
  .filters input, .filters select, select, input[type=number] { width: 100%; padding: 6px; border: 1px solid var(--line); border-radius: 4px; font: inherit; background: #fff; }
  .filters .full { grid-column: 1 / -1; }
  button { font: inherit; padding: 5px 10px; border: 1px solid var(--accent); background: #fff; color: var(--accent); border-radius: 4px; cursor: pointer; }
  button.primary { background: var(--accent); color: #fff; }
  button:disabled { opacity: .4; cursor: default; }
  button.small { padding: 4px 9px; font-size: 12px; }
  .btnlike { display: inline-block; padding: 5px 10px; border: 1px solid var(--accent); background: var(--accent); color: #fff; border-radius: 4px; cursor: pointer; }
  .tag { display: inline-block; font-size: 11px; padding: 0 6px; border-radius: 10px; color: #fff; margin-right: 3px; line-height: 18px; white-space: nowrap; vertical-align: middle; }
  .tag.plain { background: #eee; color: #444; }
  .tag.eff { background: #f3ebe0; color: #5a3a10; }
  .tag.eff.enemy { background: #e8eef7; color: #1f4470; }
  .tag.eff.cond { border: 1px dashed #b08a50; }
  .tag.sp { background: #e6f2e8; color: #1d5a2c; }
  /* アイコン（自作SVG） */
  .wi { width: 30px; height: 30px; flex: none; vertical-align: middle; }
  .ri { width: 24px; height: 24px; flex: none; vertical-align: middle; }
  .wi.sm { width: 20px; height: 20px; } .ri.sm { width: 17px; height: 17px; }
  .icons { display: inline-flex; gap: 2px; align-items: center; vertical-align: middle; flex: none; }
  /* 編成 */
  .slots { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; }
  @media (min-width: 720px) { .slots { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  .slot { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); background: #fff; border-radius: 10px; padding: 7px 8px; min-height: 62px; }
  .slot.empty { border: 2px dashed var(--line); background: transparent; color: var(--muted); justify-content: center; cursor: pointer; font-size: 14px; }
  .slot.empty:active { background: #efe9dd; }
  .slot .no { font-size: 11px; color: var(--muted); width: 12px; text-align: center; flex: none; }
  .slot .main { flex: 1; min-width: 0; cursor: pointer; }
  .uname { font-size: 16px; font-weight: 800; line-height: 1.25; overflow-wrap: anywhere; }
  .slot .sub { font-size: 11.5px; color: var(--muted); margin-top: 1px; }
  .slot .acts { display: flex; flex-direction: column; gap: 4px; align-items: stretch; flex: none; }
  .tog { padding: 5px 8px; border-radius: 14px; font-size: 12px; font-weight: 700; min-width: 74px; white-space: nowrap; }
  .tog.on { background: var(--accent); color: #fff; }
  .tog.off { background: #fff; color: var(--muted); border-color: #c9c2b4; }
  .rm { border: 0; background: none; color: var(--muted); font-size: 18px; padding: 4px 6px; flex: none; }
  /* 探す */
  dialog.sheet { padding: 0; border: 0; width: 100vw; max-width: 100vw; height: 100dvh; max-height: 100dvh; margin: 0; background: var(--bg); }
  @media (min-width: 760px) { dialog.sheet { width: min(760px, 96vw); height: min(92dvh, 900px); margin: auto; border-radius: 10px; } }
  dialog.sheet[open] { display: flex; flex-direction: column; }
  dialog::backdrop { background: rgba(0,0,0,.35); }
  .sheet-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: var(--accent); color: #fff; }
  .sheet-head b { flex: 1; font-size: 15px; }
  .sheet-head button { background: transparent; color: #fff; border-color: rgba(255,255,255,.7); }
  .sheet-body { padding: 8px 10px 0; flex: none; }
  .sheet-body input#f-name { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 6px; font: inherit; font-size: 15px; }
  .chips { display: flex; gap: 4px; overflow-x: auto; padding: 6px 0 2px; scrollbar-width: none; }
  .chips::-webkit-scrollbar { display: none; }
  .chip { flex: none; display: inline-flex; align-items: center; justify-content: center; padding: 3px; border: 1px solid var(--line); border-radius: 8px; background: #fff; min-width: 36px; min-height: 34px; font-size: 12px; color: var(--ink); }
  .chip.on { border-color: var(--accent); background: #f6e3dc; box-shadow: inset 0 0 0 1px var(--accent); }
  .unit-list { flex: 1; overflow-y: auto; padding: 0 10px 30px; }
  .unit-row { display: flex; align-items: center; gap: 8px; padding: 8px 4px; border-bottom: 1px solid var(--line); cursor: pointer; }
  .unit-row:active { background: #efe9dd; }
  .unit-row.dim { opacity: .45; cursor: default; }
  .unit-row .name { font-weight: 800; font-size: 15px; }
  .unit-row .meta { color: var(--muted); font-size: 12px; }
  .unit-row .grow { flex: 1; min-width: 0; }
  .unit-row .pick { font-size: 12px; color: var(--accent); font-weight: 700; flex: none; }
  /* カード */
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 8px; }
  .bcard { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 12.5px; min-width: 0; background: #fff; }
  .bcard h3 { margin: 0 0 4px; font-size: 14px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .bline { padding: 3px 0; border-top: 1px dotted var(--line); overflow-wrap: anywhere; }
  .bline .k { display: inline-block; min-width: 5.5em; font-weight: 600; margin-right: 6px; }
  .stats { display: flex; flex-wrap: wrap; gap: 2px 12px; padding: 4px 0 2px; font-size: 12.5px; }
  .stats b { font-size: 14px; }
  .steps { margin: 4px 0 2px; padding-left: 16px; font-size: 12px; color: #444; }
  details.more { display: inline; }
  details.more > summary { display: inline; color: var(--accent); font-size: 11.5px; cursor: pointer; list-style: none; }
  details.more > summary::-webkit-details-marker { display: none; }
  details.more[open] > summary { display: inline; }
  details.more .list { display: block; padding: 2px 0 2px 10px; font-size: 11.5px; color: #555; }
  .src { color: var(--muted); font-size: 11.5px; }
  .down { color: var(--bad); font-weight: 600; }
  .up { color: var(--ok); font-weight: 600; }
  .muted { color: var(--muted); }
  .ov-row { display: grid; grid-template-columns: 5.2em minmax(0, 1fr); gap: 6px; padding: 4px 0; border-top: 1px dotted var(--line); }
  .ov-row .k { font-weight: 600; color: #555; font-size: 12px; }
  .gap-item { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; background: #fff; }
  .gap-item.missing { border-left: 5px solid var(--bad); }
  .gap-item.partial { border-left: 5px solid var(--warn); }
  .gap-item.ok { border-left: 5px solid var(--ok); }
  .gap-item.info { border-left: 5px solid #9aa7b5; }
  .gap-item.have { border-left: 5px solid var(--ok); }
  .gap-item h3 { margin: 0 0 4px; font-size: 13.5px; }
  .cand { display: flex; gap: 6px; align-items: center; padding: 5px 0; font-size: 12.5px; flex-wrap: wrap; border-top: 1px dotted var(--line); }
  .cand b { font-size: 13.5px; }
  .settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px 16px; }
  .settings label { display: flex; gap: 6px; align-items: center; }
  .settings label input[type=number] { width: 90px; }
  textarea { width: 100%; min-height: 300px; font-family: ui-monospace, monospace; font-size: 12px; border: 1px solid var(--line); border-radius: 4px; padding: 6px; }
  dialog#dlg { border: 1px solid var(--line); border-radius: 8px; width: min(900px, 95vw); }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  details summary { cursor: pointer; }
  a { color: var(--accent); }
  ul.rules { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: var(--muted); }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: #444; }
  .legend span { display: inline-flex; align-items: center; gap: 3px; }
  #update-banner { margin: 8px 10px 0; padding: 8px 12px; border: 1px solid var(--ok); background: #e9f4ec; border-radius: 8px; font-size: 13px; display: flex; gap: 8px; align-items: flex-start; flex: none; }
  #update-banner[hidden] { display: none; }
  #update-banner button { margin-left: auto; flex: none; }
  .hint { font-size: 12px; color: var(--muted); margin: 4px 0 8px; }
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
  <linearGradient id="g-both" x1="0" y1="0" x2="1" y2="1"><stop offset=".5" stop-color="#d23b32"/><stop offset=".5" stop-color="#2c74d6"/></linearGradient>
  <linearGradient id="g-both-l" x1="0" y1="0" x2="1" y2="1"><stop offset=".5" stop-color="#ff8f86"/><stop offset=".5" stop-color="#8cc0ff"/></linearGradient>
  <linearGradient id="g-silver" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="24" y2="24"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#c9c4d2"/></linearGradient>
</defs></svg>
<header>
  <h1>城プロRE 編成補助</h1>
  <span class="count" id="hdr-count"></span>
</header>
<nav class="tabs" id="tabs"></nav>
<div id="update-banner" hidden></div>
<div class="pager" id="pager">

<div class="page" data-title="編成"><div class="inner">
  <div class="slots" id="slots"></div>
  <div class="hint">空き枠をタップすると城娘を探せます。名前をタップすると一覧のその城娘へ移動します。</div>
  <section class="panel">
    <h2>まとめて読み込む</h2>
    <div class="row" style="margin-bottom:6px">
      <label id="shot-wrap" hidden><span class="btnlike">スクショから読み込む</span><input type="file" id="shot" accept="image/*" hidden></label>
      <button id="clear-party">編成を空にする</button>
    </div>
    <div class="row">
      <input id="bulk" placeholder="名前をまとめて入力（読点・改行区切り）" style="flex:1;min-width:180px;padding:6px;border:1px solid var(--line);border-radius:4px;font:inherit">
      <button id="bulk-go">名前で読み込む</button>
    </div>
    <div id="import-msg" class="muted" style="font-size:12px;margin-top:6px"></div>
  </section>
  <section class="panel">
    <h2>アイコンの見方</h2>
    <div class="legend" id="legend"></div>
  </section>
</div></div>

<div class="page" data-title="一覧"><div class="inner">
  <div id="overview"></div>
  <p class="hint">茶色・青のタグが計算に使っている効果、緑のタグが隠密無効や足止め数などの特殊効果です（点線枠は「〜する度に」などの条件付きで、上限値で計算）。</p>
</div></div>

<div class="page" data-title="バフ/デバフ"><div class="inner">
  <p class="hint" style="margin-top:0">全員が互いの射程内にいる前提で、計算式どおり有効になるものだけを表示します。固定値は合計だけを出し、「内訳」で提供元を見られます。実数値は初期値（Lv・装備なし、最大化の巨大化補正あり）での目安です。</p>
  <div class="grid" id="buffs"></div>
  <h3 style="font-size:14px;margin:14px 0 6px">敵へのデバフ</h3>
  <div id="debuffs"></div>
  <h3 style="font-size:14px;margin:14px 0 6px">計略で加わる効果</h3>
  <div id="strat-diff"></div>
</div></div>

<div class="page" data-title="不足と候補"><div class="inner">
  <div class="row" style="margin-bottom:8px">
    <label>候補の属性: <select id="g-attr" style="width:auto"></select></label>
    <label>最低レア: <select id="g-rar" style="width:auto"><option value="0">指定なし</option><option>5</option><option>6</option><option>7</option></select></label>
  </div>
  <div id="gaps"></div>
</div></div>

<div class="page" data-title="特殊効果"><div class="inner">
  <div id="sp-party"></div>
  <h3 style="font-size:14px;margin:14px 0 6px">あると便利な特殊効果</h3>
  <p class="hint" style="margin-top:0">候補の属性・レアは「不足と候補」の絞り込みを使います。</p>
  <div class="grid" id="sp-checks"></div>
</div></div>

<div class="page" data-title="設定"><div class="inner">
  <section class="panel">
    <h2>計算の設定</h2>
    <div class="settings">
      <label>敵の防御 <input type="number" id="s-edef" min="0"></label>
      <label>敵の攻撃 <input type="number" id="s-eatk" min="0"></label>
      <label>巨大化回数（鎌の防御無視に使用） <input type="number" id="s-giant" min="0" max="5"></label>
      <label><input type="checkbox" id="s-cond"> 条件付き効果（〜する度に、撃破時など）も上限値で含める</label>
      <label><input type="checkbox" id="s-target"> 計略の「対象の〜」を発動者自身に掛けたものとして扱う</label>
    </div>
  </section>
  <section class="panel">
    <h2>スクショ読み取り（任意）</h2>
    <div class="settings">
      <label>Anthropic APIキー <input type="password" id="s-key" autocomplete="off" placeholder="sk-ant-..." style="width:100%"></label>
      <label>モデル <select id="s-model" style="width:auto"><option value="claude-haiku-5-5">Haiku 5.5（安い・1回0.03円ほど）</option><option value="claude-sonnet-5-5">Sonnet 5.5（高精度・1回1円弱）</option></select></label>
    </div>
    <p class="muted" style="font-size:12px;margin:4px 0 0">キーはこの端末のブラウザにだけ保存され、スクショを読み取るときにAnthropicへ直接送られます（このツールの運営側には送られません）。キーは専用のものを作り、Consoleで使用量を確認できる状態にしておくのがおすすめです。</p>
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
    <p class="muted" style="font-size:12px"><span class="note">データ: 城プロRE攻略wiki（scre.swiki.jp）の全城娘一覧・ステータス一覧/能力値（DATA_DATE 取得）。効果は説明文から自動で読み取ったもので、読み違いがあり得ます。</span></p>
  </section>
  <section class="panel">
    <h2>計算ルール</h2>
    <ul class="rules">
      <li>同じ種類の割合バフ/デバフは、一番高いものだけ有効（説明文に「重複」とあるものは加算）。固定値は全て加算。</li>
      <li>編成特技・所持特技・特技/計略は別系統なので、割合バフは系統ごとに掛け算で重なる。</li>
      <li>攻撃 = ((初期攻撃×(1+編成%)＋編成固定)×(1+所持%)) ×(1+特技計略%)＋固定値、その後に計略などの攻撃倍率。乗算ごとに端数切り捨て。</li>
      <li>ダメージ = (攻撃 − 敵防御) ×(1+与ダメ増)×(1+敵の被ダメ増)×(1+与えるダメージ増)。最低20。法術・鈴・杖・祓串は防御無視。</li>
      <li>敵防御 = (防御×(1−特技計略の防御低下%) − 固定値低下) ×(1−防御無視%)。防御無視は特技計略の最大値＋鎌の武器種特性を加算。</li>
      <li>変換バフ（「攻撃に防御の50%の値を加算」）と鼓舞バフ（「自身の攻撃の35%の値を射程内の城娘に加算」）は、割合・固定値の後に加算。加算元は他のバフ適用後の値。鼓舞は提供者自身には掛からないものとして計算。</li>
      <li>攻撃速度・隙短縮は系統ごとに乗算。射程の位置関係は考慮せず、「射程内」の効果は全員に届くものとして扱う。</li>
      <li>能力値は改壱・改弐のある城娘は一番上の段階の初期値。特殊能力は「特殊」をオンにしたときだけ計算に入る。</li>
      <li>出典: wiki「検証」ページの「ステータス計算式」「ダメージ計算式」「特技・計略・武器の重複、競合」。地形・装備・武器効果は未反映。</li>
      <li>「巨大化する度に」の効果は最大化した値（☆1〜2は3回、☆3〜5は4回、☆6〜7は5回分）で計算し、「最大化時」の効果も含めています。能力値には最大化したときの巨大化補正（単属性は1回につき耐久・防御+22%、攻撃+18%、射程+16%、回復+12%、複合属性は+20%・+16%・+16%・+10%）を、編成・所持特技の後、特技・計略の前に掛けています。</li>
      <li>武器種・近遠のアイコンはこのツール用に作ったもので、ゲームの画像ではありません。</li>
    </ul>
  </section>
</div></div>

</div>

<dialog id="pick" class="sheet">
  <div class="sheet-head"><b>城娘を探す</b><button id="pick-close" class="small">閉じる</button></div>
  <div class="sheet-body">
    <input id="f-name" placeholder="名前・特技/計略の文章で検索" autocomplete="off">
    <div class="chips" id="chip-w"></div>
    <div class="chips" id="chip-a"></div>
    <details id="pick-more"><summary style="font-size:12.5px;color:var(--accent)">その他の絞り込み・並び替え</summary>
      <div class="filters">
        <select id="f-attr" hidden></select>
        <select id="f-weapon" hidden></select>
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
        <button id="f-clear" class="full small">絞り込みを解除</button>
      </div>
    </details>
    <div class="muted" id="list-count" style="font-size:12px;padding:4px 0"></div>
  </div>
  <div class="unit-list" id="unit-list"></div>
</dialog>

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
const giantTxt = e => e.giant ? `（巨大化${e.giant}回分）` : "";
const effTag = e => `<span class="tag eff${EFFECTS[e.type]?.enemy ? " enemy" : ""}${e.cond ? " cond" : ""}">${e.target === "enemy" && effText(e).startsWith("敵") ? "" : esc(targetText(e.target || "self")) + ":"}${esc(effText(e))}</span>`;
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
// 巨大化1回あたりの能力値上昇率（wiki「巨大化・属性」）。最大化した回数分を掛ける
const GIANT_RATE = { single: { hp: 22, atk: 18, def: 22, rng: 16, heal: 12 }, multi: { hp: 20, atk: 16, def: 20, rng: 16, heal: 10 } };
const giantMul = (u, k) => 1 + (GIANT_RATE[(u.attr || []).length > 1 ? "multi" : "single"][k] || 0) * (u.giants ?? 5) / 100;
// 割合と固定値を、編成→所持→巨大化補正→特技計略の順に適用
function applyStat(base, effs, pctType, flatType, gmul = 1) {
  const p = byGroups(effs, pctType), f = byGroups(effs, flatType);
  let v = fl(base * (1 + p.formation.total / 100)) + f.formation.total;
  v = fl(v * (1 + p.held.total / 100)) + f.held.total;
  v = fl(v * gmul);
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
    for (const [k, pt, ft] of STATS) st[k] = applyStat(u[k] ?? 0, mine, pt, ft, giantMul(u, k));
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

// ---- アイコン（このツール用に描いたSVG。ゲーム・wikiの画像は使っていない） ----
// 武器の絵は 24×24 の座標で、柄を右下・先端を左上に向けて描く
const D = "#1d1410";
const WGLYPH = {
  "刀": `<path d="M17.2 16Q8.4 11.4 2.8 2.8Q13.4 7 19.4 13.6Z" fill="currentColor"/><path d="M15.4 18.4L19.4 14.4" stroke-width="2"/><path d="M18.2 16.6L21.6 20" stroke-width="2.6"/>`,
  "槍": `<path d="M21 21L9.6 9.6" stroke-width="1.8"/><path d="M2.4 2.4L10.2 6.4L11 11L6.4 10.2Z" fill="currentColor"/><path d="M7.4 12.6L12.6 7.4" stroke-width="1.6"/>`,
  "槌": `<path d="M21 21L10.5 10.5" stroke-width="2"/><path d="M14.4 5.9L10.1 1.6L1.6 10.1L5.9 14.4Z" fill="currentColor"/><path d="M12.3 3.7L3.7 12.3" stroke="${D}" stroke-width="1"/>`,
  "盾": `<path d="M12 2L20 5V11C20 16.5 16.5 20 12 22C7.5 20 4 16.5 4 11V5Z" stroke-width="1.8"/><path d="M12 5.4L17 7.3V11C17 14.6 15 17 12 18.6C9 17 7 14.6 7 11V7.3Z" fill="currentColor"/>`,
  "拳": `<rect x="5" y="6" width="13" height="10" rx="3" fill="currentColor"/><path d="M8.6 6.4V10.4M11.6 6.4V10.4M14.6 6.4V10.4M5.4 12.4H11.6" stroke="${D}" stroke-width="1.1"/><rect x="7" y="16.8" width="10" height="4.6" rx="1" fill="currentColor"/>`,
  "鎌": `<path d="M21 21L8.6 4.2" stroke-width="2"/><path d="M8.6 4.2C3.6 5.4 2 10.6 4.2 15.6C5 10.6 7.6 8 11.6 7.6Z" fill="currentColor"/>`,
  "戦棍": `<path d="M21 21L11 11" stroke-width="2"/><circle cx="8" cy="8" r="4.4" fill="currentColor"/><path d="M8 1.4V3.2M1.4 8H3.2M3.2 3.2L4.6 4.6M12.8 3.2L11.6 4.4M3.2 12.8L4.4 11.6" stroke-width="1.6"/><circle cx="21.2" cy="21.2" r="1.3" fill="currentColor"/>`,
  "双剣": `<path d="M3 3L16.6 16.6M21 3L7.4 16.6" stroke-width="2"/><path d="M14 19L19 14M5 14L10 19" stroke-width="1.7"/><path d="M17.4 17.4L21 21M6.6 17.4L3 21" stroke-width="2.4"/>`,
  "ランス": `<path d="M2 2L17.2 11L11 17.2Z" fill="currentColor"/><path d="M18.2 10.2L10.2 18.2" stroke-width="2"/><path d="M15.6 15.6L21.2 21.2" stroke-width="2.4"/>`,
  "弓": `<path d="M5 19Q0.6 0.6 19 5" stroke-width="2.2"/><path d="M5 19L19 5" stroke-width=".9"/><path d="M21 21L6.4 6.4" stroke-width="1.3"/><path d="M3.6 3.6L9.2 5.4L5.4 9.2Z" fill="currentColor"/><path d="M17.4 21L21 21L21 17.4" stroke-width="1.4"/>`,
  "石弓": `<path d="M20.6 20.6L7 7" stroke-width="2.8"/><path d="M2.4 13.6Q3.4 3.4 13.6 2.4" stroke-width="2"/><path d="M2.4 13.6L10 10L13.6 2.4" stroke-width=".9"/><path d="M15.4 16.6L14.6 20" stroke-width="1.6"/>`,
  "鉄砲": `<path d="M2.6 2.6L15 15" stroke-width="2.2"/><path d="M13.4 15.6L15.6 13.4L21.6 17.6L17.6 21.6Z" fill="currentColor"/><path d="M14.4 17.6L13 20.2" stroke-width="1.4"/><path d="M5.6 7.4L7.4 5.6" stroke-width="1.4"/>`,
  "大砲": `<path d="M1.6 4.6L4.6 1.6L16.4 11.6L11.6 16.4Z" fill="currentColor"/><path d="M1.8 6.6L6.6 1.8" stroke-width="1.6"/><circle cx="15.6" cy="17" r="4.6" stroke-width="1.8" fill="${D}"/><path d="M15.6 12.4V21.6M11 17H20.2M12.4 13.8L18.8 20.2M18.8 13.8L12.4 20.2" stroke-width=".9"/>`,
  "歌舞": `<ellipse cx="6.8" cy="18.2" rx="2.9" ry="2.2" transform="rotate(-22 6.8 18.2)" fill="currentColor"/><ellipse cx="16.6" cy="16" rx="2.9" ry="2.2" transform="rotate(-22 16.6 16)" fill="currentColor"/><path d="M9.4 17.4V5.6M19.2 15.2V3.4" stroke-width="1.6"/><path d="M9.4 4.8L19.2 2.6V6L9.4 8.2Z" fill="currentColor"/>`,
  "法術": `<rect x="3.4" y="4" width="9" height="14.6" rx="1" transform="rotate(-14 7.9 11.3)" fill="currentColor" opacity=".75"/><rect x="10" y="5.4" width="9.2" height="15" rx="1" transform="rotate(10 14.6 12.9)" fill="currentColor"/><path d="M14.2 8.6L15.6 9.6L13.8 11.6L15.4 13L13.6 15L15 16.4" stroke="${D}" stroke-width="1.1" transform="rotate(10 14.6 12.9)"/>`,
  "鈴": `<g fill="currentColor"><circle cx="12" cy="3.4" r="2.1"/><circle cx="9.2" cy="7.4" r="2.1"/><circle cx="14.8" cy="7.4" r="2.1"/><circle cx="6.6" cy="11.4" r="2.1"/><circle cx="12" cy="11.6" r="2.1"/><circle cx="17.4" cy="11.4" r="2.1"/></g><path d="M5.4 14.6H18.6" stroke-width="1.8"/><path d="M12 14.6V22" stroke-width="2.2"/>`,
  "杖": `<path d="M17.6 21.6L11.2 8" stroke-width="2.2"/><path d="M11.2 8C9.2 3.8 12.8 1.2 15.6 3C18 4.8 16.2 8.2 13.6 7" stroke-width="2"/>`,
  "祓串": `<path d="M12 2.4V22" stroke-width="1.8"/><path d="M11 4.4L5.6 6.6L9 8.8L3.8 11L7.4 13.2L2.8 15.6M13 4.4L18.4 6.6L15 8.8L20.2 11L16.6 13.2L21.2 15.6" stroke-width="1.6"/>`,
  "本": `<path d="M11.2 6.4C8.8 4.6 5.4 4.4 2.6 5.4V19.2C5.4 18.2 8.8 18.4 11.2 20.2Z" fill="currentColor"/><path d="M12.8 6.4C15.2 4.6 18.6 4.4 21.4 5.4V19.2C18.6 18.2 15.2 18.4 12.8 20.2Z" fill="currentColor"/><path d="M5 8.6C6.6 8.2 8.2 8.4 9.4 9M5 11.6C6.6 11.2 8.2 11.4 9.4 12M14.6 9C15.8 8.4 17.4 8.2 19 8.6" stroke="${D}" stroke-width=".9"/>`,
  "投剣": `<path d="M2.6 2.6L12.4 8.2L11.2 11.2L8.2 12.4Z" fill="currentColor"/><path d="M11 11L16.6 16.6" stroke-width="2.2"/><path d="M12.6 13.6L13.6 12.6M14.2 15.2L15.2 14.2" stroke="${D}" stroke-width="1"/><circle cx="18.8" cy="18.8" r="2.3" stroke-width="1.6"/>`,
  "鞭": `<path d="M15.2 15.2C9.6 19.4 3.2 15.8 4.2 10C5.2 4.2 12.6 2.6 15 6.6C17.2 10.6 12 14.4 8.8 12C6.4 10.2 8.2 6.6 11.4 7.6" stroke-width="1.5"/><path d="M15.2 15.2L21 21" stroke-width="2.8"/><path d="M11.4 7.6Q14 9 12.2 10.6" stroke-width="1.1"/>`,
  "陣貝": `<path d="M2.8 3.6C10 1.6 17.2 6 19.4 13L21.2 20.8L13.6 18.6C6.8 16.6 2.2 10.8 2.8 3.6Z" fill="currentColor"/><path d="M5.8 5.4C10.8 5.6 14.4 8.8 15.6 13.6M4.6 8.6C8 9.8 10.6 12.2 11.8 15.6M8.8 3.8C13 5 16.4 8.2 17.6 12.4" stroke="${D}" stroke-width="1"/>`,
  "軍船": `<path d="M2.4 14.6H21.6L18.2 20.6H5.8Z" fill="currentColor"/><path d="M12 2V14.6" stroke-width="1.6"/><rect x="6.6" y="3.6" width="10.8" height="8.6" rx=".6" fill="currentColor"/><path d="M6.8 6.4H17.2M6.8 9.2H17.2M9.4 3.8V12M14.6 3.8V12" stroke="${D}" stroke-width=".8"/>`,
  "茶器": `<path d="M2.6 10.6H16.8C16.8 15.8 14 19 9.7 19C5.4 19 2.6 15.8 2.6 10.6Z" fill="currentColor"/><path d="M7.4 19.4H12V21.4H7.4Z" fill="currentColor"/><path d="M4.4 12.2H15" stroke="${D}" stroke-width="1"/><rect x="18" y="5" width="3.6" height="8.4" rx="1.4" fill="currentColor"/><path d="M19.8 13.4V19.6" stroke-width="1.8"/><path d="M8 7.6Q7 5.8 8.4 4.2M11.4 7.6Q10.4 5.8 11.8 4.2" stroke-width="1" opacity=".7"/>`,
  "その他": `<circle cx="6" cy="12" r="2" fill="currentColor"/><circle cx="12" cy="12" r="2" fill="currentColor"/><circle cx="18" cy="12" r="2" fill="currentColor"/>`,
};
const RANGE_OF_W = w => ["弓","石弓","鉄砲","大砲","歌舞","法術","鈴","杖","祓串","本"].includes(w) ? "遠" : ["投剣","鞭","陣貝","軍船","茶器"].includes(w) ? "両" : ["刀","槍","槌","盾","拳","鎌","戦棍","双剣","ランス"].includes(w) ? "近" : "";
const RCOL = { "近": "#d23b32", "遠": "#2c74d6", "両": "url(#g-both)" };
// 武器種: 黒い菱形の枠（近接は赤、遠隔は青、両用は赤青）に銀色の武器
function wIcon(w, cls = "", rng = "") {
  const g = WGLYPH[w] || WGLYPH["その他"], col = RCOL[RANGE_OF_W(w) || rng] || "#8a8a8a";
  return `<svg class="wi ${cls}" viewBox="0 0 32 32" role="img" aria-label="${esc(w)}"><title>${esc(w)}</title>`
    + `<path d="M16 1.2L30.8 16L16 30.8L1.2 16Z" fill="#241a15" stroke="${col}" stroke-width="2.2" stroke-linejoin="round"/>`
    + `<g transform="translate(4 4)" fill="none" stroke="url(#g-silver)" stroke-linecap="round" stroke-linejoin="round" color="#ece8f2" stroke-width="1.6">${g.replace(/fill="currentColor"/g, 'fill="url(#g-silver)" stroke="none"')}</g></svg>`;
}
// 近/遠/両: 配置マス（赤＝近接、青＝遠隔、赤青＝両用）
function rIcon(r, cls = "") {
  const c = { "近": ["#d23b32", "#ff9a90"], "遠": ["#2c74d6", "#9ccaff"], "両": ["url(#g-both)", "url(#g-both-l)"] }[r];
  if (!c) return "";
  const lab = { "近": "近接", "遠": "遠隔", "両": "両用" }[r];
  return `<svg class="ri ${cls}" viewBox="0 0 24 24" role="img" aria-label="${lab}"><title>${lab}</title>`
    + `<ellipse cx="12" cy="15.6" rx="11" ry="6.8" fill="${c[0]}"/><ellipse cx="12" cy="15.6" rx="8.4" ry="4.8" fill="none" stroke="${c[1]}" stroke-width="1.1"/>`
    + `<path d="M7.6 16.2V9.2L9.2 6.6L10.4 9H13.6L14.8 6.6L16.4 9.2V16.2Z" fill="${c[0]}" stroke="${c[1]}" stroke-width="1"/>`
    + `<path d="M10.2 11.8H11.2M12.8 11.8H13.8" stroke="${c[1]}" stroke-width="1.2" stroke-linecap="round"/></svg>`;
}
const unitIcons = (u, cls = "") => `<span class="icons">${weaponsOf(u).map(w => wIcon(w, cls, u.range)).join("")}${rIcon(u.range, cls)}</span>`;

// ---- 描画 ----
function fill(sel, vals, first) {
  const cur = sel.value;
  sel.innerHTML = `<option value="">${first}</option>` + vals.map(v => `<option>${esc(v)}</option>`).join("");
  sel.value = cur;
}
const ATTR_ORDER = ["平", "平山", "山", "水", "地獄", "無"];
const WEAPON_ORDER = ["刀","槍","槌","盾","拳","鎌","戦棍","双剣","ランス","弓","石弓","鉄砲","大砲","歌舞","法術","鈴","杖","祓串","本","投剣","鞭","陣貝","軍船","茶器","その他"];
function renderFilters() {
  const rank = (o, x) => { const i = o.indexOf(x); return i < 0 ? 99 : i; };
  const attrs = [...new Set(units.flatMap(u => u.attr || []))].sort((a, b) => rank(ATTR_ORDER, a) - rank(ATTR_ORDER, b));
  fill($("f-attr"), attrs, "属性: すべて"); fill($("g-attr"), attrs, "指定なし");
  const wl = [...new Set(units.flatMap(weaponsOf))].sort((a, b) => rank(WEAPON_ORDER, a) - rank(WEAPON_ORDER, b));
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
  renderChips();
  $("legend").innerHTML = WEAPON_ORDER.filter(w => w !== "その他").map(w => `<span>${wIcon(w, "sm")}${esc(w)}</span>`).join("")
    + ["近", "遠", "両"].map(r => `<span>${rIcon(r, "sm")}${{ "近": "近接", "遠": "遠隔", "両": "両用" }[r]}</span>`).join("");
}
// 武器種・属性はタップで選ぶチップ（中身は隠しselectと同期）
function renderChips() {
  const w = $("f-weapon").value, a = $("f-attr").value;
  const ws = [...$("f-weapon").options].slice(1).map(o => o.value);
  $("chip-w").innerHTML = `<button class="chip ${w ? "" : "on"}" data-chip-w="">全武器</button>` + ws.map(x => `<button class="chip ${w === x ? "on" : ""}" data-chip-w="${esc(x)}" title="${esc(x)}">${wIcon(x, "sm")}</button>`).join("");
  const as = [...$("f-attr").options].slice(1).map(o => o.value);
  $("chip-a").innerHTML = `<button class="chip ${a ? "" : "on"}" data-chip-a="">全属性</button>` + as.map(x => `<button class="chip ${a === x ? "on" : ""}" data-chip-a="${esc(x)}"><span class="tag" style="background:${attrColor(x)};margin:0">${esc(x)}</span></button>`).join("")
    + ["近", "遠", "両"].map(r => `<button class="chip ${$("f-range").value === r ? "on" : ""}" data-chip-r="${r}" title="${r}">${rIcon(r, "sm")}</button>`).join("");
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

const LIST_MAX = 150;
function renderList() {
  if (!$("pick").open) return;
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
  const nf = [a, w, rg, ra, ef, ft, tgf].filter(Boolean).length;
  $("list-count").textContent = `${list.length} 体` + (nf ? `（絞り込み ${nf}件）` : "") + (list.length > LIST_MAX ? `・先頭${LIST_MAX}体を表示` : "");
  $("unit-list").innerHTML = list.slice(0, LIST_MAX).map(u => {
    const inParty = party.some(p => p.id === u.id);
    const effs = allEffects(u).filter(e => (!ef || e.type === ef) && matchTarget(e, ft)).slice(0, 4).map(effTag).join("")
      + [...new Map(allTags(u).filter(t => !tgf || t.tag === tgf).map(t => [t.tag, t])).values()].slice(0, 3).map(spTag).join("");
    const stat = u.atk == null ? "能力値データなし" : `耐${u.hp} 攻${u.atk} 防${u.def} 射${u.rng}`;
    return `<div class="unit-row ${inParty ? "dim" : ""}" ${inParty ? "" : `data-add="${esc(u.id)}"`}>
      ${unitIcons(u)}
      <div class="grow">
        <div>${attrTags(u)}<span class="name">${esc(u.name)}</span> <span class="tag plain">★${u.rarity}</span>${k2Tag(u)}</div>
        <div class="meta">${stat}</div>
        <div>${effs}</div>
      </div>
      <span class="pick">${inParty ? "編成中" : "選ぶ"}</span>
    </div>`;
  }).join("");
}
function openPick() {
  if (party.length >= 8) return;
  const d = $("pick");
  if (!d.open) { try { d.showModal(); } catch { d.setAttribute("open", ""); } }
  renderChips(); renderList();
  $("unit-list").scrollTop = 0;
}
function closePick() { const d = $("pick"); if (d.open) { try { d.close(); } catch { d.removeAttribute("open"); } } }

const hasStrat = u => !!(u.strategy?.text && u.strategy.text !== "なし");
const hasSp = u => !!(u.specialAbility?.text && u.specialAbility.text !== "なし");
function renderSlots(res) {
  let html = "";
  for (let i = 0; i < 8; i++) {
    const p = party[i], u = p && byId(p.id), x = u && res.rows.find(r => r.u === u);
    html += u ? `<div class="slot">
        ${unitIcons(u)}
        <div class="main" data-goto="${esc(u.id)}">
          <div class="uname">${esc(u.name)}</div>
          <div class="sub">${attrTags(u)}★${u.rarity}${x && u.atk != null ? `・攻${x.atk}・1撃${x.dmg}` : ""}</div>${k2Tag(u)}
        </div>
        <div class="acts">
          ${hasStrat(u) ? `<button class="tog ${p.strat ? "on" : "off"}" data-tog-strat="${i}">計略 ${p.strat ? "ON" : "OFF"}</button>` : ""}
          ${hasSp(u) ? `<button class="tog ${p.sp ? "on" : "off"}" data-tog-sp="${i}">特殊 ${p.sp ? "ON" : "OFF"}</button>` : ""}
        </div>
        <button class="rm" data-rm="${i}" title="外す" aria-label="外す">×</button>
      </div>` : `<div class="slot empty" data-open-pick="${i}">＋ 城娘を探す</div>`;
  }
  $("slots").innerHTML = html;
  $("hdr-count").textContent = `編成 ${party.length}/8`;
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
  if (!res.members.length) { $("overview").innerHTML = "<p class='muted'>城娘を編成すると表示されます</p>"; return; }
  const rows = [["特技", "skill"], ["計略", "strategy"], ["編成特技", "formation"], ["所持特技", "held"], ["大破・特殊", "specialAttack"], ["特殊能力", "specialAbility"]];
  $("overview").innerHTML = `<div class="grid">` + res.members.map(({ u }) => `<div class="bcard" id="ov-${esc(u.id)}">
      <h3>${unitIcons(u)}<span class="uname">${esc(u.name)}</span></h3>
      <div class="src">${attrTags(u)}★${u.rarity}${u.kai ? "・改" + esc(u.kai) : ""}・${esc(u.weapon)}${u.weaponRaw && u.weaponRaw !== u.weapon ? `（${esc(u.weaponRaw)}）` : ""}・${esc(u.range)}${isMagic(u) ? "・術攻撃" : ""}
        ・<a href="${WIKI + encodeURIComponent(u.name)}" target="_blank" rel="noopener">wiki</a> ${k2Tag(u)}</div>
      <div class="stats"><span>耐 ${u.hp ?? "?"}</span><span>攻 ${u.atk ?? "?"}</span><span>防 ${u.def ?? "?"}</span><span>射 ${u.rng ?? "?"}</span><span class="muted">（初期値）</span></div>
      ${rows.map(([k, key]) => `<div class="ov-row"><span class="k">${k}</span><div>${cell(u[key])}</div></div>`).join("")}
    </div>`).join("") + `</div>`;
}

// ---- 各城娘にかかるバフ（実数値ではなく「+60%」「+（〇〇の攻撃の35%）」の形で） ----
const GL = { formation: "編成", held: "所持", normal: "" };
const srcOf = (e, u) => `${esc(e.from.name)}${e.from === u ? "（自身）" : ""}・${e.sourceLabel}`;
const refWho = (e, u) => e.ref.frm === "recv" ? "各自" : e.from === u ? "自身" : esc(e.from.name);
const srcLine = (e, u, grp) => `${srcOf(e, u)}${grp && GL[grp] ? "［" + GL[grp] + "］" : ""}${e.stack ? "（重複）" : ""}${giantTxt(e)}${e.cond ? "（条件付き）" : ""}`;
// 固定値は合計だけを出し、内訳は開いて見る
function flatSum(cat, list, u, sign = "+") {
  if (!list.length) return null;
  const sum = list.reduce((a, x) => a + x.e.value, 0), cls = sign === "+" ? "up" : "down";
  if (list.length === 1) return { cat, html: `<span class="${cls}">${sign}${sum}</span> <span class="src">${srcLine(list[0].e, u, list[0].g)}</span>` };
  return { cat, html: `<span class="${cls}">${sign}${sum}</span> <span class="src">固定値の合計（${list.length}件）</span> <details class="more"><summary>内訳 ▾</summary><span class="list">${list.map(x => `${sign}${x.e.value} ${srcLine(x.e, u, x.g)}`).join("<br>")}</span></details>` };
}
// 1体分の有効なバフを {cat, html} の並びにする（表示と計略で加わる効果の比較に共用）
function buffItems(x) {
  const u = x.u, out = [];
  const push = (cat, e, unit, grp) => out.push({ cat, html: `<span class="up">+${e.value}${unit}</span> <span class="src">${srcLine(e, u, grp)}</span>` });
  const groups = (cat, g, unit) => { for (const k of ["formation", "held", "normal"]) if (g[k]) for (const e of g[k].used) push(cat, e, unit, k); };
  const flats = g => ["formation", "held", "normal"].flatMap(k => [...g[k].used].map(e => ({ e, g: k })));
  for (const [k, label] of [["atk", "攻撃"], ["def", "防御"], ["hp", "耐久"], ["rng", "射程"], ["heal", "回復"]]) {
    groups(label, x.st[k].p, "%");
    const f = flatSum(label, flats(x.st[k].f), u); if (f) out.push(f);
    for (const e of x.refs.filter(e => e.type === k + "_flat"))
      out.push({ cat: label, html: `<span class="up">+（${refWho(e, u)}の${STAT_JA[e.ref.stat]}の${e.pctEff}%）</span> <span class="src">${srcOf(e, u)}${e.kobu ? "・鼓舞" : ""}${e.kmul && e.kmul !== 1 ? `（${e.ref.pct}%×鼓舞効果${e.kmul}倍）` : ""}${giantTxt(e)}${e.cond ? "（条件付き）" : ""}</span>` });
  }
  for (const e of x.mult.used) push("攻撃", e, "%（倍率）");
  groups("与ダメージ", x.upG, "%");
  for (const e of x.up2.used) push("与えるダメージ", e, "%");
  groups("攻撃速度", x.speedG, "%"); groups("隙短縮", x.gapG, "%"); groups("被ダメ軽減", x.cutG, "%");
  if (isMagic(u)) out.push({ cat: "防御無視", html: `<b>術攻撃</b> <span class="src">武器種</span>` });
  else {
    for (const e of x.ign.used) out.push({ cat: "防御無視", html: e.value >= 100 ? `<b>敵の防御を無視</b> <span class="src">${srcOf(e, u)}</span>` : `<span class="up">+${e.value}%</span> <span class="src">${srcOf(e, u)}${giantTxt(e)}</span>` });
    if (x.scythe) out.push({ cat: "防御無視", html: `<span class="up">+${x.scythe}%</span> <span class="src">鎌の武器種特性（巨大化${settings.giant}回）</span>` });
  }
  return out;
}
function enemyItems(res) {
  const out = [], e = res.enemy;
  const pct = (cat, g, sign = "−") => { for (const k of ["formation", "held", "normal"]) for (const x of g[k].used)
    out.push({ cat, html: x.ref ? `<span class="down">−（${esc(x.from.name)}の${STAT_JA[x.ref.stat]}の${x.ref.pct}%）</span> <span class="src">${esc(x.from.name)}・${x.sourceLabel}${giantTxt(x)}${x.cond ? "（条件付き）" : ""}</span>`
      : `<span class="${sign === "+" ? "up" : "down"}">${sign}${x.value}%</span> <span class="src">${esc(x.from.name)}・${x.sourceLabel}${GL[k] ? "［" + GL[k] + "］" : ""}${giantTxt(x)}${x.cond ? "（条件付き）" : ""}</span>` }); };
  const flat = (cat, g) => {
    const list = ["formation", "held", "normal"].flatMap(k => [...g[k].used].map(x => ({ e: x.orig && x.ref ? { ...x.orig, value: x.value } : x, g: k })));
    const plain = list.filter(x => !x.e.ref), refs = list.filter(x => x.e.ref);
    const f = flatSum(cat, plain, null, "−"); if (f) out.push(f);
    for (const { e: x } of refs) out.push({ cat, html: `<span class="down">−（${esc(x.from.name)}の${STAT_JA[x.ref.stat]}の${x.ref.pct}%）</span> <span class="src">${esc(x.from.name)}・${x.sourceLabel}${giantTxt(x)}${x.cond ? "（条件付き）" : ""}</span>` });
  };
  pct("防御", e.enemy_def); flat("防御", e.enemy_def_flat); pct("攻撃", e.enemy_atk); flat("攻撃", e.enemy_atk_flat);
  pct("被ダメージ", e.enemy_taken, "+"); pct("与ダメージ", e.enemy_dealt); pct("移動速度", e.enemy_slow); pct("射程", e.enemy_rng);
  return out;
}
const CATS = ["攻撃", "防御", "耐久", "射程", "回復", "与ダメージ", "与えるダメージ", "攻撃速度", "隙短縮", "被ダメ軽減", "防御無視"];
const ECATS = ["防御", "攻撃", "被ダメージ", "与ダメージ", "移動速度", "射程"];
function itemLines(items, cats, empty) {
  const html = cats.map(c => { const xs = items.filter(i => i.cat === c); return xs.length ? `<div class="bline"><span class="k">${c}</span>${xs.map(i => i.html).join("<br>")}</div>` : ""; }).join("");
  return html || `<div class="muted" style="font-size:12px">${empty}</div>`;
}
// 実数値の内訳（初期値→編成→所持→巨大化→特技計略→変換・鼓舞→倍率）
function statSteps(x, k) {
  const u = x.u, s = x.st[k], gm = giantMul(u, k);
  let v = u[k] ?? 0; const out = [`初期値 ${v}`];
  const stage = (label, p, f) => { if (!p && !f) return; v = fl(v * (1 + p / 100)) + f; out.push(`${label} ${p ? "+" + p + "%" : ""}${p && f ? " " : ""}${f ? "+" + f : ""} → ${v}`); };
  stage("編成特技", s.p.formation.total, s.f.formation.total);
  stage("所持特技", s.p.held.total, s.f.held.total);
  if (gm !== 1) { v = fl(v * gm); out.push(`巨大化補正 ×${Math.round(gm * 100) / 100}（${u.giants ?? 5}回） → ${v}`); }
  stage("特技・計略", s.p.normal.total, s.f.normal.total);
  const r = x.refs.filter(e => e.type === k + "_flat");
  if (r.length) { const add = r.reduce((a, e) => a + e.value, 0); v += add; out.push(`変換・鼓舞 +${add}（${r.map(e => esc(e.from.name) + " " + e.value).join("、")}） → ${v}`); }
  if (k === "atk" && x.mult.total) { v = fl(v * (1 + x.mult.total / 100)); out.push(`攻撃倍率 +${x.mult.total}% → ${v}`); }
  return out;
}
function statBlock(x, res) {
  const raw = Math.max(x.atk - x.edef, 20);
  const dmgSteps = [`敵の防御 ${settings.edef} → ${x.magic ? "0（防御無視）" : x.edef}${!x.magic && x.ignore ? `（防御無視${x.ignore}%込み）` : ""}`,
    `(攻撃 ${x.atk} − ${x.magic ? 0 : x.edef}) = ${raw}${raw === 20 ? "（最低20）" : ""}`,
    `× 与ダメージ +${x.dmgUp}% × 敵の被ダメージ +${res.taken}%${x.dmgUp2 ? ` × 与えるダメージ +${x.dmgUp2}%` : ""} = ${x.dmg}`];
  const li = a => a.map(s => `<li>${s}</li>`).join("");
  return `<div class="stats"><span>攻 <b>${x.atk}</b></span><span>防 <b>${x.def}</b></span><span>耐 <b>${x.hp}</b></span><span>射 <b>${x.rng}</b></span><span>1撃 <b>${x.dmg}</b></span>
    <details class="more"><summary>実数値の内訳 ▾</summary><span class="list">
      <b>攻撃</b><ol class="steps">${li(statSteps(x, "atk"))}</ol><b>1撃の目安</b><ol class="steps">${li(dmgSteps)}</ol>
      <b>防御</b><ol class="steps">${li(statSteps(x, "def"))}</ol><b>耐久</b><ol class="steps">${li(statSteps(x, "hp"))}</ol>
      <b>射程</b><ol class="steps">${li(statSteps(x, "rng"))}</ol></span></details></div>`;
}
function renderBuffs(res) {
  if (!res.rows.length) { $("buffs").innerHTML = "<p class='muted'>城娘を編成すると表示されます</p>"; $("debuffs").innerHTML = ""; return; }
  $("buffs").innerHTML = res.rows.map(x => {
    const p = party.find(p => p.id === x.u.id);
    return `<div class="bcard"><h3>${unitIcons(x.u, "sm")}<span style="font-weight:800">${esc(x.u.name)}</span>
      ${hasStrat(x.u) ? `<button class="tog ${p?.strat ? "on" : "off"}" data-tog-strat="${party.indexOf(p)}" style="margin-left:auto;min-width:0">計略 ${p?.strat ? "ON" : "OFF"}</button>` : ""}</h3>
      ${statBlock(x, res)}
      ${itemLines(buffItems(x), CATS, "数値で読み取れたバフはありません")}</div>`;
  }).join("");
  $("debuffs").innerHTML = `<div class="bcard">${itemLines(enemyItems(res), ECATS, "数値で読み取れたデバフはありません")}
    <div class="src" style="margin-top:4px">敵: 防御 ${settings.edef} → ${res.edefBase} ／ 攻撃 ${settings.eatk} → ${res.eatk} ／ 被ダメージ +${res.taken}% ／ 与ダメージ −${res.dealt}% ／ 移動速度 −${res.slow}%</div>
    <div class="src">割合デバフは同系統で一番高いものだけ有効（編成と所持は競合、特技計略とは乗算）。固定値は割合の後に引きます。</div></div>`;
}

// ---- 計略で加わる効果（オンにしたときに新しく有効になるものだけ。上書きされて消えるものは出さない） ----
function renderStrat(res) {
  if (!res.rows.length) { $("strat-diff").innerHTML = "<p class='muted'>城娘を編成すると表示されます</p>"; return; }
  const key = i => i.cat + "|" + i.html;
  const diff = (a, b, cats) => cats.map(c => {
    const ka = new Set(a.filter(i => i.cat === c).map(key));
    const add = b.filter(i => i.cat === c && !ka.has(key(i))).map(i => i.html);
    return add.length ? `<div class="bline"><span class="k">${c}</span>${add.join("<br>")}</div>` : "";
  }).join("");
  const html = res.members.map(m => {
    const u = m.u;
    if (!hasStrat(u)) return "";
    const alt = compute(party.map(p => p.id === u.id ? { ...p, strat: !p.strat } : p));
    const off = m.strat ? alt : res, on = m.strat ? res : alt;
    const lines = off.rows.map((x, i) => { const d = diff(buffItems(x), buffItems(on.rows[i]), CATS); return d ? `<div style="margin-top:4px"><b>→ ${esc(x.u.name)}</b>${d}</div>` : ""; }).join("");
    const el = diff(enemyItems(off), enemyItems(on), ECATS);
    const body = lines + (el ? `<div style="margin-top:4px"><b>→ 敵</b>${el}</div>` : "");
    const i = party.findIndex(p => p.id === u.id);
    return `<div class="gap-item ${body ? "have" : "info"}"><h3 style="display:flex;align-items:center;gap:6px">${unitIcons(u, "sm")}${esc(u.name)}の計略
      <button class="tog ${m.strat ? "on" : "off"}" data-tog-strat="${i}" style="margin-left:auto;min-width:0">計略 ${m.strat ? "ON" : "OFF"}</button></h3>
      <div class="src">${esc(u.strategy.text.split("\n")[0])}</div>
      ${body ? `<div style="font-size:12.5px">${body}</div>` : `<div class="muted" style="font-size:12px">数値で読み取れる効果はありません（足止め数・攻撃対象数などは対象外）。</div>`}</div>`;
  }).join("");
  $("strat-diff").innerHTML = html || "<p class='muted'>計略を持つ城娘がいません</p>";
}

function coverage(res, types) {
  if (types.some(t => EFFECTS[t].enemy)) return types.some(t => res.enemy[t]?.used.size) ? "ok" : "missing";
  const got = res.rows.filter(x => types.some(t => x.mine.some(e => e.type === t))).length;
  return got === 0 ? "missing" : got < res.rows.length ? "partial" : "ok";
}
const candRow = (u, tagHtml, label) => `<div class="cand">${unitIcons(u, "sm")}${attrTags(u)}<b>${esc(u.name)}</b>
  <span class="muted">★${u.rarity}｜${label}</span>${tagHtml}
  <button class="small" data-add="${esc(u.id)}" ${party.length >= 8 ? "disabled" : ""} style="margin-left:auto">追加</button></div>`;
function candFilter() { const ga = $("g-attr").value, gr = Number($("g-rar").value), inParty = new Set(party.map(p => p.id));
  return u => !inParty.has(u.id) && (!ga || (u.attr || []).includes(ga)) && u.rarity >= gr; }
function renderGaps(res) {
  if (!res.members.length) { $("gaps").innerHTML = "<p class='muted'>城娘を編成すると表示されます</p>"; return; }
  const ok = candFilter(), filtered = $("g-attr").value || Number($("g-rar").value);
  const allMagic = res.rows.every(x => x.magic);
  const items = GAP_CHECKS.map(c => {
    let st = coverage(res, c.types);
    if (c.types[0] === "enemy_def" && allMagic) st = "ok";
    const label = c.types.map(t => EFFECTS[t].label).join(" / ");
    const head = { ok: "足りています", partial: "一部の城娘にしか届いていません", missing: "不足" }[st];
    let body = "";
    if (st !== "ok") {
      const cands = units.filter(ok).map(u => {
          const es = allEffects(u).filter(e => c.types.includes(e.type) && !["self", "target"].includes(e.target) && !String(e.target).startsWith("other:"));
          if (!es.length) return null;
          const best = es.reduce((a, b) => (b.value > a.value ? b : a));
          return { u, e: best, wide: ["all", "enemy", "inrange"].includes(best.target) };
        }).filter(Boolean)
        .sort((a, b) => (b.wide - a.wide) || (b.e.value - a.e.value) || (b.u.rarity - a.u.rarity)).slice(0, 6);
      body = cands.length ? cands.map(({ u, e }) => candRow(u, effTag(e), e.sourceLabel)).join("")
        : `<div class="muted">候補が見つかりません${filtered ? "（絞り込みを外すと見つかるかもしれません）" : ""}</div>`;
    }
    return { st, html: `<div class="gap-item ${st}"><h3>${label}：${head}</h3><div class="muted" style="font-size:12px">${c.why}</div>${body}</div>` };
  });
  // 不足しているものを上に
  const order = { missing: 0, partial: 1, ok: 2 };
  $("gaps").innerHTML = items.sort((a, b) => order[a.st] - order[b.st]).map(x => x.html).join("");
}
function renderSp(res) {
  if (!res.members.length) { $("sp-party").innerHTML = "<p class='muted'>城娘を編成すると表示されます</p>"; $("sp-checks").innerHTML = ""; return; }
  $("sp-party").innerHTML = `<div class="bcard">` + res.members.map(({ u }) => {
    const ts = [...new Map(allTags(u).map(t => [t.tag + t.source, t])).values()];
    return `<div class="bline" style="display:flex;gap:6px;align-items:flex-start">${unitIcons(u, "sm")}<div><b>${esc(u.name)}</b><br>${ts.length ? ts.map(t => `${spTag(t)}<span class="src">${t.sourceLabel}</span>`).join(" ") : '<span class="muted">なし</span>'}</div></div>`;
  }).join("") + `</div>`;
  const ok = candFilter();
  $("sp-checks").innerHTML = SP_CHECKS.map(c => {
    const have = res.members.flatMap(({ u }) => allTags(u).filter(t => c.tags.includes(t.tag)));
    const label = c.tags.join(" / ");
    if (have.length) {
      const who = [...new Map(have.map(t => [t.from.name + t.tag, t])).values()]
        .map(t => `${esc(t.from.name)}（${t.sourceLabel}${t.tag !== c.tags[0] || c.tags.length > 1 ? "・" + esc(t.tag) : ""}${t.value ? " " + t.value : ""}）`).join("、");
      return `<div class="gap-item have"><h3>${label}：あり</h3><div style="font-size:12px">${who}</div></div>`;
    }
    const cands = units.filter(ok)
      .map(u => ({ u, t: allTags(u).filter(t => c.tags.includes(t.tag)).sort((a, b) => (b.value || 0) - (a.value || 0))[0] })).filter(x => x.t)
      .sort((a, b) => (b.u.rarity - a.u.rarity) || ((b.t.value || 0) - (a.t.value || 0))).slice(0, 5);
    return `<div class="gap-item info"><h3>${label}：なし</h3><div class="muted" style="font-size:12px">${c.why}</div>
      <details><summary style="font-size:12px">候補を見る（${cands.length}体）</summary>${cands.map(({ u, t }) => candRow(u, spTag(t), t.sourceLabel)).join("")}</details></div>`;
  }).join("");
}

function renderAll() {
  const res = compute();
  renderSlots(res); renderList(); renderOverview(res); renderBuffs(res); renderStrat(res); renderGaps(res); renderSp(res);
  save();
}

// ---- タブとスワイプ（横スクロールのスナップで切り替え） ----
const LS_TAB = "shiroRe.v2.tab";
const pages = [...document.querySelectorAll("#pager > .page")];
$("tabs").innerHTML = pages.map((p, i) => `<button data-tab="${i}">${p.dataset.title}</button>`).join("");
let curTab = 0;
function setTabUI(i) {
  curTab = i;
  document.querySelectorAll("#tabs button").forEach((b, j) => b.classList.toggle("on", j === i));
  try { localStorage.setItem(LS_TAB, String(i)); } catch {}
}
function goTab(i, smooth = true) {
  const pg = $("pager");
  pg.scrollTo({ left: i * pg.clientWidth, behavior: smooth ? "smooth" : "auto" });
  setTabUI(i);
}
let scrollT = null;
$("pager").addEventListener("scroll", () => {
  const pg = $("pager"), i = Math.round(pg.scrollLeft / Math.max(1, pg.clientWidth));
  if (i !== curTab) setTabUI(i);
}, { passive: true });
window.addEventListener("resize", () => { const pg = $("pager"); pg.scrollLeft = curTab * pg.clientWidth; });

// ---- イベント ----
["f-name", "f-rarity", "f-effect", "f-tag", "f-target", "f-sort"].forEach(id => $(id).addEventListener("input", renderList));
$("f-range").addEventListener("input", () => { renderChips(); renderList(); });
["g-attr", "g-rar"].forEach(id => $(id).addEventListener("input", () => { const r = compute(); renderGaps(r); renderSp(r); }));
$("pick-close").onclick = closePick;
$("f-clear").onclick = () => { ["f-attr", "f-weapon", "f-range", "f-rarity", "f-effect", "f-tag", "f-target"].forEach(id => $(id).value = ""); $("f-sort").value = "no"; renderChips(); renderList(); };
document.addEventListener("click", ev => {
  const t = ev.target;
  const add = t.closest("[data-add]"), rm = t.closest("[data-rm]"), op = t.closest("[data-open-pick]"), tab = t.closest("[data-tab]");
  const ts = t.closest("[data-tog-strat]"), tsp = t.closest("[data-tog-sp]"), go = t.closest("[data-goto]");
  const cw = t.closest("[data-chip-w]"), ca = t.closest("[data-chip-a]"), cr = t.closest("[data-chip-r]");
  if (tab) goTab(+tab.dataset.tab);
  if (op) openPick();
  if (cw) { $("f-weapon").value = cw.dataset.chipW; renderChips(); renderList(); }
  if (ca) { $("f-attr").value = ca.dataset.chipA; renderChips(); renderList(); }
  if (cr) { $("f-range").value = $("f-range").value === cr.dataset.chipR ? "" : cr.dataset.chipR; renderChips(); renderList(); }
  if (add && party.length < 8 && !party.some(p => p.id === add.dataset.add)) {
    party.push({ id: add.dataset.add, strat: true, sp: true });
    if (add.closest("#pick")) closePick();
    renderAll();
  }
  if (rm) { party.splice(+rm.dataset.rm, 1); renderAll(); }
  if (ts && party[+ts.dataset.togStrat]) { const p = party[+ts.dataset.togStrat]; p.strat = !p.strat; renderAll(); }
  if (tsp && party[+tsp.dataset.togSp]) { const p = party[+tsp.dataset.togSp]; p.sp = !p.sp; renderAll(); }
  if (go) { goTab(1); setTimeout(() => { const el = $("ov-" + go.dataset.goto); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }, 350); }
});
function bindSetting(id, key, num) {
  const el = $(id);
  if (num) el.value = settings[key]; else el.checked = settings[key];
  el.addEventListener("input", () => { settings[key] = num ? Number(el.value) || 0 : el.checked; renderAll(); });
}
bindSetting("s-edef", "edef", true); bindSetting("s-eatk", "eatk", true); bindSetting("s-giant", "giant", true); bindSetting("s-cond", "cond"); bindSetting("s-target", "target");
(() => { let t = 0; try { t = Number(localStorage.getItem(LS_TAB)) || 0; } catch {} t = Math.min(Math.max(0, t), pages.length - 1); requestAnimationFrame(() => goTab(t, false)); })();

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
    if (!sampleFn && !localStorage.getItem(LS_KEY)) { $("import-msg").textContent = "スクショの読み取りには、「設定」タブでAPIキーを入れてください。名前の入力でも読み込めます。"; return; }
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

# -*- coding: utf-8 -*-
"""渲染层：封面（6 主题 × 3 模板 × 2 尺寸 × 3 留白 × 水印）与视频卡片帧（3 模板）。

画布比例锁死：竖 1080×1920(9:16)、横 1920×1080(16:9)，内容只在画布内自适应。
三层分工：封面只有 序号/标题（不显示分类标签）；视频卡片才有 标题/摘要/来源(平台+完整地址)。
"""
import os, json, math, re
import source as SRC   # 期号规范化与各处共享
from PIL import Image, ImageDraw, ImageFont

THEMES = {
    'deep_blue': {'n': '深墨蓝', 'bg': '#0d1b2a', 'txt': '#f2f6fb', 'sub': '#a9bdd4', 'line': 'rgba(255,255,255,.10)', 'card': 'rgba(255,255,255,.045)', 'acc': '#e6432f', 'dark': True},
    'obsidian':  {'n': '曜石黑', 'bg': '#14161a', 'txt': '#f5f6f8', 'sub': '#a7adb8', 'line': 'rgba(255,255,255,.09)', 'card': 'rgba(255,255,255,.04)',  'acc': '#e6432f', 'dark': True},
    'indigo':    {'n': '靛蓝夜', 'bg': '#101a38', 'txt': '#f2f5ff', 'sub': '#a9b8de', 'line': 'rgba(255,255,255,.10)', 'card': 'rgba(255,255,255,.045)', 'acc': '#e6432f', 'dark': True},
    'daylight':  {'n': '晨光白', 'bg': '#f7f9fc', 'txt': '#16283f', 'sub': '#5a6c82', 'line': 'rgba(16,40,63,.13)',  'card': 'rgba(16,40,63,.035)',  'acc': '#c8321f', 'dark': False},
    'paper':     {'n': '暖米纸', 'bg': '#faf5ea', 'txt': '#2a2118', 'sub': '#756454', 'line': 'rgba(42,33,24,.13)',  'card': 'rgba(42,33,24,.035)',  'acc': '#c03a24', 'dark': False},
    'ice':       {'n': '浅冰蓝', 'bg': '#f0f6fc', 'txt': '#12263d', 'sub': '#5a7390', 'line': 'rgba(18,38,61,.12)',  'card': 'rgba(18,38,61,.035)',  'acc': '#c8321f', 'dark': False},
}
SIZES = {'portrait': (1080, 1920), 'landscape': (1920, 1080),
         'xhs': (1080, 1440), 'wechat': (1080, 1260), 'square': (1080, 1080)}
# 平台 -> 成品文件名中缀；页面 / 服务端 / 出品 CLI 共用
ENAME = {'portrait': '竖版9比16', 'landscape': '横版16比9',
         'xhs': '小红书3比4', 'wechat': '视频号6比7', 'square': '方形1比1'}
def is_land(size):
    w, h = SIZES.get(size, SIZES['portrait'])
    return w > h
# 两条横线 / 日期基线按画布高度归一：新增 3:4 / 6:7 / 1:1 不会撑破画面
_GEOM = {'line1': (272 / 1080.0, 328 / 1920.0),
         'line2': (856 / 1080.0, 1512 / 1920.0),
         'date_y': (226 / 1080.0, 262 / 1920.0)}
def card_geom(name, W, H):
    lr, pr = _GEOM[name]
    return int(round(H * (lr if W > H else pr)))
GAPS = {'compact': {'gap': .18, 'pad': .55}, 'standard': {'gap': .62, 'pad': .80}, 'airy': {'gap': 1.0, 'pad': 1.0}}
AVOID_HEAD = set('，。；：！？、）》」』】,.!?;:)]}')


HEAD_DATE_GAP = 82   # 日期牌中心距标题块底部；与 index.html 同值（原 46，标题与日期贴太近）
HEAD_RULE_AT = 126  # 日期牌下方分隔线位置；与页面同值
HEAD_TITLE_AT = 72  # 主标题起点（期号胶囊放大后避免压字）
CARD_HDR_FS = 28    # 视频卡片顶部「今日要闻速览 · 日期」字号（原 19）
CARD_NO_FS = 30     # 「NO.xx · 分类标签」字号（原 21）
CARD_META_LIFT = .62  # 元信息向主文字提亮比例（原纯 sub 太浅）
CARD_DATE_Y = 42        # 顶部日期/分类标签基线上移，贴顶部红线下
CARD_BOX_TOP = 126      # 卡片框顶（页面与服务端同值）
CARD_BOX_BOTTOM = 40    # 卡片框距画布底部（不再给字幕预留大片空白）
CARD_TITLE_PORTRAIT = 80    # 标题放大（原 70）
CARD_TITLE_LANDSCAPE = 70   # 横版标题放大（原 60）
CARD_INK_DARK = '#f4f8fd'    # 深主题标题：近白
CARD_INK_LIGHT = '#0e1724'   # 浅主题标题：中性深墨（浅冰蓝下不再用主题蓝）
TOKEN_CH = set('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.%+-/:_?=&#~@')

# ---- r14：封面资讯标题样式，四套模板共用（字体 / 字号 / 颜色 / 加粗）----
# 与页面 COVER_ITEM_FONTS 同源；wqy 与 mono 是随包 ttc 的两个真实 face，
# noto / serif 用系统中文字体，缺失时自动回退 wqy 并在 meta 记录。
COVER_ITEM_FONT_MAP = {
    'wqy':   [('assets/fonts/wqy-microhei.ttc', 0), ('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', 0)],
    'mono':  [('assets/fonts/wqy-microhei.ttc', 1), ('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', 1)],
    'noto':  [('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 0)],
    'serif': [('/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc', 0)],
}
_COVER_FONT_FAMILY = 'wqy'
_CF_CACHE = {}


def set_cover_font(cfg):
    global _COVER_FONT_FAMILY
    st = cfg.get('item_style') or {}
    _COVER_FONT_FAMILY = (st.get('font') or cfg.get('item_font') or
                          cfg.get('itemFont') or 'wqy')


def CF(size, root, bold=False):
    # 与 F 同签名，但按当前封面标题字族选字体；带缓存。
    key = (int(size), bool(bold), _COVER_FONT_FAMILY)
    if key in _CF_CACHE:
        return _CF_CACHE[key]
    fam = _COVER_FONT_FAMILY
    cands = list(COVER_ITEM_FONT_MAP.get(fam) or COVER_ITEM_FONT_MAP['wqy'])
    cands += [('assets/fonts/wqy-microhei.ttc', 0),
              ('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', 0),
              ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 0),
              ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 0)]
    f = None
    for rel, idx in cands:
        fp = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if os.path.isfile(fp):
            try:
                f = ImageFont.truetype(fp, int(size), index=idx)
                break
            except OSError:
                continue
    if f is None:
        f = F(int(size), root, bold)
    _CF_CACHE[key] = f
    return f


def cover_item_style(cfg, theme, u, size):
    st = cfg.get('item_style') or {}
    raw = st.get('size', cfg.get('item_fs', cfg.get('itemFs', 0)))
    try:
        base = float(raw)
    except (TypeError, ValueError):
        base = 0.0
    if base <= 0:
        base = 34.0 if is_land(size) else 38.0
    color = (st.get('color') or cfg.get('item_color') or
             cfg.get('itemColor') or '')
    auto = st.get('auto_color', cfg.get('item_auto_color', cfg.get('itemAutoColor', True)))
    col = rgb(color) if (color and not auto) else rgb(theme['txt'])
    bold = bool(st.get('bold', cfg.get('item_bold', cfg.get('itemBold', True))))
    return _COVER_FONT_FAMILY, base * u, col, bold, base
# 来源行里的 URL 整段作为不可断原子；末尾遇到中文标点即止。
URL_RE = re.compile(r'https?://[^\s，。；：、）】》」』]+')
URL_HEAD = re.compile(r'(https?://[^/?#]+)(.*)$', re.S)
URL_SEG = re.compile(r'[^/?&=]*[/?&=]|[^/?&=]+')


def card_title(theme):
    """标题色随主题背景亮度反相，浅冰蓝等浅底一律用中性深墨，保证不糊。"""
    b = rgb(theme['bg'])
    lum = .2126 * b[0] + .7152 * b[1] + .0722 * b[2]
    return rgb(CARD_INK_DARK if lum < 127.5 else CARD_INK_LIGHT)
SUM_BASE_MIX = .58        # 摘要从副色向主文字混合比例（标题保持 fg，不再同为一片白）
SUM_COOL_DARK = '#8fb2d4'
SUM_COOL_LIGHT = '#3c5a7d'
SUM_COOL_MIX = .20         # 再向冷蓝偏，形成明确色相层级

DATE_FS = 38        # 日期牌字号（原 30）
DATE_BH = 62        # 日期牌高度（原 48）
ISSUE_FS = 38       # 期号胶囊字号（原 30）
ISSUE_BH = 68       # 期号胶囊高度（原 56）
LEAD_GOLD_DARK = '#ffc75c'   # 重点句强调色（深主题：琥珀金）
LEAD_GOLD_LIGHT = '#9e600c'  # 重点句强调色（浅主题：压深琥珀）
CARD_SUM_PORTRAIT = 50       # 摘要字号（竖版）
CARD_SUM_LANDSCAPE = 44      # 摘要字号（横版）
CARD_SRC_FS = 32             # 来源字号（放大且紧跟摘要）
# 卡片报头：与封面截图2 同结构（朱红短横＋DAILY BRIEF 眉标 / 期号胶囊右上 /
# 大标题独占一行 / 日期纯文字在标题下方 / 细分隔线）。横版高度只有竖版一半，按高度紧凑化。
CARD_KICKER_FS = 24
CARD_HEAD_TITLE_P = 60
CARD_HEAD_TITLE_L = 48
CARD_HEAD_TOP = 34
CARD_HEAD_TITLE_AT = 60
CARD_HEAD_DATE_GAP_P = 52
CARD_HEAD_DATE_GAP_L = 44
CARD_HEAD_RULE_AT_P = 78
CARD_HEAD_RULE_AT_L = 66
CARD_HEAD_PAD_P = 16
CARD_HEAD_PAD_L = 10
CARD_META_GAP_P = 40
CARD_META_GAP_L = 24
CARD_CONTENT_GAP_P = 66
CARD_CONTENT_GAP_L = 44

# ------------------------------------------------------------------ v12 / v11 卡片排版常量
# 报头三件套竖横共用同一组字号（50 / 32 / 30），两条横线的绝对位置一寸不动。
CARD_BRAND_FS = 50
CARD_DATE_FS = 32
CARD_ISSUE_FS = 30
CARD_LINE1_P, CARD_LINE1_L = 328, 272
CARD_LINE2_P, CARD_LINE2_L = 1512, 856
CARD_BODY_P, CARD_BODY_L = 42, 38
CARD_TITLE_FS_P, CARD_TITLE_FS_L = 60, 54
CARD_INDENT_P, CARD_INDENT_L = 84, 76
CARD_PARA_GAP_P, CARD_PARA_GAP_L = 80, 64
CARD_BG_ALPHA_DARK = .62
CARD_BG_ALPHA_LIGHT = .68
# 本版起停用原文图片背景：日期下移、来源与线2距离放大；上/下横线位置保持不动
CARD_DATE_Y_P, CARD_DATE_Y_L = 262, 226
CARD_SRC_GAP_P, CARD_SRC_GAP_L = 96, 72

# ---- r22：字幕安全带（页面 / 播放器 / 服务端同源；默认 0 保持基准画幅逐像素不变） ----
SUBTITLE_SAFE_U = 0


def subtitle_safe_u(cfg):
    c = cfg if isinstance(cfg, dict) else {}
    if not c.get('on') or not c.get('burn_in'):
        return 0
    lines = max(1, min(5, int(c.get('max_lines', 2))))
    fs = int(c.get('font_size', 44))
    return int(lines * fs * 1.5 + fs * .9)


CARD_BG_ENABLED = False
# r19：短画幅改为「大字优先 + 下横线/来源随内容自适应下移」。
# 3:4 / 6:7 / 1:1 与 9:16 一样宽，按高度线性缩字号只会看不清；
# 横线与来源也不再钉在固定比例位置，跟着摘要末尾走，腾出的高度全部让给字号。
CARD_SHORT_FS_MIN = 1.0      # 短画幅正文不低于基准画幅字号
CARD_SHORT_FS_BOOST = 1.12   # 短画幅正文/摘要在基准上再放大 12%
CARD_SHORT_FLOOR_P, CARD_SHORT_FLOOR_L = 40, 36  # 极端长文的可读下限（原 32）
CARD_SHORT_BOTTOM_PAD = 40   # 来源下方固定内边距（单位 u）
CARD_SHORT_TITLE_MAX = 1.0   # 标题不跟着放大，省下行数给摘要
CARD_SHORT_LINE_GAP = 44     # 摘要末尾到下横线净距（单位 u，原 60）
CARD_SHORT_BLH = 1.40        # 短画幅行距系数（原 1.48，略收紧换字号）
CARD_SHORT_HDR_MIN = .84   # 短画幅报头 42/27/25（原 37/24/22），起点同步上移避免叠字
CARD_SHORT_BRAND_AT = 136  # 短画幅大标题起点（原 148u），给放大的报头让出净距

# r14：折行只保留「数字/小数/单位」原子 + 单字，删除词组表。
# 词组整块保护会把放不下的词整体推到下一行，右侧留一大片空白（用户反复指出的提前换行）。
_FILL_TOK = re.compile(r'[0-9A-Za-z.:/%+\-]+[\u4e00-\u9fff]?|.', re.S)
_FILL_NOHEAD = set('，。、；：？！）】》”’、,.;:!?%)]}>')


def fill_wrap(d, text, font, maxw, indent=0):
    """逐字按真实像素折行填满；数字/小数/单位当原子不拆、标点不落行首。
    返回 [(行, 首行缩进)]。r14 去掉词组保护，右侧不再提前留白。"""
    lines, cur, first = [], '', True
    for tk in _FILL_TOK.findall(str(text)):
        avail = (maxw - indent) if first else maxw
        if d.textlength(cur + tk, font=font) > avail * 1.01 and cur:
            lines.append([cur, indent if first else 0]); cur, first = tk, False
        else:
            cur += tk
    if cur:
        lines.append([cur, indent if first else 0])
    for i in range(len(lines) - 1):
        nxt = lines[i + 1][0]
        while nxt and nxt[0] in _FILL_NOHEAD:
            cand = lines[i][0] + nxt[0]
            if d.textlength(cand, font=font) <= maxw + font.size * .4:
                lines[i][0] = cand; nxt = nxt[1:]; lines[i + 1][0] = nxt
            else:
                break
    if len(lines) >= 2:
        target = max(font.size * 2.2, maxw * .12)
        while d.textlength(lines[-1][0], font=font) < target:
            tks = _FILL_TOK.findall(lines[-2][0])
            if len(tks) <= 1 or d.textlength(lines[-2][0], font=font) < maxw * .62:
                break
            lines[-2][0] = ''.join(tks[:-1]); lines[-1][0] = tks[-1] + lines[-1][0]
    return [(a, b) for a, b in lines]


# r25：分类标签线稿纹样 —— 程序化绘制，无外部图片依赖，前后端同源。
# 六类关键词映射到六种几何母题；只画低对比度线稿，不压正文。
CAT_ART_RULES = [
    ('tech',    ('芯片', '算力', '人工智能', 'AI', '新能源', '科技', '数据', '卫星', '标准')),
    ('finance', ('股', '美股', '金融', '央行', 'LPR', '外贸', '进博会', '利润', '产业', '成交', '融资', '房价', '房贷')),
    ('law',     ('司法', '命案', '法院', '宣判', '反诈', '诈骗', '辟谣', '监管', '侵权', '使馆')),
    ('health',  ('流感', '疾控', '健康', '疫苗', '医疗', '创新药', '医保', '呼吸道')),
    ('traffic', ('天气', '交通', '大雾', '预警', '地震', '事故', '出行', '降雨', '暴雪')),
    ('civic',   ('民生', '油价', '成品油', '社保', '最低工资', '基层', '养老', '乡村', '消费', '班列', '治理')),
]
CAT_ART_STRENGTH = {'light': 0.20, 'medium': 0.32, 'strong': 0.46}


def category_kind(card):
    lab = str(card.get('label') or '') + str(card.get('title') or '')
    for kind, keys in CAT_ART_RULES:
        if any(k in lab for k in keys):
            return kind
    return 'civic'


def draw_category_art(im, card, theme, strength='light'):
    """在卡片底图上叠一层分类线稿；失败静默回退纯色，不影响出片。"""
    try:
        a = CAT_ART_STRENGTH.get(str(strength), 0.10)
        base = rgb(theme['bg'])
        ink = rgb(theme['sub'])
        col = mix(base, ink, a)
        W, H = im.size
        d = ImageDraw.Draw(im)
        kind = category_kind(card)
        cx, cy = int(W * 0.78), int(H * 0.66)
        rr = int(min(W, H) * 0.17)
        lw = max(2, int(min(W, H) * 0.0028))
        if kind == 'tech':
            n = 5
            step = rr * 2 // n
            for i in range(n + 1):
                x = cx - rr + i * step
                d.line([x, cy - rr, x, cy + rr], fill=col, width=lw)
                y = cy - rr + i * step
                d.line([cx - rr, y, cx + rr, y], fill=col, width=lw)
            d.rectangle([cx - rr // 3, cy - rr // 3, cx + rr // 3, cy + rr // 3],
                        outline=col, width=lw * 2)
        elif kind == 'finance':
            for i in range(5):
                y = cy - rr + i * rr // 2
                d.line([cx - rr, y, cx + rr, y], fill=col, width=lw)
            pts = [(cx - rr + i * rr // 3, cy + rr // 2 - int(rr * v))
                   for i, v in enumerate((0.1, 0.4, 0.3, 0.75, 0.6, 0.95, 0.8))]
            d.line(pts, fill=col, width=lw * 2)
        elif kind == 'law':
            d.line([cx, cy - rr, cx, cy + rr], fill=col, width=lw * 2)
            d.line([cx - rr, cy - rr // 2, cx + rr, cy - rr // 2], fill=col, width=lw)
            for side in (-1, 1):
                x = cx + side * rr * 0.7
                d.line([x, cy - rr // 2, x, cy], fill=col, width=lw)
                d.arc([x - rr // 4, cy, x + rr // 4, cy + rr // 2], 0, 180,
                      fill=col, width=lw)
        elif kind == 'health':
            for i in range(1, 5):
                r = rr * i // 4
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=lw)
        elif kind == 'traffic':
            for i in range(-3, 4):
                d.line([cx, cy, cx + i * rr // 3, cy + rr], fill=col, width=lw)
            for i in range(1, 5):
                y = cy + rr * i // 5
                d.line([cx - rr, y, cx + rr, y], fill=col, width=lw)
        else:
            for i in range(1, 5):
                r = rr * i // 4
                d.arc([cx - r, cy - r, cx + r, cy + r], 20, 340, fill=col, width=lw)
        return True
    except Exception:
        return False


def _card_bg(root, card, W, H, theme):
    """原文图片铺底实现保留但由 CARD_BG_ENABLED 关闭；本版起渲染层一律纯色。
    下载失败/无值一律回退纯色，不报错、不占流程。"""
    url = str(card.get('bg_image') or '').strip()
    if not url or url.startswith('data:') or not url.startswith(('http://', 'https://')):
        return None
    import urllib.request, hashlib
    cache = os.path.join(root, 'media', 'orig')
    fp = os.path.join(cache, hashlib.md5(url.encode('utf-8')).hexdigest()[:16] + '.img')
    if not os.path.isfile(fp):
        try:
            os.makedirs(cache, exist_ok=True)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = r.read()
            if len(data) < 1000:
                return None
            with open(fp, 'wb') as f:
                f.write(data)
        except Exception:
            return None
    try:
        bg = Image.open(fp).convert('RGB')
    except Exception:
        return None
    sw, sh = bg.size
    sc = max(W / max(1, sw), H / max(1, sh))
    bg = bg.resize((max(1, int(sw * sc)), max(1, int(sh * sc))), Image.LANCZOS)
    l, t = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((l, t, l + W, t + H))
    base = Image.new('RGB', (W, H), rgb(theme['bg']))
    return Image.blend(bg, base, CARD_BG_ALPHA_DARK if theme.get('dark') else CARD_BG_ALPHA_LIGHT)



def cover_count(cfg, payload):
    """显示条数：来自 cover_theme.json / data_source.json / data.json，缺省 8。"""
    v = cfg.get('count', payload.get('cover_count', 8))
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = 10
    return max(1, min(v, len(payload.get('cover') or []) or 10))

_FONT_CACHE = {}


def font_path(root):
    for p in [os.path.join(root, 'assets', 'fonts', 'wqy-microhei.ttc'),
              '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if os.path.isfile(p):
            return p
    return None


def F(size, root, bold=False):
    key = (int(size), bold)
    if key not in _FONT_CACHE:
        p = font_path(root)
        try:
            _FONT_CACHE[key] = ImageFont.truetype(p, int(size)) if p else ImageFont.load_default()
        except OSError:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def rgb(hexs):
    h = hexs.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(bg, fg, a):
    return tuple(int(bg[i] * (1 - a) + fg[i] * a) for i in range(3))


def rgba_color(s, base):
    """把 'rgba(r,g,b,a)' 混到纯色底上，避免半透明直接写进 RGB 底图丢 alpha。"""
    if not s.startswith('rgba'):
        return rgb(s)
    nums = s[s.find('(') + 1:s.find(')')].split(',')
    fg = tuple(int(float(x)) for x in nums[:3])
    a = float(nums[3])
    return mix(base, fg, a)


def wrap(draw, text, font, maxw, avoid=True, keep_token=False):
    """按像素宽度断行；闭标点不落在行首；不截断文本。"""
    lines, cur = [], ''
    for ch in text:
        if ch == '\n':
            lines.append(cur); cur = ''; continue
        t = cur + ch
        if cur and draw.textlength(t, font=font) > maxw:
            if avoid and ch in AVOID_HEAD and cur:
                # 把闭标点挤到上一行末尾（允许轻微超宽）
                lines.append(cur + ch); cur = ''
                continue
            if keep_token:
                cut = len(cur)
                while cut > 0 and cur[cut - 1] in TOKEN_CH:
                    cut -= 1
                if 0 < cut < len(cur):
                    lines.append(cur[:cut]); cur = cur[cut:] + ch
                    continue
            lines.append(cur); cur = ch
        else:
            cur = t
    if cur:
        lines.append(cur)
    # 末行避免孤字：从上一行末尾挪 1-2 字下来，不截断、不超宽
    if len(lines) >= 2 and len(lines[-1]) <= 2:
        prev = lines[-2]
        mv = 3 - len(lines[-1])
        if keep_token:
            j = len(prev) - mv
            while j > 0 and prev[j - 1] in TOKEN_CH:
                mv += 1; j -= 1
        if len(prev) > mv + 1:
            lines[-2] = prev[:-mv]
            lines[-1] = prev[-mv:] + lines[-1]
    return lines


def _url_segments(url):
    """超长 URL 的安全断点：scheme+host 整段不可拆，之后只允许在 / ? & = 之后断。
    https:// 前缀与 content_ 这类下划线串不会被拆开。"""
    m = URL_HEAD.match(url)
    if not m:
        return [url]
    head, rest = m.group(1), m.group(2)
    segs = [head]
    for part in URL_SEG.findall(rest):
        if part:
            segs.append(part)
    return segs


def wrap_source(draw, text, font, maxw, root, base_fs, min_fs):
    """来源行折行：URL 优先整段不可断，https:// 前缀永不拆。

    折行点只允许落在 URL 之前（或 ' · ' 之后）；URL 独占一行仍超宽时，
    只在 / ? & = 这些安全断点后分段折行，绝不劈开 https: 或 content_。
    仍超宽的行按宽度比例单独缩字号（标签行保持原字号）。
    返回 [(line, font)]，页面 wrapSourceText 与之同源。
    """
    text = str(text)
    atoms, pos = [], 0
    for m in URL_RE.finditer(text):
        if m.start() > pos:
            atoms.append((text[pos:m.start()], False))
        atoms.append((m.group(), True))
        pos = m.end()
    if pos < len(text):
        atoms.append((text[pos:], False))
    if not atoms:
        atoms = [(text, False)]

    def width(s):
        return draw.textlength(s, font=font)

    raw, cur = [], ''
    for seg, is_url in atoms:
        if is_url:
            trial = cur + seg
            if not cur or width(trial) <= maxw:
                cur = trial
                continue
            raw.append(cur.rstrip())
            cur = ''
            if width(seg) <= maxw:
                cur = seg
            else:
                # 超长 URL：按安全断点分段，前缀与下划线串不被拆
                for us in _url_segments(seg):
                    t = cur + us
                    if cur and width(t) > maxw:
                        raw.append(cur.rstrip())
                        cur = us
                    else:
                        cur = t
        else:
            for ch in seg:
                t = cur + ch
                if cur and width(t) > maxw:
                    raw.append(cur.rstrip())
                    cur = ch
                else:
                    cur = t
    if cur:
        raw.append(cur.rstrip())

    out = []
    for ln in raw:
        fs, f = base_fs, F(base_fs, root)
        w = draw.textlength(ln, font=f)
        if w > maxw:
            fs = max(min_fs, int(fs * maxw / w))
            f = F(fs, root)
        out.append((ln, f))
    return out


def txt(draw, xy, s, font, fill, bold=False, anchor=None):
    # 小字号不再加描边：文泉驿的横画密集字（如「量」）会被 1px 描边糊成方块
    sw = 1 if bold and getattr(font, 'size', 0) >= 64 else 0
    if sw:
        draw.text(xy, s, font=font, fill=fill, anchor=anchor, stroke_width=sw, stroke_fill=fill)
    else:
        draw.text(xy, s, font=font, fill=fill, anchor=anchor)


# ------------------------------------------------------------------ 封面
def render_cover(root, payload, cfg, out_path, meta_path=None):
    set_cover_font(cfg)
    if cfg.get('tpl') == 'semantic':
        return render_semantic_cover(root, payload, cfg, out_path, meta_path)
    theme = THEMES.get(cfg.get('theme', 'deep_blue'), THEMES['deep_blue'])
    tpl = cfg.get('tpl', 'rank')
    size = cfg.get('size', 'portrait')
    gapmode = cfg.get('gap', 'airy')
    wm = cfg.get('wm') or {}
    head = cfg.get('cover_header') or payload.get('cover_header') or {}
    issue = cfg.get('issue') or payload.get('issue_cfg') or {}
    W, H = SIZES.get(size, SIZES['portrait'])
    # 短画幅整张等比：3:4 / 6:7 / 1:1 的报头、字号、间距、横线同源缩放；
    # 9:16 与 16:9 的 u 仍为 1，逐像素不变。
    u = H / (1080.0 if is_land(size) else 1920.0)
    base = rgb(theme['bg'])
    line_c = rgba_color(theme['line'], base)
    acc = rgb(theme['acc'])
    fg = rgb(theme['txt'])
    sub = rgb(theme['sub'])
    dark = theme['dark']
    _cis = cover_item_style(cfg, theme, u, size)
    item_col, item_bold = _cis[2], _cis[3]

    # 04 起用反相高对比实色块：深底→浅块深字，浅底→深块白字
    chip_bg = rgb('#dbe8f8') if dark else rgb('#16283f')
    soft_ink = rgb('#101f33') if dark else (255, 255, 255)
    edge = chip_bg
    num_soft = soft_ink

    im = Image.new('RGB', (W, H), base)
    d = ImageDraw.Draw(im)
    boxes = []

    # 顶部朱红细线
    d.rectangle([0, 0, W, max(3, int(6 * u))], fill=acc)

    pad = int(58 * u)
    y = int(86 * u)
    show_title = head.get('show_title', True)
    show_date = head.get('show_date', True)
    show_issue = head.get('show_issue', True)

    if show_title:
        fs = int(100 * u)
        f = F(fs, root, True)
        title = head.get('title', '今日要闻速览')
        txt(d, (pad, y), title, f, fg, True)
        y += int(fs * 1.22)
        d.rectangle([pad, y + int(14 * u), pad + int(96 * u), y + int(20 * u)], fill=acc)
        y += int(52 * u)
    else:
        y += int(24 * u)

    # 榜单模板与语义版共用报头标签：日期纯文字无底色、期号朱红实底白字，字号统一放大。
    rco = _sem_palette(theme)
    if show_date:
        f = F(int(DATE_FS * u), root, True)
        dl = issue.get('date_line') or payload.get('date', '')
        # 与语义版同一套报头几何：中心距标题块底部 HEAD_DATE_GAP*u
        _date_badge(d, pad, y, dl, f, rco, u)
    if show_issue:
        f = F(int(ISSUE_FS * u), root, True)
        s = SRC.norm_issue(issue.get('issue_no') or payload.get('issue') or '第01期')
        _issue_badge(d, W - pad, y + HEAD_DATE_GAP * u, s, f, rco, u)
    y += int(138 * u) if (show_date or show_issue) else int(30 * u)
    head_bottom = y

    # 内容区：条数可设置；竖版单列 N 行，横版 2 列（前 ceil(N/2) 左、其余右）
    n = cover_count(cfg, payload)
    items = payload['cover'][:n]
    cols = 2 if (is_land(size) and n >= 2) else 1
    rows = math.ceil(n / cols)
    bottom_pad = int(58 * u)
    avail = H - head_bottom - bottom_pad
    colw = (W - 2 * pad - (cols - 1) * int(30 * u)) / cols
    fill = {'compact': .99, 'standard': .98, 'airy': .96}.get(gapmode, .96)
    # 行距由留白档位给定上限，条数多时自动收紧但不撑满；
    # 整组资讯作为一个块在内容区上下居中，字号不因条数少而放大。
    wanted_gap = int({'compact': 16, 'standard': 28, 'airy': 40}.get(gapmode, 40) * u)
    min_gap = max(2, int(3 * u))
    cap = avail * (.99 if rows >= 8 else fill) / rows

    k = .86 if is_land(size) else 1.0
    badge = int(50 * k * u)
    num_fs = int(30 * k * u)
    nf = F(num_fs, root, True)
    # 字号固定，不随条数放大：条数少时 cell_h 变大，内容在行内垂直居中，
    # 多出来的高度全部变成行间留白；只在确实放不下时才缩小。
    min_fs = int(24 * u)
    # r14：默认与语义编排等权列表一致（竖38 / 横34），可在 03 区灵活设置
    title_fs = int(_cis[1])
    line_factor = 1.18
    tx_off = int(20 * u) + badge + int(20 * u)
    # 「头条」胶囊只占第一条右上角；其余条用全宽，不再提前折行留出大片空白
    maxw = colw - tx_off - int(22 * u)
    maxw0 = maxw - (int(120 * u) if tpl == 'headline' else 0)

    def _measure(fs):
        f = CF(fs, root)
        out = []
        for idx, it in enumerate(items):
            mw = maxw0 if (tpl == 'headline' and idx == 0) else maxw
            ls = wrap(d, it['title'], f, mw)
            th = len(ls) * int(fs * line_factor)
            out.append((ls, max(badge, th), th))
        return f, out

    tf, blocks = _measure(title_fs)

    def _fits(bs):
        return max(b[1] for b in bs) + min_gap <= cap

    while title_fs > min_fs and not _fits(blocks):
        title_fs -= max(1, int(1 * u))
        tf, blocks = _measure(title_fs)

    max_bh = max(b[1] for b in blocks)
    row_gap = min(wanted_gap, max(min_gap, int(cap - max_bh)))
    row_h = max_bh + row_gap
    block_h = rows * row_h
    top = head_bottom + max(0, (avail - block_h) / 2)
    cell_h = row_h  # 兼容旧校验字段：每行高度

    band = mix(base, (255, 255, 255) if dark else (0, 0, 0), .075)
    sep_mode = _sep_mode(cfg)
    plain_num = (tpl == 'list')
    for i, it in enumerate(items):
        c = i // rows
        r = i % rows
        x0 = pad + c * (colw + int(30 * u))
        y0 = top + r * row_h
        x1, y1 = x0 + colw, y0 + row_h
        boxes.append([x0, y0, x1, y1])
        ls, bh, th = blocks[i]
        cy = y0 + (row_h - bh) / 2
        by = cy + (bh - badge) / 2

        # 条目分隔：五套方案统一入口，与页面 sepPaint 同源
        _sep_paint(d, {'bg': base, 'dark': dark, 'acc': acc, 'line': line_c},
                   sep_mode, x0, y0 + 2 * u, x1, y1 - 2 * u, r, i < 3, u, cfg)
        no_decor = (sep_mode == 'none')
        # 结构差异：榜单卡片=逐行圆角卡；极简列表=顶部细线+纯文字序号；报头重点=首条头条块
        if tpl == 'rank':
            if i < 3 and not no_decor:
                d.rectangle([x0, y0 + 3 * u, x0 + 6 * u, y1 - 3 * u], fill=acc)
        elif tpl == 'list':
            if not no_decor:
                d.line([x0, y0, x1, y0], fill=line_c, width=1)
        else:
            if i == 0:
                d.rounded_rectangle([x0, y0 + 2 * u, x1, y1 - 2 * u],
                                    radius=int(10 * u), fill=mix(base, acc, .16))
                d.rectangle([x0, y0 + 2 * u, x0 + 10 * u, y1 - 2 * u], fill=acc)
                # 「头条」角标移到卡片右上角：朱红实底胶囊 + 白字，字号放大，不与标题抢位
                tag_f = F(int(28 * u), root, True)
                tag_w = d.textlength('头条', font=tag_f) + 40 * u
                tag_h = 44 * u
                tag_x, tag_y = x1 - tag_w - 14 * u, y0 + 8 * u
                d.rounded_rectangle([tag_x, tag_y, tag_x + tag_w, tag_y + tag_h],
                                    radius=tag_h / 2, fill=acc)
                txt(d, (tag_x + tag_w / 2, tag_y + tag_h / 2), '头条', tag_f,
                    (255, 255, 255), True, 'mm')
            else:
                if not no_decor:
                    d.line([x0, y1 - 1, x1, y1 - 1], fill=line_c, width=1)

        strong = i < 3
        bx = x0 + int(20 * u)
        if plain_num:
            txt(d, (bx, cy + bh / 2), '%02d' % it['rank'], nf,
                acc if strong else fg, True, 'lm')
        else:
            if strong:
                d.rounded_rectangle([bx, by, bx + badge, by + badge], radius=int(11 * u), fill=acc)
                numc = (255, 255, 255)
            else:
                d.rounded_rectangle([bx, by, bx + badge, by + badge], radius=int(11 * u),
                                    fill=chip_bg, outline=edge, width=max(1, int(2 * u)))
                numc = num_soft
            txt(d, (bx + badge / 2, by + badge / 2), '%02d' % it['rank'], nf, numc, True, 'mm')

        tx = x0 + (int(20 * u) + int(70 * u) if plain_num else tx_off)
        ty = cy + (bh - th) / 2
        for ln in ls:
            txt(d, (tx, ty), ln, tf, item_col, item_bold)
            ty += int(title_fs * line_factor)

    # 水印：只画在底部预留区或内容之下，不压正文
    if wm.get('on'):
        a = float(wm.get('alpha', .12))
        wf = F(int(30 * u), root)
        s = str(wm.get('text', ''))
        pos = wm.get('pos', 'bottom_right')
        wcol = mix(base, fg, a)
        if pos in ('bottom_right', 'bottom_left'):
            wy = H - int(30 * u)
            tw = d.textlength(s, font=wf)
            wx = W - pad - tw if pos == 'bottom_right' else pad
            txt(d, (wx, wy), s, wf, wcol, anchor='lm')
        elif pos == 'center':
            txt(d, (W / 2, H / 2), s, F(int(96 * u), root), wcol, anchor='mm')
        else:
            for yy in range(int(120 * u), H, int(220 * u)):
                for xx in range(int(40 * u), W, int(420 * u)):
                    txt(d, (xx, yy), s, wf, wcol)

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    im.save(out_path)
    meta = {'type': 'cover', 'w': W, 'h': H, 'theme': cfg.get('theme'), 'tpl': tpl,
            'size': size, 'gap': gapmode, 'boxes': boxes,
            'used': max(b[1] for b in blocks), 'avail': avail,
            'head_bottom': head_bottom, 'watermark': bool(wm.get('on')),
            'count': n, 'cols': cols, 'rows': rows,
            'items': len(items), 'title_fs': title_fs, 'cell_h': round(cell_h, 2),
            'row_h': round(row_h, 2), 'row_gap': row_gap,
            'centered': True, 'top_gap': round(top - head_bottom, 2),
            'bottom_gap': round(H - bottom_pad - (top + block_h), 2),
            'whitespace': round((avail - block_h) / 2, 2),
            'fixed_font': True, 'label_chip': False, 'divider': tpl != 'list',
            'item_style': {'font': _cis[0], 'fs': title_fs, 'color': list(item_col), 'bold': item_bold,
                           'base_px': _cis[4], 'font_fallback': _cis[0] != _COVER_FONT_FAMILY},
            'sep': sep_mode, 'row_gap': row_gap,
            'alternate_bands': sep_mode == 'bands', 'template_structure': tpl}
    if meta_path:
        os.makedirs(os.path.dirname(meta_path) or '.', exist_ok=True)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


# ------------------------------------------------------------------ 视频卡片帧
def _summary_blocks(d, text, font, maxw, first_indent=0, first_font=None):
    """摘要不按句末标点分段、不做程序化缩进：只按「重点句\n内容摘要」两块折行。

    重点句来自表格列，由解析层放在首行；这里只负责排版，不推断内容。
    首块用粗体字宽、按「缩进后的实际可用宽度」折行，
    保证首行加两个全角缩进也不越出画面（粗体比常规宽，不能用常规字宽估算）。
    """
    parts = [p for p in str(text or '').split('\n') if p.strip()]
    if not parts:
        parts = ['']
    return [wrap(d, p, (first_font if (i == 0 and first_font) else font),
                 maxw - (first_indent if i == 0 else 0), keep_token=True)
            for i, p in enumerate(parts)]


def render_card(root, card, cfg, out_path, meta_path=None, reveal=1.0):
    """v11 排版：报头 50/32/30、两条浅色横线、三段首行缩进、标题填满折行、
    横版单栏上下排、序号+分类标签去掉、来源只要渠道、内容组靠上不居中。
    「原文图片」列仍随表解析，但本版起不再作背景图，卡片一律纯色底。
    摘要恒等于表格「内容摘要」列，保留 Excel 自带两个全角空格作为首行缩进。
    """
    theme = THEMES.get(cfg.get('theme', 'deep_blue'), THEMES['deep_blue'])
    tpl = cfg.get('tpl', 'frame_card')
    land = is_land(cfg.get('size', 'portrait'))
    W, H = SIZES.get(cfg.get('size', 'portrait'), SIZES['portrait'])
    # 短画幅（3:4 / 6:7 / 1:1）整卡等比：报头、字号、行距、两条横线一起缩放。
    # 旧版只把 line1/line2/date_y 按 H 归一，而 brand_y 与字号固定不缩，
    # 1080 高时日期 y=147 与大标题 y=148 撞在一起、横线穿过文字。
    # 9:16 与 16:9 的 u 仍为 1，逐像素不变。
    u = H / (1080.0 if land else 1920.0)
    short = u < 1
    fs_u = max(u, CARD_SHORT_FS_MIN) * CARD_SHORT_FS_BOOST if short else u
    hdr_u = max(u, CARD_SHORT_HDR_MIN) if short else u
    base = rgb(theme['bg']); sub = rgb(theme['sub'])
    acc = rgb(theme['acc']); line_c = rgba_color(theme['line'], base)
    title_col = card_title(theme)
    meta_col = mix(sub, title_col, CARD_META_LIFT)
    sum_col = mix(mix(sub, title_col, SUM_BASE_MIX),
                  rgb(SUM_COOL_DARK if theme.get('dark') else SUM_COOL_LIGHT), SUM_COOL_MIX)

    im = (_card_bg(root, card, W, H, theme) if CARD_BG_ENABLED else None) or Image.new('RGB', (W, H), base)
    art = cfg.get('category_art') or 'off'
    if art not in ('off', False, None, ''):
        draw_category_art(im, card, theme, cfg.get('category_strength', 'light'))
    d = ImageDraw.Draw(im)
    bg_applied = False
    M = int((120 if land else 96) * u); R = W - M; CW = R - M
    hdr = cfg.get('card_header') or {}
    brand = str(hdr.get('title') or '今日要闻速览')
    date_s = str(hdr.get('date') or '').replace('，', ' · ')
    issue_s = SRC.norm_issue(str(hdr.get('issue') or '第01期'))
    show_t = bool(hdr.get('show_title', True)); show_d = bool(hdr.get('show_date', True))
    show_i = bool(hdr.get('show_issue', True))
    # r32：视频帧逐字 = 卡片标题/摘要按真实进度逐字显现（frames_for 逐字子帧传 reveal）
    rv = max(0.0, min(1.0, float(reveal)))
    ttl = str(card['title'])
    raw_smy = str(card['summary'])

    # 模板不画框/底：v11 版式只有纯背景 + 两条横线，避免与横线叠加
    if tpl == 'frame_headline':
        d.rectangle([0, 0, W, max(1, int(6 * u))], fill=acc)

    # ---- 报头：朱红圆点 + DAILY BRIEF + 期号胶囊 + 大标题 + 日期（纯文字无底色）
    dot_y = int(96 * u); dot_r = int(9 * u)
    d.ellipse([M, dot_y - dot_r, M + 2 * dot_r, dot_y + dot_r], fill=acc)
    _spaced(d, M + int(34 * u), dot_y - int(14 * u), 'D A I L Y   B R I E F',
            F(int(22 * hdr_u), root, True), meta_col, 3 * u)
    issue_fs = int(CARD_ISSUE_FS * hdr_u); f_is = F(issue_fs, root, True)
    iw = int(d.textlength(issue_s, font=f_is)) + int(48 * u)
    ih, iy, ix = int(60 * u), int(70 * u), R - iw
    _bco = _sem_palette(theme)
    _issue_badge(d, R, iy + ih // 2, issue_s, f_is, _bco, u) if show_i else None
    brand_fs = int(CARD_BRAND_FS * hdr_u); date_fs = int(CARD_DATE_FS * hdr_u)
    brand_y = int((124 if land else (CARD_SHORT_BRAND_AT if short else 148)) * u)
    date_y = card_geom('date_y', W, H)
    if show_t:
        txt(d, (M, brand_y), brand, F(brand_fs, root, True), title_col, True)
    if show_d and date_s:
        txt(d, (M, date_y), date_s, F(date_fs, root), meta_col, False, 'lm')

    line1 = card_geom('line1', W, H)
    d.line([M, line1, R, line1], fill=line_c, width=max(1, int(2 * u)))

    # ---- 正文标题：首行缩进 + 填满折行
    indent = int((CARD_INDENT_L if land else CARD_INDENT_P) * fs_u)
    t_u = min(fs_u, CARD_SHORT_TITLE_MAX) if short else fs_u
    title_fs = int((CARD_TITLE_FS_L if land else CARD_TITLE_FS_P) * t_u)
    tlh = int((72 if land else 84) * t_u)
    tf = F(title_fs, root, True)
    ty = line1 + int(44 * u)
    tlines = fill_wrap(d, ttl, tf, CW, indent)

    # ---- 摘要：只取「内容摘要」列；Excel 行首全角空格换算成缩进，其余清掉
    body_fs = int((CARD_BODY_L if land else CARD_BODY_P) * fs_u)
    # 9:16 / 16:9 沿用旧版固定行高，保证基准画幅逐像素不变；短画幅才按字号比例算
    blh = int((54 if land else 62) * u) if not short else int(body_fs * CARD_SHORT_BLH)
    bf = F(body_fs, root)
    excel_indent = len(re.match(r'^[\u3000\u00a0]*', str(raw_smy)).group(0)) * body_fs
    body_txt = re.sub(r'^[\u3000\u00a0]+', '', str(raw_smy)).replace('\u3000', '')
    body_txt = re.sub(r'[ \t]*\n[ \t]*', '', body_txt)
    sind = excel_indent if excel_indent > 0 else indent
    para_gap = int((CARD_PARA_GAP_L if land else CARD_PARA_GAP_P) * u)
    slines = fill_wrap(d, body_txt, bf, CW, sind)
    line2_target = card_geom('line2', W, H)
    min_fs = int((32 if land else 36) * fs_u)
    truncated = False
    src_gap_v = int((CARD_SRC_GAP_L if land else CARD_SRC_GAP_P) * u)
    src_lh_v = int((34 if land else 40) * u)
    safe_u = min(int(SUBTITLE_SAFE_U * H / 1920.0),
                 max(0, H - line2_target - src_gap_v - src_lh_v - int(CARD_SHORT_BOTTOM_PAD * u)))
    max_line2 = H - src_gap_v - src_lh_v - int(CARD_SHORT_BOTTOM_PAD * u) - safe_u

    def _need():
        return len(tlines) * tlh + para_gap + len(slines) * blh

    if short:
        # r19：下横线与来源不再钉在固定比例位置，而是跟着摘要末尾往下走。
        # 可用高度算到「来源下方留固定内边距」为止，比旧版固定 line2_target 多出一截，
        # 全部让给字号：起始 47/43px，极端长文才逐步收，下限 40/36，绝不回到 32px。
        avail = max(160, max_line2 - int(CARD_SHORT_LINE_GAP * u) - ty)
        floor_fs = CARD_SHORT_FLOOR_L if land else CARD_SHORT_FLOOR_P
        while _need() > avail and body_fs > floor_fs:
            body_fs -= 1; bf = F(body_fs, root)
            blh = int(body_fs * CARD_SHORT_BLH)
            slines = fill_wrap(d, body_txt, bf, CW, sind)
        while _need() > avail and len(slines) > 2:
            slines = slines[:-1]; truncated = True
            if slines:
                ln, off = slines[-1]
                slines[-1] = (ln[:-1] + '…', off)
    else:
        while body_fs > min_fs:
            end = ty + _need()
            if end <= line2_target - int(60 * u):
                break
            body_fs -= 1; bf = F(body_fs, root)
            blh = int(body_fs * (1.48 if not land else 1.42))
            slines = fill_wrap(d, body_txt, bf, CW, sind)

    sy = ty + len(tlines) * tlh + para_gap
    left_t = int(len(ttl) * rv + 0.9999)
    for i, (ln, off) in enumerate(tlines):
        k = min(len(ln), max(0, left_t)); left_t -= k
        if k: txt(d, (M + off, ty + i * tlh), ln[:k], tf, title_col, True)
    title_end = ty + len(tlines) * tlh
    left_s = int(len(body_txt) * rv + 0.9999)
    for i, (ln, off) in enumerate(slines):
        k = min(len(ln), max(0, left_s)); left_s -= k
        if k: txt(d, (M + off, sy + i * blh), ln[:k], bf, sum_col)
    sum_end = sy + len(slines) * blh

    if short:
        # 内容驱动：横线贴着摘要末尾，来源随横线一起往下走，不再固定在比例位置
        line2 = min(sum_end + int(CARD_SHORT_LINE_GAP * u), max_line2)
    else:
        line2 = max(line2_target, sum_end + int(60 * u))
        line2 = min(line2, H - int(160 * u))
    d.line([M, line2, R, line2], fill=line_c, width=max(1, int(2 * u)))

    # ---- r23：字幕安全带只作布局占位（来源下移、meta 返回带范围），画面不再画框与标识文字

    # ---- 来源：只要渠道名，去掉链接与编号，紧跟线2
    chans = [re.sub(r'^[A-Za-z]?\d+\s*[·.、]\s*', '',
                   str(x.get('platform') or '').strip()).strip()
             for x in card.get('sources', [])]
    chans = [c for c in chans if c]
    src_s = '来源：' + ' · '.join(chans)
    src_fs = int((28 if land else CARD_SRC_FS) * fs_u)
    src_y = line2 + int((CARD_SRC_GAP_L if land else CARD_SRC_GAP_P) * u) + safe_u
    txt(d, (M, src_y), src_s, F(src_fs, root), meta_col, False, 'lm')
    src_end = src_y + int((34 if land else 40) * u)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    im.save(out_path)
    meta = {
        'type': 'card', 'index': card['index'], 'w': W, 'h': H, 'tpl': tpl,
        'brand': brand, 'date_line': date_s, 'issue_no': issue_s, 'reveal': rv,
        'v12_layout': True, 'header_fs': [brand_fs, date_fs, issue_fs],
        'line1_y': line1, 'line2_y': line2, 'indent': [indent, sind],
        'title_first_indent': tlines[0][1] if tlines else 0,
        'body_first_indent': slines[0][1] if slines else 0,
        'three_blocks_aligned': True, 'no_label_row': True,
        'para_gap': para_gap, 'src_channels_only': True, 'src_has_url': 'http' in src_s,
        'bg_image': str(card.get('bg_image') or ''), 'bg_applied': bg_applied,
        'bg_disabled': not CARD_BG_ENABLED,
        'category_art': cfg.get('category_art') or 'off',
        'category_kind': category_kind(card),
        'category_strength': cfg.get('category_strength', 'light'),
        'title_lines': len(tlines), 'summary_lines': len(slines),
        'sources': 1 if chans else 0, 'src_fs': src_fs,
        'summary_blocks': 1, 'lead_present': False, 'lead_bar': False,
        'lead_bold': False, 'lead_highlight': False, 'lead_no_bg': True,
        'no_paragraph_split': True, 'no_programmatic_indent': True,
        'body_excel_indent_kept': sind > 0,
        'sum_fs': body_fs, 'summary_color_mix': SUM_BASE_MIX,
        'summary_cool_mix': SUM_COOL_MIX, 'title_color_sep': True,
        'min_sum_fs': min_fs, 'summary_color_lift': True,
        'src_label': '来源：', 'src_red': False, 'src_band': False,
        'src_url_intact': True, 'src_atom_wrap': True,
        'src_lines_text': [src_s], 'src_top': src_y, 'src_bottom': src_end,
        'src_gap': src_y - line2, 'summary_bottom': sum_end,
        'src_anchored_bottom': False, 'src_follows_summary': bool(short),
        'content_driven_rule': bool(short), 'src_bottom_pad': H - src_end,
        'src_line_fs': [src_fs],
        'subtitle_reserved': safe_u > 0, 'subtitle_safe_u': safe_u,
        'subtitle_band': [line2 + int((24 if land else 32) * u),
                          line2 + int((24 if land else 32) * u) + safe_u] if safe_u > 0 else None,
        'title_color': list(title_col), 'date_color': list(meta_col),
        'tag_color': list(meta_col), 'title_fs': title_fs,
        'date_y': date_y, 'date_no_bg': True, 'header_aligned_cover': True,
        'kicker': True, 'issue_fs': issue_fs, 'hdr_fs': date_fs, 'no_fs': 0,
        'meta_lift': CARD_META_LIFT, 'box_bottom': H, 'content_top': ty,
        'head_bottom': line1, 'meta_y': 0, 'rule_y': line1,
        'title_theme_adaptive': True, 'content_group_top': True,
        'landscape_single_column': True, 'overflow': src_end > H,
        # 各文字块的真实 y 边界：短画幅叠字回归靠它判定，而不是只查是否出画布
        'boxes': {
            'brand':   [brand_y, brand_y + int(brand_fs * 1.15)],
            'date':    [date_y - int(date_fs * .6), date_y + int(date_fs * .6)],
            'kicker':  [dot_y - dot_r, dot_y + dot_r],
            'title':   [ty, title_end],
            'summary': [sy, sum_end],
            'line1':   [line1, line1], 'line2': [line2, line2],
            'src':     [src_y - int(src_fs * .6), src_end],
        },
        'size_scale': u, 'fs_scale': fs_u, 'short_layout': short,
        'summary_truncated': truncated, 'whitespace_below': line2 - sum_end,
    }
    if meta_path:
        os.makedirs(os.path.dirname(meta_path) or '.', exist_ok=True)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


# ================================================================== L1 语义编排封面
# 条目分隔五套方案：与页面 sepPaint 一一对应，cfg.sep 写进配置导出。
SEP_MODES = ('bands', 'cards', 'lines', 'bars', 'none', 'dashes', 'outline', 'accent', 'inset')


def _sep_mode(cfg):
    v = cfg.get('sep')
    if v in SEP_MODES:
        return v
    return 'bands' if cfg.get('alt_bands', True) else 'none'


def _sep_paint(d, co, mode, x0, y0, x1, y1, i, strong, u, cfg=None):
    """条目分隔九套方案 + 自由强度/强调色；与页面 sepPaint 一一对应。"""
    ink = (255, 255, 255) if co['dark'] else (0, 0, 0)
    cfg = cfg or {}
    st = max(.4, min(2.0, float(cfg.get('sep_strength', co.get('strength', 1.0)) or 1.0)))
    accent_on = bool(cfg.get('sep_accent', co.get('accent_on', False)))
    stripe = mix(co['bg'], ink, min(.30, .075 * st))
    line_c = co['acc'] if accent_on else mix(co['bg'], ink, min(.55, .28 * st))
    lw = max(1, int(2 * u * st))
    rad = max(0, int(10 * u * st))
    yb = y1 - max(2, int(2 * u))
    if mode == 'bands':
        if i % 2 == 1:
            d.rounded_rectangle([x0, y0, x1, y1], radius=rad, fill=stripe)
    elif mode == 'cards':
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad, fill=stripe)
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad, outline=line_c, width=lw)
    elif mode == 'lines':
        d.line([x0, yb, x1, yb], fill=line_c, width=lw)
    elif mode == 'bars':
        d.rectangle([x0, y0, x0 + 10 * u * st, y1], fill=co['acc'] if strong else line_c)
    elif mode == 'dashes':
        seg, gapx = max(6, int(14 * u * st)), max(4, int(9 * u))
        xx = x0
        while xx < x1:
            d.line([xx, yb, min(xx + seg, x1), yb], fill=line_c, width=lw)
            xx += seg + gapx
    elif mode == 'outline':
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad, outline=line_c, width=lw)
    elif mode == 'accent':
        d.rectangle([x0, y0, x0 + min((x1 - x0) * .18, 110 * u * st),
                     y0 + max(2, lw * 2)], fill=co['acc'])
    elif mode == 'inset':
        ix = int(24 * u * st)
        d.line([x0 + ix, y0 + 2 * u, x1 - ix, y0 + 2 * u], fill=line_c, width=1)
        d.line([x0 + ix, yb, x1 - ix, yb], fill=line_c, width=1)


def _sem_palette(theme):
    bg = rgb(theme['bg'])
    fg = rgb(theme['txt'])
    sub = rgb(theme['sub'])
    acc = rgb(theme['acc'])
    line = rgba_color(theme['line'], bg)
    if theme['dark']:
        card = mix(bg, (255, 255, 255), .062)
        chip = mix(bg, (255, 255, 255), .10)
    else:
        card = mix(bg, (0, 0, 0), .045)
        chip = mix(bg, (0, 0, 0), .075)
    # 报头标签实底：日期=深色块(白字，无竖条)，期号=朱红块(白字)。
    # 深主题用提亮 bg 做日期底，浅主题直接用主文字色做深底，白字对比均 >8:1。
    date_box = mix(bg, (255, 255, 255), .16) if theme['dark'] else fg
    badge_red = acc if theme['dark'] else mix(acc, (0, 0, 0), .12)
    return dict(bg=bg, fg=fg, sub=sub, acc=acc, line=line, card=card, chip=chip,
                date_box=date_box, badge_red=badge_red,
                date_ink=(255, 255, 255), badge_ink=(255, 255, 255),
                dark=theme['dark'])


def _date_badge(d, x0, yy, date_cn, f, co, u):
    """日期：纯文字、无底色，字号 DATE_FS；位置与封面一致（距标题块底部 HEAD_DATE_GAP*u）。"""
    s = str(date_cn).replace('，', ' · ')
    tw = d.textlength(s, font=f)
    txt(d, (x0, yy + HEAD_DATE_GAP * u), s, f, co['fg'], True, 'lm')
    return tw


def _issue_badge(d, x1, y_center, s, f, co, u):
    """期号胶囊：朱红实底 + 白字，无描边；y_center 为胶囊垂直中心。"""
    bw = d.textlength(s, font=f) + 56 * u
    bh = ISSUE_BH * u
    bx = x1 - bw
    by = y_center - bh / 2
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh / 2, fill=co['badge_red'])
    txt(d, (bx + bw / 2, by + bh / 2), s, f, co['badge_ink'], True, 'mm')
    return bx, by, bw, bh


def _spaced(d, x, y, text, font, fill, spacing=3):
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing
    return x


def _fit(d, text, maxw, maxh, base, minsize, root, maxlines=3, bold=False, factor=1.28):
    """自适应字号：不截断文字，只缩字号 / 换行，直到装进给定宽高。"""
    size = int(base)
    lines, font = [], None
    while size >= max(10, int(minsize)):
        font = F(size, root, bold)
        lines = wrap(d, text, font, maxw)
        if len(lines) <= maxlines and len(lines) * size * factor <= maxh:
            return font, lines, size
        size -= 1
    font = F(max(10, int(minsize)), root, bold)
    return font, wrap(d, text, font, maxw), max(10, int(minsize))


def _para(d, x, y, text, font, fill, lh):
    # 已按宽度断好的行由调用方给；这里只画一整段
    for i, ln in enumerate(text):
        txt(d, (x, y + i * lh), ln, font, fill, getattr(font, 'size', 0) >= 64)
    return y + len(text) * lh


def _box(d, co, x0, y0, x1, y1, r=20, side=False):
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=co['card'], outline=co['line'], width=1)
    if side:
        d.rounded_rectangle([x0, y0, x0 + 6, y1], radius=3, fill=co['acc'])


def _rule(d, co, x0, x1, y):
    d.line([x0, y, x1, y], fill=co['line'], width=1)


def _sec(d, co, x, y, name, meta, right, x2, root):
    d.rounded_rectangle([x, y + 3, x + 5, y + 33], radius=2, fill=co['acc'])
    f = F(34, root, True)
    txt(d, (x + 18, y), name, f, co['fg'], True)
    ox = x + 18 + d.textlength(name, font=f) + 14
    txt(d, (ox, y + 8), meta, F(21, root), co['sub'])
    if right:
        txt(d, (x2, y + 8), right, F(21, root), co['sub'], anchor='ra')


def _wrapped(d, text, font, maxw, maxlines):
    ls = wrap(d, text, font, maxw)
    return ls[:maxlines] if len(ls) > maxlines else ls


def _render_equal_cover(root, payload, cfg, out_path, meta_path, sem):
    set_cover_font(cfg)
    """等权列表：表格未填可选列时使用。N 条一视同仁、整组上下居中、字号固定不放大；
    条目靠交替淡底与横向细线区分，不显示统计条，不设独立头条卡。"""
    theme = THEMES.get(cfg.get('theme', 'deep_blue'), THEMES['deep_blue'])
    size = cfg.get('size', 'portrait')
    W, H = SIZES.get(size, SIZES['portrait'])
    u = H / (1080.0 if is_land(size) else 1920.0)
    co = _sem_palette(theme)
    head = cfg.get('cover_header') or payload.get('cover_header') or {}
    issue = cfg.get('issue') or payload.get('issue_cfg') or {}
    wm = cfg.get('wm') or {}
    n = sem['count']
    items = (payload.get('cover') or [])[:n]
    land = is_land(size)
    _cis = cover_item_style(cfg, theme, u, size)
    item_col, item_bold = _cis[2], _cis[3]
    pad = 58 * u
    footer_h = 52 * u
    im = Image.new('RGB', (W, H), co['bg'])
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, max(3, int(6 * u))], fill=co['acc'])

    show_t = head.get('show_title', True)
    show_d = head.get('show_date', True)
    show_i = head.get('show_issue', True)
    title = head.get('title', '今日要闻速览')
    yy = 54 * u
    d.rectangle([pad, yy + 12 * u, pad + 56 * u, yy + 17 * u], fill=co['acc'])
    _spaced(d, pad + 72 * u, yy, 'DAILY  BRIEF', F(24, root, True), co['acc'], 3 * u)
    if show_i:
        s = SRC.norm_issue(issue.get('issue_no') or payload.get('issue') or '第01期')
        _issue_badge(d, W - pad, yy + 28 * u, s, F(ISSUE_FS * u, root, True), co, u)
    yy += HEAD_TITLE_AT * u
    if show_t:
        big = 80
        f = F(big * u, root, True)
        while d.textlength(title, font=f) > (W - pad * 2) and big > 40:
            big -= 2
            f = F(big * u, root, True)
        txt(d, (pad, yy), title, f, co['fg'], True)
        yy += big * u * 1.16
    else:
        yy += 20 * u
    date_cn = issue.get('date_cn') or issue.get('date_line') or payload.get('date', '')
    if show_d:
        _date_badge(d, pad, yy, date_cn, F(DATE_FS * u, root, True), co, u)
    yy += HEAD_RULE_AT * u
    _rule(d, co, pad, W - pad, yy)
    head_bottom = yy + 24 * u

    avail = H - head_bottom - footer_h
    cols = 2 if land else 1
    rows = math.ceil(n / cols)
    col_gap = 36 * u
    colw = (W - pad * 2 - (cols - 1) * col_gap) / cols
    numw = 64 * u
    tx_off = 34 * u + numw + 20 * u
    innerw = colw - tx_off - 24 * u
    # 留白三档：只改「卡片内上下留白」与「卡片之间的真空隙」，字号固定不放大。
    # 剩余高度不摊进卡间距，全部留给整组上下居中。
    SPACING = {'compact': (8, 10), 'standard': (11, 14), 'airy': (16, 20)}
    pad_v, gap = SPACING.get(cfg.get('gap', 'airy'), SPACING['airy'])
    pad_v, gap = pad_v * u, gap * u
    min_pad_v, min_gap = 6 * u, 8 * u
    base_fs = _cis[1]  # r14 与三模板同源，可设
    min_fs = 30 * u

    def measure(sz):
        f = CF(sz, root)
        out = []
        for it in items:
            ls = wrap(d, it.get('title') or '', f, innerw)
            out.append((ls, max(64 * u, len(ls) * sz * 1.22)))
        return out

    fs = base_fs
    blocks = measure(fs)
    maxbh = max(b[1] for b in blocks)
    def total():
        return rows * (maxbh + 2 * pad_v) + (rows - 1) * gap
    # 放不下时优先缩字号保间距，再缩卡内留白，最后才缩间距且有硬下限。
    while fs > min_fs and total() > avail:
        fs -= 1
        blocks = measure(fs)
        maxbh = max(b[1] for b in blocks)
    while pad_v > min_pad_v and total() > avail:
        pad_v -= 1
    while gap > min_gap and total() > avail:
        gap -= 1
    card_h = maxbh + 2 * pad_v
    row_h = card_h + gap
    block_h = rows * card_h + (rows - 1) * gap
    # 整组仍上下居中，但每侧留白封顶 84u；多出的高度转成卡片内留白，
    # 不把条目间距拉大、也不让内容缩成中间一小条。
    MAX_SIDE = 84 * u
    if (avail - block_h) / 2 > MAX_SIDE:
        pad_v += (avail - block_h - 2 * MAX_SIDE) / (2 * rows)
        card_h = maxbh + 2 * pad_v
        row_h = card_h + gap
        block_h = rows * card_h + (rows - 1) * gap
    top = head_bottom + max(0, (avail - block_h) / 2)
    ink = (255, 255, 255) if co['dark'] else (0, 0, 0)
    stripe = mix(co['bg'], ink, .075)
    strong_line = mix(co['bg'], ink, .20)

    for i, it in enumerate(items):
        col, row = i // rows, i % rows
        x = pad + col * (colw + col_gap)
        y0 = top + row * row_h
        y1 = y0 + card_h
        _sep_paint(d, dict(co, line=strong_line), _sep_mode(cfg),
                   x, y0, x + colw, y1, i, i < 3, u, cfg)
        bx = x + 34 * u
        by = y0 + (card_h - numw) / 2
        strong = i < 3
        # 04 起改高对比实底：深主题浅底深字 / 浅主题深底白字，序号一眼可辨
        num_bg = co['acc'] if strong else ((219, 232, 248) if co['dark'] else co['fg'])
        num_ink = (255, 255, 255) if strong else ((16, 31, 51) if co['dark'] else (255, 255, 255))
        d.rounded_rectangle([bx, by, bx + numw, by + numw], radius=numw * .21, fill=num_bg)
        txt(d, (bx + numw / 2, by + numw / 2), '%02d' % (i + 1),
            F(34 * u, root, True), num_ink, True, 'mm')
        f = CF(fs, root)
        ty = y0 + (card_h - blocks[i][1]) / 2
        for k, ln in enumerate(blocks[i][0]):
            txt(d, (x + tx_off, ty + k * fs * 1.22), ln, f, item_col, item_bold)

    _all_n = len(payload.get('news') or [])
    _lim = int(payload.get('news_limit') or 0)
    _show_n = min(_lim, _all_n) if _lim > 0 else _all_n
    foot = '本期共有 %d 条资讯，仅展示 %d 条' % (_all_n, _show_n)
    txt(d, (pad, H - 42 * u), foot, F(22 * u, root, True), co['sub'])

    if wm.get('on'):
        a = float(wm.get('alpha', .12))
        s = str(wm.get('text', ''))
        wf = F(26 * u, root)
        wcol = mix(co['bg'], co['fg'], a)
        pos = wm.get('pos', 'bottom_right')
        if pos in ('bottom_right', 'bottom_left'):
            tw = d.textlength(s, font=wf)
            txt(d, (W - pad - tw if pos == 'bottom_right' else pad, H - 14 * u),
                s, wf, wcol, anchor='lm')
        elif pos == 'center':
            txt(d, (W / 2, H / 2), s, F(90 * u, root), wcol, anchor='mm')
        else:
            for wy in range(int(120 * u), H, int(220 * u)):
                for wx in range(int(40 * u), W, int(420 * u)):
                    txt(d, (wx, wy), s, wf, wcol)

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    im.save(out_path)
    boxes = [[pad + (i // rows) * (colw + col_gap), top + (i % rows) * row_h,
              pad + (i // rows) * (colw + col_gap) + colw,
              top + (i % rows) * row_h + card_h] for i in range(n)]
    meta = {'type': 'cover', 'tpl': 'semantic', 'semantic': True, 'mode': 'L1',
            'layout': 'equal', 'w': W, 'h': H, 'theme': cfg.get('theme'), 'size': size,
            'gap': cfg.get('gap'), 'count': n, 'items': n, 'boxes': boxes,
            'used': round(row_h, 2), 'cell_h': round(row_h, 2),
            'card_h': round(card_h, 2), 'card_gap': round(gap, 2),
            'card_pad': round(pad_v, 2), 'spacing': cfg.get('gap', 'airy'),
            'avail': round(avail, 2), 'head_bottom': round(head_bottom, 2),
            'watermark': bool(wm.get('on')), 'cols': cols, 'rows': rows,
            'centered': True, 'top_gap': round(top - head_bottom, 2),
            'bottom_gap': round(H - footer_h - (top + block_h), 2),
            'whitespace': round((avail - block_h) / 2, 2),
            'fixed_font': True, 'label_chip': False, 'divider': True,
            'sep': _sep_mode(cfg), 'font_fs': round(fs, 2), 'stats_hidden': True,
            'item_style': {'font': _cis[0], 'fs': round(fs, 2), 'color': list(item_col), 'bold': item_bold},
            'hero_value': '', 'topic_count': 0, 'rest_count': n,
            'boards': [], 'enabled': False}
    if meta_path:
        os.makedirs(os.path.dirname(meta_path) or '.', exist_ok=True)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def render_semantic_cover(root, payload, cfg, out_path, meta_path=None):
    """杂志版（精简编排）：语义元素只从表格可选列读，程序不猜不编。

    元素只保留：报头 / 头条(标签+数值+标题) / 专题(列表) / 其余要闻(列表) / 页脚。
    统计条、头条摘要、来源行、时间角标、专题「N 条合并」、逐条细线全部去掉。
    所有文字用「顺序行盒」逐行推进 y：每行高度 >= 实际文字 bbox，行间留固定空隙，
    并登记每个文字块的 bbox 做两两相交自检（overlap_count 写进 meta）。
    """
    import source as SRC
    theme = THEMES.get(cfg.get('theme', 'deep_blue'), THEMES['deep_blue'])
    size = cfg.get('size', 'portrait')
    W, H = SIZES.get(size, SIZES['portrait'])
    u = H / (1080.0 if is_land(size) else 1920.0)
    co = _sem_palette(theme)
    set_cover_font(cfg)
    _cis = cover_item_style(cfg, theme, u, size)
    item_col = _cis[2]
    n = cover_count(cfg, payload)
    sem = SRC.build_semantic(payload, n)
    if not sem['enabled']:
        return _render_equal_cover(root, payload, cfg, out_path, meta_path, sem)

    head = cfg.get('cover_header') or payload.get('cover_header') or {}
    issue = cfg.get('issue') or payload.get('issue_cfg') or {}
    wm = cfg.get('wm') or {}
    acc, fg, sub = co['acc'], co['fg'], co['sub']
    im = Image.new('RGB', (W, H), co['bg'])
    d = ImageDraw.Draw(im)
    tboxes = []          # [x0,y0,x1,y1,tag]，所有文字块
    boxes = []           # 区块盒子，仅用于 meta
    section_fs = []      # 各列表统一字号记录（回归用）
    pad = 58 * u
    land = is_land(size)
    footer_h = 62 * u
    gap_cfg = cfg.get('gap', 'airy')
    row_gap = {'compact': 8, 'standard': 14, 'airy': 22}.get(gap_cfg, 14) * u
    land_gap = {'compact': 4, 'standard': 6, 'airy': 10}.get(gap_cfg, 6) * u
    # 行高按最大档收敛：三档差全部留给条目间真实空隙，不被 rowh 反推吃掉
    rh_gap, lh_gap = 14 * u, 12 * u
    sep_mode = _sep_mode(cfg)
    d.rectangle([0, 0, W, max(3, int(6 * u))], fill=acc)
    show_t = head.get('show_title', True)
    show_d = head.get('show_date', True)
    show_i = head.get('show_issue', True)
    title = head.get('title', '今日要闻速览')

    def T(x, y, s, f, fill, tag, anchor=None, bold=False):
        """画一行文字并登记真实 bbox；列表文字用可设标题色。"""
        s = str(s)
        if fill == fg and tag.startswith(('topic', 'rest', 'land')):
            fill = item_col
        a = anchor or 'la'
        bb = d.textbbox((x, y), s, font=f, anchor=a)
        txt(d, (x, y), s, f, fill, bold, a)
        tboxes.append([round(bb[0], 1), round(bb[1], 1), round(bb[2], 1),
                       round(bb[3], 1), tag])
        return bb

    def num_chip(x, y, h, rk, strong, tag):
        """序号小色块 + 数字（与右侧文字 x 不重叠）。"""
        bw = min(58 * u, h * 1.25)
        bh = min(h * .82, 44 * u)
        rbg = acc if strong else ((219, 232, 248) if co['dark'] else fg)
        rink = (255, 255, 255) if strong else ((16, 31, 51) if co['dark'] else (255, 255, 255))
        d.rounded_rectangle([x, y + (h - bh) / 2, x + bw, y + (h + bh) / 2],
                            radius=int(6 * u), fill=rbg)
        T(x + bw / 2, y + h / 2, '%02d' % rk, F(int(25 * u), root, True),
          rink, tag + '_num', 'mm', True)
        return x + bw + 16 * u

    def uniform_lines(texts, maxw, fs0, minfs, max_lines, rowh):
        """整组共用一个字号：长标题换行到 <= max_lines，不逐条缩字号、不截断。
        行高上限由 rowh 反推，保证两行文字也不越出卡片。"""
        cap = int((rowh - 14 * u) / (max_lines * 1.22))
        fs = max(int(minfs), min(int(fs0), cap))
        f = CF(int(fs), root)
        rows = [wrap(d, t, f, maxw) for t in texts]
        while fs > int(minfs) and any(len(r) > max_lines for r in rows):
            fs -= 1
            f = CF(int(fs), root)
            rows = [wrap(d, t, f, maxw) for t in texts]
        return f, rows, int(fs)

    def overlaps():
        out = []
        for i, a in enumerate(tboxes):
            for b in tboxes[i + 1:]:
                ox = min(a[2], b[2]) - max(a[0], b[0])
                oy = min(a[3], b[3]) - max(a[1], b[1])
                if ox > 6 * u and oy > 6 * u:
                    out.append((a[4], b[4], round(ox, 1), round(oy, 1)))
        return out

    # ------------------------------------------------------------ 报头
    def header(x0, x1, y0, big):
        yy = y0
        d.rectangle([x0, yy + 12 * u, x0 + 56 * u, yy + 17 * u], fill=acc)
        _spaced(d, x0 + 72 * u, yy, 'DAILY  BRIEF', F(24 * u, root, True), acc, 3 * u)
        tboxes.append([round(x0 + 72 * u, 1), round(yy, 1),
                       round(x0 + 72 * u + 260 * u, 1), round(yy + 30 * u, 1), 'kicker'])
        if show_i:
            s = SRC.norm_issue(issue.get('issue_no') or payload.get('issue') or '第01期')
            bx, by, bw, bh = _issue_badge(d, x1, yy + 28 * u, s,
                                          F(ISSUE_FS * u, root, True), co, u)
            tboxes.append([round(bx, 1), round(by, 1), round(bx + bw, 1),
                           round(by + bh, 1), 'issue'])
        yy += HEAD_TITLE_AT * u
        if show_t:
            f = F(big * u, root, True)
            while d.textlength(title, font=f) > (x1 - x0) and big > 40:
                big -= 2
                f = F(big * u, root, True)
            bb = T(x0, yy, title, f, fg, 'title', bold=True)
            yy = bb[3] + 6 * u
        else:
            yy += 20 * u
        rule_base = yy
        date_cn = issue.get('date_cn') or issue.get('date_line') or payload.get('date', '')
        if show_d:
            bw = _date_badge(d, x0, rule_base, date_cn, F(DATE_FS * u, root, True), co, u)
            by0 = rule_base + HEAD_DATE_GAP * u - DATE_FS / 2 * u
            tboxes.append([round(x0, 1), round(by0, 1),
                           round(x0 + bw, 1), round(by0 + DATE_FS * u, 1), 'date'])
        yy = rule_base + HEAD_RULE_AT * u
        _rule(d, co, x0, x1, yy)
        return yy + 24 * u

    if not land:
        head_bottom = header(pad, W - pad, 62 * u, 88)
    else:
        head_bottom = 40 * u
    land_fs, land_rh = 0, 0   # 横版双栏列表的实际字号/行高，写入 meta 供回归读取

    # ------------------------------------------------------------ 行盒工具
    def draw_lines(lines, x0, y0, inner=None):
        """lines: [(h, fn(y))]；fn 内部画一行并登记文字块。返回结束 y。"""
        y = y0
        for h, fn in lines:
            fn(y)
            y += h + row_gap
        return y - row_gap

    def hero_lines(hero, x0, x1, big):
        """头条只保留：标签 / 数值行 / 标题（最多 2 行）。"""
        out = []
        out.append((36 * u, lambda y: T(x0, y, '今日头条', F(32 * u, root, True),
                                        acc, 'hero_label', bold=True)))
        if hero.get('value'):
            def value_row(y, hero=hero):
                fa = F(int(86 * u), root, True)
                fv = F(int(126 * u), root, True)
                aw = d.textlength(hero.get('arrow') or '', font=fa)
                xx = x0
                if hero.get('arrow'):
                    T(xx, y + 26 * u, hero['arrow'], fa, acc, 'hero_arrow', bold=True)
                    xx += aw + 14 * u
                bb = T(xx, y, hero['value'], fv, acc, 'hero_value', bold=True)
                if hero.get('unit'):
                    T(bb[2] + 14 * u, y + 82 * u, hero['unit'], F(30 * u, root),
                      acc, 'hero_unit')
            out.append((120 * u, value_row))
        f, ls, fs = _fit(d, hero['title'], x1 - x0, 110 * u, big * u, 26 * u,
                         root, 2, True)
        for ln in ls[:2]:
            out.append((fs * 1.24, (lambda ln=ln, f=f: lambda y: T(x0, y, ln, f, fg,
                                                                    'hero_title', bold=True))(ln, f)))
        return out

    def list_section(name, items, x0, x1, y0, fs0, minfs, tag, rowh=None):
        """专题/其余要闻：标题行 + 每行「序号块 + 统一字号文字」，隔行淡底。
        整组共用一个字号，长标题换行到最多 2 行，不逐条缩字号、不截断。"""
        lines = []
        lines.append((54 * u, lambda y: T(x0, y, name, F(34 * u, root, True),
                                          fg, tag + '_head', bold=True)))
        textx = x0 + 58 * u + 16 * u
        maxw = x1 - textx - 8 * u
        rh = rowh or max(74 * u, fs0 * 1.5)
        texts = [str(it.get('label') or it['title']) for it in items]
        f, rows, fs = uniform_lines(texts, maxw, fs0, minfs, 2, rh)
        lh = fs * 1.22
        section_fs.append({'tag': tag, 'fs': fs, 'rows': len(items),
                           'lines': [len(r) for r in rows]})
        for k, it in enumerate(items):
            ls = rows[k]
            ty = (rh - 6 * u - len(ls) * lh) / 2

            def row(y, f=f, ls=ls, k=k, it=it, rh=rh, tag=tag, ty=ty, lh=lh):
                boxes.append([x0, y, x1, y + rh - 6 * u])
                _sep_paint(d, co, sep_mode, x0 - 8 * u, y, x1, y + rh - 6 * u,
                           k, it['rank'] <= 3, u, cfg)
                nx = num_chip(x0, y, rh - 6 * u, it['rank'], it['rank'] <= 3,
                              tag + '_row' + str(k))
                for j, ln in enumerate(ls):
                    T(nx, y + ty + j * lh, ln, f, fg,
                      tag + '_text' + str(k) + '_' + str(j), bold=True)
            lines.append((rh, row))
        end = draw_lines(lines, x0, y0)
        return end, len(lines) - 1

    # ------------------------------------------------------------ 竖版
    if not land:
        cy = head_bottom + 12 * u
        hero = sem['hero']
        if hero:
            hx0, hx1 = pad + 30 * u, W - pad - 30 * u
            ls = hero_lines(hero, hx0, hx1, 42)
            inner = 18 * u
            card_h = inner * 2 + sum(h for h, _ in ls) + row_gap * (len(ls) - 1)
            _box(d, co, pad, cy, W - pad, cy + card_h, 20 * u)
            boxes.append([pad, cy, W - pad, cy + card_h])
            draw_lines(ls, hx0, cy + inner)
            cy += card_h + 16 * u

        all_items = []
        for t in sem['topics']:
            for it in t['items']:
                all_items.append({'rank': it['rank'],
                                  'label': ' · '.join(x for x in
                                                      ((it.get('org') or ''),
                                                       (it['title'] or it.get('brief') or '')) if x),
                                  'title': it['title']})
        rest = [{'rank': it['rank'], 'label': it['title'], 'title': it['title']}
                for it in sem['rest']]
        # 统一列表行高：专题与其余要闻共用同一 rowh，字号全封面一致。
        # 专题结束的 y 依赖 rowh，而 rowh 由剩余高度反推，迭代收敛。
        cy0 = cy
        rh = 112 * u
        if all_items or rest:
            for _ in range(4):
                cy_t = cy0 + (54 * u + len(all_items) * (rh + rh_gap) - rh_gap
                              + 34 * u) if all_items else cy0
                avail = H - footer_h - 20 * u - cy_t
                rh = max(58 * u, min(112 * u,
                        (avail - 54 * u - len(rest) * rh_gap) / max(1, len(rest))))
        if all_items:
            label = '专题 · ' + (sem['topics'][0]['name'] or sem['topics'][0]['id'])
            e, _ = list_section(label, all_items, pad + 26 * u, W - pad - 26 * u,
                                cy, _cis[1], 22 * u, 'topic', rowh=rh)
            cy = e + 16 * u
        if rest:
            e, _ = list_section('其余要闻 · %d 条' % len(rest), rest,
                                pad + 26 * u, W - pad - 26 * u, cy,
                                _cis[1], 22 * u, 'rest', rowh=rh)
            cy = e
            boxes.append([pad + 26 * u, cy - rh, W - pad - 26 * u, cy])

    # ------------------------------------------------------------ 横版：整条骨架重排
    # 弃用「左竖长头卡 + 右 7 行小字」：改为 报头横贯 → 头条横带 → 下半双栏列表。
    # 两栏共用同一行高与同一字号，资讯字号由 18~24 提到 30+。
    def land_band():
        nonlocal head_bottom
        x0, x1 = pad, W - pad
        hy0 = 56 * u
        d.rectangle([x0, hy0 + 12 * u, x0 + 56 * u, hy0 + 17 * u], fill=acc)
        _spaced(d, x0 + 72 * u, hy0, 'DAILY  BRIEF', F(24 * u, root, True), acc, 3 * u)
        tboxes.append([round(x0 + 72 * u, 1), round(hy0, 1),
                       round(x0 + 332 * u, 1), round(hy0 + 30 * u, 1), 'kicker'])
        ty = hy0 + 62 * u
        if show_t:
            fs_t = 64
            f = F(fs_t * u, root, True)
            while d.textlength(title, font=f) > (x1 - x0) * .64 and fs_t > 40:
                fs_t -= 2
                f = F(fs_t * u, root, True)
            T(x0, ty, title, f, fg, 'title', bold=True)
        # 日期牌 + 期号胶囊与标题同一行带、靠右
        badge_y = ty + 34 * u
        right = x1
        if show_i:
            s = SRC.norm_issue(issue.get('issue_no') or payload.get('issue') or '第01期')
            bx, by, bw, bh = _issue_badge(d, right, badge_y, s,
                                          F(ISSUE_FS * u, root, True), co, u)
            tboxes.append([round(bx, 1), round(by, 1), round(bx + bw, 1),
                           round(by + bh, 1), 'issue'])
            right = bx - 20 * u
        date_cn = issue.get('date_cn') or issue.get('date_line') or payload.get('date', '')
        if show_d:
            ds = str(date_cn).replace('，', ' · ')
            f = F(DATE_FS * u, root, True)
            bw = d.textlength(ds, font=f)
            bx = right - bw
            txt(d, (bx, badge_y), ds, f, co['fg'], True, 'lm')
            tboxes.append([round(bx, 1), round(badge_y - DATE_FS / 2 * u, 1),
                           round(bx + bw, 1), round(badge_y + DATE_FS / 2 * u, 1), 'date'])
        _rule(d, co, x0, x1, 226 * u)
        head_bottom = 246 * u

        # 头条横带：全宽卡片，左标签＋大数字，右标题，中间淡竖线
        hero = sem['hero']
        by0, by1 = 262 * u, 470 * u
        if hero:
            _box(d, co, x0, by0, x1, by1, 20 * u)
            boxes.append([x0, by0, x1, by1])
            ix0, ix1 = x0 + 30 * u, x1 - 30 * u
            split = ix0 + (ix1 - ix0) * .40
            T(ix0, by0 + 26 * u, '今日头条', F(32 * u, root, True), acc,
              'hero_label', bold=True)
            if hero.get('value'):
                fa, fv = F(64 * u, root, True), F(100 * u, root, True)
                xx = ix0
                if hero.get('arrow'):
                    bb = T(xx, by0 + 76 * u, hero['arrow'], fa, acc,
                           'hero_arrow', bold=True)
                    xx = bb[2] + 12 * u
                bb = T(xx, by0 + 62 * u, hero['value'], fv, acc,
                       'hero_value', bold=True)
                if hero.get('unit'):
                    T(bb[2] + 12 * u, by0 + 118 * u, hero['unit'],
                      F(28 * u, root), acc, 'hero_unit')
            d.line([split, by0 + 26 * u, split, by1 - 26 * u],
                   fill=co['line'], width=1)
            tx0 = split + 30 * u
            f, ls, fs = _fit(d, hero['title'], ix1 - tx0, 120 * u,
                             42 * u, 30 * u, root, 2, True)
            lh = fs * 1.24
            lines = ls[:2]
            ty0 = by0 + (by1 - by0 - len(lines) * lh) / 2
            for j, ln in enumerate(lines):
                T(tx0, ty0 + j * lh, ln, f, fg, 'hero_title', bold=True)

        # 下半双栏：专题 / 其余要闻，共用行高与字号
        ry0 = 496 * u
        avail = H - footer_h - 14 * u - ry0
        gapL = land_gap
        all_items = []
        for t in sem['topics']:
            for it in t['items']:
                all_items.append({'rank': it['rank'],
                                  'label': ' · '.join(x for x in
                                                      ((it.get('org') or ''),
                                                       (it['title'] or it.get('brief') or '')) if x),
                                  'title': it['title']})
        rest = [{'rank': it['rank'], 'label': it['title'], 'title': it['title']}
                for it in sem['rest']]
        lx0, lx1 = x0 + 8 * u, W * .49
        rx0, rx1 = W * .51, x1 - 8 * u
        maxrows = max(len(all_items), len(rest), 1)
        rh = max(78 * u, min(118 * u,
                 (avail - 54 * u - maxrows * lh_gap) / maxrows))
        cap = int((rh - 14 * u) / (2 * 1.22))
        fs = min(34 * u, cap)

        def all_fit(size):
            f = CF(int(size), root)
            for arr, a, b in ((all_items, lx0, lx1), (rest, rx0, rx1)):
                mw = b - (a + 58 * u + 16 * u) - 8 * u
                for it in arr:
                    if len(wrap(d, str(it['label']), f, mw)) > 2:
                        return False
            return True

        while fs > 26 * u and not all_fit(fs):
            fs -= 1
        fs = max(26 * u, fs)

        def land_list(name, arr, a, b, y, tag):
            T(a, y, name, F(34 * u, root, True), fg, tag + '_head', bold=True)
            textx = a + 58 * u + 16 * u
            maxw = b - textx - 8 * u
            f = CF(int(fs), root)
            yy = y + 54 * u
            for k, it in enumerate(arr):
                h = rh - 6 * u
                _sep_paint(d, co, sep_mode, a - 8 * u, yy, b, yy + h,
                           k, it['rank'] <= 3, u, cfg)
                nx = num_chip(a, yy, h, it['rank'], it['rank'] <= 3,
                              tag + '_row' + str(k))
                ls = wrap(d, str(it['label']), f, maxw)[:2]
                lh = fs * 1.22
                ty2 = yy + (h - len(ls) * lh) / 2
                for j, ln in enumerate(ls):
                    T(nx, ty2 + j * lh, ln, f, fg,
                      tag + '_text' + str(k) + '_' + str(j), bold=True)
                boxes.append([a, yy, b, yy + h])
                yy += rh + gapL
            section_fs.append({'tag': tag, 'fs': int(fs), 'rows': len(arr),
                               'lines': [1] * len(arr)})
            return yy - gapL

        if all_items:
            land_list('专题 · ' + (sem['topics'][0]['name'] or sem['topics'][0]['id']),
                      all_items, lx0, lx1, ry0, 'topic')
        if rest:
            land_list('其余要闻 · %d 条' % len(rest), rest, rx0, rx1, ry0, 'rest')
        return fs, rh

    if land:
        land_fs, land_rh = land_band()

    # ------------------------------------------------------------ 页脚
    _all_n = len(payload.get('news') or [])
    _lim = int(payload.get('news_limit') or 0)
    _show_n = min(_lim, _all_n) if _lim > 0 else _all_n
    foot = '本期共有 %d 条资讯，仅展示 %d 条' % (_all_n, _show_n)
    T(pad, H - 42 * u, foot, F(22 * u, root, True), sub, 'footer', bold=True)

    if wm.get('on'):
        a = float(wm.get('alpha', .12))
        s = str(wm.get('text', ''))
        wf = F(26 * u, root)
        wcol = mix(co['bg'], fg, a)
        pos = wm.get('pos', 'bottom_right')
        if pos in ('bottom_right', 'bottom_left'):
            tw = d.textlength(s, font=wf)
            T(W - pad - tw if pos == 'bottom_right' else pad, H - 14 * u,
              s, wf, wcol, 'watermark', 'lm')
        elif pos == 'center':
            T(W / 2, H / 2, s, F(90 * u, root), wcol, 'watermark', 'mm')
        else:
            for wy in range(int(120 * u), H, int(220 * u)):
                for wx in range(int(40 * u), W, int(420 * u)):
                    T(wx, wy, s, wf, wcol, 'watermark_tile' + str(wx) + '_' + str(wy))

    ov = overlaps()
    used = max([b[3] - b[1] for b in boxes] or [1])
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    im.save(out_path)
    meta = {'type': 'cover', 'tpl': 'semantic', 'semantic': True, 'mode': 'L1',
            'layout': 'magazine_band' if land else 'magazine',
            'w': W, 'h': H, 'theme': cfg.get('theme'), 'size': size,
            'gap': cfg.get('gap'), 'count': n, 'items': n, 'boxes': boxes[:n],
            'used': round(used, 2), 'cell_h': round(used, 2),
            'head_bottom': round(head_bottom, 2),
            'watermark': bool(wm.get('on')), 'cols': 2 if land else 1,
            'rows': len(boxes[:n]), 'centered': False, 'top_gap': 0, 'bottom_gap': 0,
            'whitespace': 0, 'fixed_font': True, 'label_chip': False, 'divider': False,
            'hero_value': (sem['hero'] or {}).get('value', ''),
            'topic_count': sem['topic_count'], 'rest_count': sem['rest_count'],
            'boards': sem['boards'], 'enabled': sem['enabled'],
            'stats_hidden': True, 'font_fs': int(land_fs) if land else 31,
            'land_fs': round(land_fs, 2), 'land_rh': round(land_rh, 2),
            'hero_h': round(sum(h for h, _ in hero_lines(sem['hero'], pad, W - pad, 42)) + 56 * u, 2)
            if sem['hero'] else 0,
            'text_boxes': len(tboxes), 'overlap_count': len(ov), 'overlaps': ov[:8],
            'list_sections': section_fs, 'uniform_font_per_group': True,
            'sep': sep_mode, 'row_gap': round(row_gap, 2), 'land_gap': round(land_gap, 2),
            'uniform_font': len({x['fs'] for x in section_fs}) <= 1 if section_fs else True,
            'out_of_canvas': len([b for b in tboxes
                                  if b[0] < -2 or b[1] < -2 or b[2] > W + 2 or b[3] > H + 2]),
            'compact_layout': True}
    if meta_path:
        os.makedirs(os.path.dirname(meta_path) or '.', exist_ok=True)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta

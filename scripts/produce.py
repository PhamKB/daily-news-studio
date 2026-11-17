# -*- coding: utf-8 -*-
"""合成层：按封面设置只出一版视频；字幕默认烧录 + 可选软轨 + 独立 SRT；
视频帧与字幕均可选打字机逐字显现；静帧编码参数针对体积优化。

所有 ffmpeg 调用检查返回码；失败即抛错，不静默报成功、不删旧片换空文件。
成品状态由 ffprobe 读真实流判定，不是「文件存在就算有轨」。
"""
import os, json, re, subprocess, math
from PIL import Image, ImageDraw, ImageOps
import render as R
import tts as T
import source as SRC


DISCLAIMER = '内容依据公开信息整理，具体以官方发布为准；仅供参考，不构成投资、医疗或法律建议。'


def _card_header(manifest):
    """卡片报头与封面同文案：中文长日期 + 期号；日期纯文字无底色。"""
    _is = manifest.get('issue') or {}
    _d, _w = str(_is.get('date') or ''), str(_is.get('weekday') or '')
    if len(_d) >= 10:
        _date_cn = '%s年%s月%s日 · %s' % (_d[:4], int(_d[5:7]), int(_d[8:10]), _w)
    else:
        _date_cn = _d
    return {'title': (manifest['config'].get('cover') or {}).get('title') or '今日要闻速览',
            'date': _date_cn, 'issue': _is.get('issue_no') or '第01期',
            'show_title': True, 'show_date': True, 'show_issue': True}



def run(cmd, tag):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError('%s 失败 rc=%d\nCMD: %s\nSTDERR: %s' % (
            tag, p.returncode, ' '.join(map(str, cmd))[:900], p.stderr[-1800:]))
    return p


def probe(path):
    p = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path], 'ffprobe ' + path)
    return json.loads(p.stdout)


def ff_dur(info):
    try:
        return float(info['format']['duration'])
    except (KeyError, ValueError, TypeError):
        return 0.0


def mean_db(path):
    """读真实平均电平；静音占位返回 -91，避免对无信号轨做归一化。"""
    p = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', path,
                        '-af', 'volumedetect', '-f', 'null', '-'],
                       capture_output=True, text=True)
    m = re.findall(r'mean_volume:\s*(-?[\d.]+) dB', p.stderr)
    return float(m[-1]) if m else -91.0


# ------------------------------------------------------------------ 音频
def build_audio(root, voice, manifest):
    cfg = manifest['config']
    media = os.path.join(root, 'media')
    os.makedirs(media, exist_ok=True)
    cache = os.path.join(root, '.cache'); os.makedirs(cache, exist_ok=True)
    vol = float(cfg['voice'].get('volume', 1.0))
    gain_db = float(cfg['voice'].get('master_gain_db', 0.0))
    files = [s['file'] for s in voice['segments']]
    parts, labels = [], []
    cmd = ['ffmpeg', '-y', '-loglevel', 'error']
    for f in files:
        cmd += ['-i', f]
    for i in range(len(files)):
        parts.append('[%d:a]volume=%.3f[a%d]' % (i, vol, i)); labels.append('[a%d]' % i)
    parts.append(''.join(labels) + 'concat=n=%d:v=0:a=1[raw]' % len(files))
    raw = os.path.join(cache, 'voice_raw.wav')
    cmd += ['-filter_complex', ';'.join(parts), '-map', '[raw]', '-ar', '24000', '-ac', '1',
            '-c:a', 'pcm_s16le', raw]
    run(cmd, '人声拼接')

    # TTS 输出电平普遍偏低；统一归一化到广播/播客 -16 LUFS，再叠加用户总增益，最后限幅。
    # 静音占位（dry-run）无信号，跳过 loudnorm，避免对空轨做无意义处理。
    vwav = os.path.join(cache, 'voice_track.wav')
    if mean_db(raw) > -70.0:
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', raw,
             '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11,volume=%.3fdB,alimiter=limit=0.95' % gain_db,
             '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', vwav], '人声响度归一化')
    else:
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', raw,
             '-af', 'volume=%.3fdB' % gain_db,
             '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', vwav], '人声增益')

    out = os.path.join(media, '今日播报.mp3')
    bgm_rel = cfg['bgm'].get('file')
    if bgm_rel:
        bgm = os.path.join(root, bgm_rel)
        if not os.path.isfile(bgm):
            raise RuntimeError('配置的 BGM 不存在：' + bgm)
        mx = cfg.get('mix') or {}
        b = float(cfg['bgm'].get('volume', .33))
        # 人声优先：播放期间按 duck_db 压低配乐；总音量由 master_gain_db 统一补偿
        if mx.get('duck', True):
            b *= 10 ** (float(mx.get('duck_db', -8)) / 20.0)
        fade_in = max(0.0, float(mx.get('fade_in', .4)))
        fade_out = max(0.0, float(mx.get('fade_out', .8)))
        af = '[1:a]volume=%.4f' % b
        if fade_in > 0:
            af += ',afade=t=in:st=0:d=%.2f' % fade_in
        if fade_out > 0:
            dur = float(voice.get('total') or 0)
            af += ',afade=t=out:st=%.2f:d=%.2f' % (max(0.0, dur - fade_out), fade_out)
        af += ',alimiter=limit=0.30[b];'
        # normalize=0：amix 默认会把每路各乘 0.5（约 -6dB），这是总音量偏小的主因。
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', vwav, '-stream_loop', '-1', '-i', bgm,
             '-filter_complex',
             af + '[0:a][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,'
             'alimiter=limit=0.95[m]',
             '-map', '[m]', '-c:a', 'libmp3lame', '-b:a', '96k', '-ac', '1', out], '混音 BGM')
    else:
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', vwav,
             '-c:a', 'libmp3lame', '-b:a', '96k', '-ac', '1', out], '编码 MP3')
    info = probe(out)
    return out, ff_dur(info), {'streams': [s['codec_type'] for s in info.get('streams', [])]}


# ------------------------------------------------------------------ 帧
def simple_frame(root, text, size, out, acc_hex='#e6432f', reveal=1.0, theme='deep_blue',
                 kind='window', header=None):
    """开场 / 窗口说明 / 片尾帧：与页面预览同源的顺序行盒。

    r14：去掉「本期 N 条 · 来源 N 个」和重复窗口行；免责声明只在帧上展示两行，
    不朗读、不进口播、不进字幕。所有文字登记 bbox，做两两相交自检。
    """
    W, H = R.SIZES[size]
    vert = W <= H
    u = min(W, H) / 1080.0
    th = R.THEMES.get(theme, R.THEMES['deep_blue'])
    base = R.rgb(th['bg']); fg = R.rgb(th['txt'])
    sub = R.rgb(th['sub']); line_c = R.rgba_color(th['line'], base)
    acc = R.rgb(acc_hex or th['acc'])
    im = Image.new('RGB', (W, H), base)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, max(2, int(6 * u))], fill=acc)
    pad = int(80 * u)
    hdr = header or {}
    issue = str(hdr.get('issue') or '')
    # 生产 manifest 的段类型是 opening / closing，帧内统一成 open / close，
    # 否则开场与片尾都会 fallback 成「资讯时间窗口」（r14 收尾发现的真 bug）。
    kind_norm = {'opening': 'open', 'closing': 'close', 'end': 'close',
                 'outro': 'close'}.get(str(kind), str(kind))
    labels = {'open': str(hdr.get('title') or '今日要闻速览'),
              'window': '资讯时间窗口', 'close': '感谢收听 · 下期见'}
    label = labels.get(kind_norm, '资讯时间窗口')
    boxes = []
    y = int(172 * u)
    R.txt(d, (pad, y), '今日要闻速览' + (' · ' + issue if issue else ''),
          R.F(int(44 * u), root), sub)
    boxes.append([pad, y - int(44 * u), pad + int(620 * u), y + int(8 * u), 'brand'])
    y = int(H * (0.30 if vert else 0.26))
    big = int((112 if vert else 88) * u)
    f = R.F(big, root, True)
    # r23：片尾标题按可用宽度自适应字号，保证「感谢收听 · 下期见」一行放下
    while big > int(52 * u) and d.textlength(label, font=f) > W - 2 * pad:
        big -= int(2 * u)
        f = R.F(big, root, True)
    lines = [label]
    lh = int(big * 1.30)
    for ln in lines:
        R.txt(d, (pad, y), ln, f, fg, True)
        boxes.append([pad, y - big, W - pad, y + int(8 * u), 'title'])
        y += lh
    y += int(36 * u)
    d.rectangle([pad, y, pad + int(220 * u), y + int(12 * u)], fill=acc)
    boxes.append([pad, y, pad + int(220 * u), y + int(12 * u), 'bar'])
    y += int(100 * u)
    date_s = str(hdr.get('date') or '')
    if date_s:
        R.txt(d, (pad, y), date_s, R.F(int(48 * u), root), sub)
        boxes.append([pad, y - int(48 * u), pad + int(720 * u), y + int(8 * u), 'date'])
        y += int(92 * u)
    # r33：片尾 / 窗口帧恢复单个「资讯窗口」信息框；片头仍是本期封面，
    # 不回退自建开场页；框高按免责线以上可用高度自适应，横版也不压免责。
    win_by = y + int(28 * u)
    win_bh = min(int(140 * u), max(int(96 * u),
                 int(H - 284 * u - win_by - 24 * u)))
    if kind_norm in ('window', 'close'):
        d.rounded_rectangle([pad, win_by, W - pad, win_by + win_bh],
                            radius=int(14 * u), outline=line_c,
                            width=max(1, int(2 * u)))
        R.txt(d, (pad + int(34 * u), win_by + int(26 * u)), '资讯窗口',
              R.F(int(30 * u), root, True), sub, True)
        R.txt(d, (pad + int(34 * u), win_by + int(70 * u)),
              '昨日 20:00 — 今日 20:00', R.F(int(40 * u), root, True), fg, True)
        boxes.append([pad + int(34 * u), win_by + int(18 * u),
                      W - pad - int(34 * u), win_by + int(112 * u), 'window_box'])
    d.line([pad, H - int(284 * u), W - pad, H - int(284 * u)], fill=line_c, width=1)
    d1 = '内容依据公开信息整理，具体以官方发布为准；'
    d2 = '仅供参考，不构成投资、医疗或法律建议。'
    R.txt(d, (pad, H - int(208 * u)), d1, R.F(int(40 * u), root), fg)
    R.txt(d, (pad, H - int(144 * u)), d2, R.F(int(38 * u), root), sub)
    boxes.append([pad, H - int(248 * u), W - pad, H - int(198 * u), 'disclaimer1'])
    boxes.append([pad, H - int(182 * u), W - pad, H - int(134 * u), 'disclaimer2'])
    overlap = 0
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            A, Bx = boxes[a], boxes[b]
            ox = min(A[2], Bx[2]) - max(A[0], Bx[0])
            oy = min(A[3], Bx[3]) - max(A[1], Bx[1])
            if ox > 6 * u and oy > 6 * u:
                overlap += 1
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    im.save(out)
    if kind_norm == 'close':
        cache = os.path.join(root, '.cache')
        os.makedirs(cache, exist_ok=True)
        with open(os.path.join(cache, 'outro_meta_%s.json' % size), 'w',
                  encoding='utf-8') as mf:
            json.dump({'kind': kind_norm, 'boxes': boxes, 'overlap': overlap,
                       'disclaimer': DISCLAIMER, 'item_count_shown': False,
                       'window_once': True, 'disclaimer_read': False}, mf, ensure_ascii=False, indent=2)
    return {'kind': kind_norm, 'overlap': overlap, 'boxes': boxes}


def opening_from_cover(root, size, out, manifest=None):
    """r25：片头 = 本期封面，绝不再回退到自建的「资讯窗口」信息页。

    上一版的 bug：源码包里 media/ 只有 .gitkeep，云端若封面渲染与出片时序错位，
    就会静默回退到 simple_frame 画的旧开场页。现在：
      ① 优先用本次重建刚落盘的 封面_<尺寸>.png，与封面成品逐字节一致；
      ② 没有就按当期 data.json + cover_theme.json 现场渲染一张，保证片头仍是封面；
      ③ 现场渲染也失败才返回 False（此时才允许回退帧）。
    """
    W, H = R.SIZES[size]
    ename = R.ENAME.get(size, '竖版9比16')
    im = None
    src = os.path.join(root, 'media', '封面_%s.png' % ename)
    if not os.path.isfile(src):
        import glob
        cand = sorted(glob.glob(os.path.join(root, 'media', '封面_*.png')))
        src = cand[0] if cand else ''
    if src:
        try:
            im = Image.open(src).convert('RGB')
        except Exception:
            im = None
    tmp = out + '.cover.png'
    if im is None:
        try:
            payload = SRC.load_json(os.path.join(root, 'data.json'))
            cv = dict(SRC.load_json(os.path.join(root, 'cover_theme.json')) or {})
            cv['size'] = size
            cv.setdefault('theme', 'deep_blue')
            cv.setdefault('tpl', 'semantic')
            cv.setdefault('gap', 'airy')
            cv.setdefault('wm', {'on': False})
            m = manifest or {}
            ci = dict(cv.get('issue') or {})
            mi = m.get('issue') or {}
            for k in ('date', 'weekday', 'issue_no'):
                if mi.get(k):
                    ci[k] = mi[k]
            if ci.get('date'):
                w = ci.get('weekday') or ''
                ci['date_cn'] = '%s年%s月%s日，%s' % (
                    ci['date'][:4], int(ci['date'][5:7]), int(ci['date'][8:10]), w)
                ci['date_line'] = ci['date'] + ' ' + w
            cv['issue'] = ci
            cv['cover_header'] = (m.get('cover_header') or payload.get('cover_header')
                                  or cv.get('cover_header'))
            R.render_cover(root, payload, cv, tmp)
            im = Image.open(tmp).convert('RGB')
        except Exception as e:
            print('片头现场渲染封面失败：%r' % (e,), flush=True)
            im = None
    if im is None:
        return False
    if im.size != (W, H):
        im = ImageOps.fit(im, (W, H), method=Image.LANCZOS)
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    im.save(out)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return True


def tw_targets(tw):
    on = bool(tw.get('on'))
    target = tw.get('target', 'subtitle')
    return (on and target in ('subtitle', 'both'), on and target in ('frame', 'both'))


def frames_for(root, manifest, voice, size, tw):
    """返回 [(png, dur), ...]，与句子/打字机子帧严格一致。"""
    outdir = os.path.join(root, '.cache', 'frames_' + size)
    os.makedirs(outdir, exist_ok=True)
    cards_dir = os.path.join(root, '.cache', 'cards_' + size)
    segs = manifest['segments']
    vs = voice['segments']
    if len(vs) == len(segs):
        durs = [s['dur'] for s in vs]
    else:
        total = voice['total']; weights = [max(1, len(s['text'])) for s in segs]
        durs = [total * w / sum(weights) for w in weights]
    _, tw_frame = tw_targets(tw)
    steps = max(2, min(int(tw.get('max_steps', 8)), 12))
    _hdr = _card_header(manifest)
    cfg = dict(manifest['config'].get('video_card') or {}, size=size, card_header=_hdr)
    theme = (manifest['config'].get('cover') or {}).get('theme', 'deep_blue')
    acc_hex = R.THEMES.get(theme, R.THEMES['deep_blue'])['acc']
    out = []
    seq = 0
    for i, s in enumerate(segs):
        du = durs[i]
        if not tw_frame:
            seq += 1
            p = os.path.join(outdir, 'f%03d.png' % seq)
            if s['kind'] == 'news' and s['card']:
                src = os.path.join(cards_dir, 'c%03d.png' % s['card'])
                if not os.path.isfile(src):
                    raise RuntimeError('缺少资讯卡片帧：' + src)
                Image.open(src).save(p)
            elif s['kind'] == 'opening' and opening_from_cover(root, size, p, manifest):
                pass
            else:
                simple_frame(root, s['text'], size, p, acc_hex, 1.0, theme,
                             s.get('kind', 'window'), _hdr)
            out.append((p, du))
            continue
        card = next((c for c in manifest['cards'] if c['index'] == s['card']), None) if s['card'] else None
        # r34：标题段先逐字出完，摘要段再按剩余时长出；r35 改用真实分段音轨 lead_dur。
        _full = str(s.get('text') or '')
        _sub = str(s.get('sub_text') or _full)
        _legacy_lead = max(0, len(_full) - len(_sub)) / max(1, len(_full))
        _vseg = vs[i] if i < len(vs) else {}
        _real_lead = float(_vseg.get('lead_dur') or 0)
        _lead = min(.92, max(.05, _real_lead / max(.01, du))) if _real_lead > 0 else _legacy_lead
        _td = max(.05, _lead)
        _bd = max(.05, 1 - _lead)
        # r37：8 帧均分时标题段几乎分不到帧（lead≈10% 时第 1 帧标题已全出）。
        # 标题段给 6 帧、摘要段给 8 帧，每帧时长按真实人声时间差分，总和仍严格等于 du。
        if card and tw_frame:
            n_t, n_s = 6, max(8, steps)
            pts = [_lead * k / n_t for k in range(1, n_t + 1)]
            pts += [_lead + (1 - _lead) * k / n_s for k in range(1, n_s + 1)]
        else:
            pts = [j / steps for j in range(1, steps + 1)]
        prev = 0.0
        for ratio in pts:
            seq += 1
            p = os.path.join(outdir, 'f%03d.png' % seq)
            _reveal = {'t': max(0.0, min(1.0, ratio / _td)),
                       's': max(0.0, min(1.0, (ratio - _lead) / _bd))}
            if card:
                R.render_card(root, card, cfg, p, reveal=_reveal)
            elif s['kind'] == 'opening' and opening_from_cover(root, size, p, manifest):
                pass
            else:
                simple_frame(root, s['text'], size, p, acc_hex, ratio, theme,
                             s.get('kind', 'window'), _hdr)
            out.append((p, max(0.01, (ratio - prev) * du)))
            prev = ratio
    return out


# ------------------------------------------------------------------ 字幕滤镜
def _ass_color(hexs, alpha='00'):
    h = str(hexs).lstrip('#')
    if len(h) != 6:
        h = 'FFFFFF'
    r, g, b = h[0:2], h[2:4], h[4:6]
    return '&H%s%s%s%s' % (alpha, b.upper(), g.upper(), r.upper())


def _escape_sub(path):
    """ffmpeg subtitles 滤镜路径转义（冒号/反斜杠/引号/逗号/方括号/分号）。"""
    p = os.path.abspath(path)
    for a, b in [('\\', '\\\\'), (':', '\\:'), ("'", "\\'"), (',', '\\,'),
                 ('[', '\\['), (']', '\\]'), (';', '\\;'), ('%', '\\%')]:
        p = p.replace(a, b)
    return p


def sub_style(sub, W, H):
    """r30：底色（样式 / 自定义颜色 / 透明度）与描边（颜色 / 宽度）独立生效。"""
    align = {'bottom': 2, 'center': 5, 'top': 8}.get(sub.get('position', 'bottom'), 2)
    fs = int(sub.get('font_size', 44))
    fs = max(16, int(fs * H / 1080.0))
    style = sub.get('background_style') or ('black' if sub.get('background', True) else 'none')
    border = 1 if style == 'none' else 3
    back = {'none': '&H00000000', 'black': '&H80000000',
            'navy': '&H8C2A1B0D', 'accent': '&H8C2F43E6'}.get(style, '&H80000000')
    if style == 'custom':
        a = max(0, min(255, int(round(255 * (1 - int(sub.get('bg_alpha', 84)) / 100.0)))))
        back = _ass_color(sub.get('bg_color', '#040b12'), '%02X' % a)
    lines = max(1, min(5, int(sub.get('max_lines', 2))))
    margin_v = int(H * (0.05 + 0.012 * max(0, lines - 1)))
    spacing = max(0, min(12, int(sub.get('letter_spacing', 0))))
    s = ("FontName=%s,FontSize=%d,PrimaryColour=%s,OutlineColour=&H00000000,"
         "BackColour=&H80000000,BorderStyle=%d,Outline=0,Shadow=0,Alignment=%d,"
         "MarginV=%d,Spacing=%d"
         % (sub.get('font', 'WenQuanYi Micro Hei'), fs,
            _ass_color(sub.get('color', '#FFFFFF')),
            border, align, margin_v, spacing))
    return s.replace('&H80000000', back)


# ------------------------------------------------------------------ 视频
def build_video(root, manifest, frames, audio_path, size, srt_path, adur=None, ass_path=None):
    W, H = R.SIZES[size]
    media = os.path.join(root, 'media'); os.makedirs(media, exist_ok=True)
    lst = os.path.join(root, '.cache', 'concat_' + size + '.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        for p, du in frames:
            f.write("file '%s'\nduration %.4f\n" % (p.replace("'", "'\\''"), du))
        f.write("file '%s'\n" % frames[-1][0].replace("'", "'\\''"))
    out = os.path.join(media, '今日要闻_%s.mp4' % ('竖版9比16' if size == 'portrait' else '横版16比9'))
    sub = manifest['config']['subtitle']
    burn = bool(sub.get('on')) and bool(sub.get('burn_in')) and bool(srt_path)
    soft = bool(sub.get('on')) and bool(sub.get('soft_track')) and bool(srt_path)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-i', audio_path]
    if soft:
        cmd += ['-i', srt_path]
    vf = ['scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=8'
          % (W, H, W, H)]
    if burn:
        if ass_path and os.path.isfile(ass_path):
            # ASS 自带逐字卡拉OK样式，不用 force_style 覆盖
            vf.append('subtitles=%s' % _escape_sub(ass_path))
        else:
            vf.append('subtitles=%s:force_style=\'%s\'' % (_escape_sub(srt_path), sub_style(sub, W, H)))
    cmd += ['-map', '0:v:0', '-map', '1:a:0']
    if soft:
        cmd += ['-map', '2:s:0']
    cmd += ['-vf', ','.join(vf),
            '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage',
            '-crf', '30', '-pix_fmt', 'yuv420p',
            '-x264-params', 'keyint=240:min-keyint=240:scenecut=0',
            '-c:a', 'aac', '-b:a', '64k', '-ac', '1']
    if soft:
        cmd += ['-c:s', 'mov_text', '-metadata:s:s:0', 'language=chi']
    cmd += ['-shortest']
    if adur and adur > 0:
        cmd += ['-t', '%.3f' % adur]
    cmd += ['-movflags', '+faststart', out]
    run(cmd, '出片 ' + size)
    info = probe(out)
    kinds = [s.get('codec_type') for s in info.get('streams', [])]
    return out, {'duration': ff_dur(info), 'streams': kinds,
                 'video': 'video' in kinds, 'audio': 'audio' in kinds,
                 'soft_subtitle': 'subtitle' in kinds,
                 'burned_subtitle': burn, 'size': [W, H],
                 'bytes': os.path.getsize(out)}


def produce(root, manifest, voice, card_cfg):
    """主编排：音频 → SRT/ASS → 单版视频 → 真实状态文件。"""
    audio, adur, ainfo = build_audio(root, voice, manifest)
    vsegs = voice['segments']
    if vsegs and len(vsegs) == len(manifest['segments']):
        s = sum(x['dur'] for x in vsegs)
        if s > 0 and abs(s - adur) > 0.01:
            k = adur / s
            for x in vsegs:
                x['dur'] = x['dur'] * k
                if x.get('lead_dur'):
                    x['lead_dur'] = x['lead_dur'] * k
            voice['total'] = adur

    sub = manifest['config']['subtitle']
    tw = manifest['config'].get('typewriter') or {}
    size = manifest.get('export_size', 'portrait')
    srt = os.path.join(root, 'media', '今日要闻.srt')
    srt_path = T.build_srt(root, voice, manifest, srt) if sub.get('on') else None
    tw_sub, tw_frame = tw_targets(tw)
    ass_path = None
    if srt_path and sub.get('burn_in') and tw_sub:
        ass_path = os.path.join(root, 'media', '今日要闻.ass')
        T.build_ass(root, voice, manifest, ass_path, R.SIZES[size][0], R.SIZES[size][1])

    cdir = os.path.join(root, '.cache', 'cards_' + size)
    os.makedirs(cdir, exist_ok=True)
    _hdr = _card_header(manifest)
    cc = dict(card_cfg, size=size, card_header=_hdr)
    card_overflow = []
    for c in manifest['cards']:
        cmeta = R.render_card(root, c, cc, os.path.join(cdir, 'c%03d.png' % c['index']))
        if cmeta.get('overflow'):
            card_overflow.append(c['index'])

    status = {'ok': False, 'real_voice': voice.get('real_voice'), 'voice_mode': voice.get('mode'),
              'audio': {'path': 'media/今日播报.mp3', 'duration': adur, 'streams': ainfo['streams'],
                        'mean_db': round(mean_db(audio), 2)},
              'subtitle_on': bool(sub.get('on')), 'subtitle_burned': bool(sub.get('burn_in')) and bool(srt_path),
              'subtitle_count': len(vsegs) if srt_path else 0,
              'subtitle_chunk_count': (sum(len(T.subtitle_chunks(x['text'])) for x in vsegs)
                                       if srt_path else 0),
              'typewriter': bool(tw.get('on')), 'typewriter_target': tw.get('target', 'subtitle'),
              'subtitle_typewriter': bool(ass_path),
              'export_size': size,
              'card_count': len(manifest['cards']), 'segment_count': len(manifest['segments']),
              'card_overflow': card_overflow,
              'versions': {}, 'errors': []}
    frames = frames_for(root, manifest, voice, size, tw)
    path, info = build_video(root, manifest, frames, audio, size, srt_path, adur, ass_path)
    status['versions'][size] = dict(info, path=os.path.relpath(path, root))
    if not (info['video'] and info['audio']):
        status['errors'].append('%s 缺视频轨或音轨' % size)
    if sub.get('soft_track') and srt_path and not info['soft_subtitle']:
        status['errors'].append('%s 缺软字幕轨' % size)
    if card_overflow:
        status['errors'].append('卡片来源溢出画面：%s' % card_overflow)
    if abs(info['duration'] - adur) > 1.5:
        status['errors'].append('%s 时长与音频不一致 %.2f vs %.2f' % (size, info['duration'], adur))
    status['frame_count'] = len(frames)
    status['ok'] = not status['errors']
    with open(os.path.join(root, 'VIDEO_STATUS.json'), 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    tl = {'source': '逐句音频 ffprobe 真实时长（已按拼接后 PCM 总长归一）',
          'total': round(adur, 3), 'unit': 's',
          'lead_durs': [round(float(x.get('lead_dur') or 0), 3) for x in vsegs],
          'segments': [{'i': i + 1, 'dur': round(x['dur'], 3), 'text': x['text'],
                        'lead_dur': round(float(x.get('lead_dur') or 0), 3)}
                       for i, x in enumerate(vsegs)]}
    with open(os.path.join(root, 'media', 'timeline.json'), 'w', encoding='utf-8') as f:
        json.dump(tl, f, ensure_ascii=False, indent=2)
    status['timeline_file'] = 'media/timeline.json'
    with open(os.path.join(root, 'VIDEO_STATUS.json'), 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    if not status['ok']:
        raise RuntimeError('成品硬校验未过：' + '; '.join(status['errors']))
    return status

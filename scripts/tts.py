# -*- coding: utf-8 -*-
"""人声层：在线 LibreTTS（微软神经音色）/ edge-tts 直连 / 自定义上传真人录音 / dry-run 占位。

失败策略 stop_and_report：在线接口失败就抛错，不静默塞静音、不沿用上期音轨。
dry-run 只用于本地冒烟链路，会在状态文件里如实标注，绝不冒充真人声。

在线接口按 POST JSON → GET t/v/r/p → GET text/voice 三种契约顺序兼容，
错误响应体写进异常，便于定位。
"""
import os, json, re, time, math, subprocess, urllib.request, urllib.parse, urllib.error, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed


class VoiceError(RuntimeError):
    pass


CPS = 4.6  # 中文播报估算字/秒，仅用于 dry-run 与预览时间轴


def estimate(text):
    return max(1.6, len(str(text)) / CPS)


def _wav_silence(path, dur):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'anullsrc=r=24000:cl=mono', '-t', '%.3f' % dur,
                    '-c:a', 'pcm_s16le', path], check=True)
    return dur


def _probe_dur(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'default=nw=1:nk=1', path], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def _audio_ok(data, ctype):
    """挡住把错误页 / JSON / HTML 当音频写盘。"""
    if not data or len(data) < 512:
        return False
    h = data[:16]
    if h.startswith(b'ID3') or h[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2', b'\xff\xf1'):
        return True
    if h.startswith((b'RIFF', b'OggS', b'fLaC')):
        return True
    if h[:1] in (b'{', b'<') or h.startswith(b'<!'):
        return False
    return bool(ctype and ('audio/' in ctype or 'octet-stream' in ctype))


def _normalize(raw, out_path, tag):
    """服务端可能给 mp3/wav/ogg/opus，统一转 24k 单声道 mp3 再交给拼接与时间轴。"""
    tmp = out_path + '.raw'
    with open(tmp, 'wb') as f:
        f.write(raw)
    p = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', tmp,
                        '-ar', '24000', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '96k', out_path],
                       capture_output=True, text=True)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if p.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 512:
        raise VoiceError('%s 返回内容不是可解码音频：%s' % (tag, p.stderr[-300:]))
    return out_path


def _one_request(endpoint, method, params, text, voice, rate, timeout):
    """返回 (data, content_type)；HTTP 错误抛出带响应体的 VoiceError。"""
    headers = {'User-Agent': 'daily-news-studio/1.2', 'Accept': 'audio/mpeg,audio/*;q=0.9,*/*;q=0.5'}
    if method == 'POST':
        body = json.dumps(params, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(endpoint, data=body, method='POST',
                                     headers=dict(headers, **{'Content-Type': 'application/json; charset=utf-8'}))
    else:
        q = urllib.parse.urlencode(params)
        url = endpoint + ('&' if '?' in endpoint else '?') + q
        req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read()[:500].decode('utf-8', 'replace').strip()
        except Exception:
            pass
        raise VoiceError('HTTP %d %s%s' % (e.code, e.reason, '：' + body if body else ''))
    except Exception as e:
        raise VoiceError('%r' % (e,))


def libretts_fetch(endpoint, text, voice, rate, out_path, timeout=20, retries=2):
    """同一个服务按三种契约依次尝试；4xx 读响应体，不再只显示 'Bad Request'。

    顺序：POST JSON（LibreSpark 标准）→ GET t/v/r/p（Ciallo / xysele 旧契约）
          → GET text/voice/rate（Piper 风格自建实例）。
    POST 优先也避免长句 GET 触发 URL 长度限制。
    """
    r = int(rate or 0)
    attempts = [
        ('POST-json', 'POST', {'text': text, 'voice': voice, 'rate': r, 'pitch': 0, 'format': 'mp3'}),
        ('GET-t/v/r/p', 'GET', {'t': text, 'v': voice, 'r': r, 'p': 0}),
        ('GET-text/voice', 'GET', {'text': text, 'voice': voice, 'rate': r, 'format': 'mp3'}),
    ]
    errs = []
    for rnd in range(max(1, int(retries or 1))):
        for label, method, params in attempts:
            try:
                data, ctype = _one_request(endpoint, method, params, text, voice, r, timeout)
            except VoiceError as e:
                errs.append('%s %s' % (label, e))
                continue
            if not _audio_ok(data, ctype):
                errs.append('%s 非音频响应（%s / %dB / %r）' %
                            (label, ctype, len(data), data[:120]))
                continue
            _normalize(data, out_path, label)
            return label
        if rnd + 1 < max(1, int(retries or 1)):
            time.sleep(0.6)
    raise VoiceError('LibreTTS 调用失败（%d 轮 × %d 契约）；逐次原因：%s；停止出片，不静音占位、不沿用上期'
                     % (max(1, int(retries or 1)), len(attempts), ' | '.join(errs[-6:])))


def _edge_fetch(text, voice, rate, out_path):
    """可选通道：edge-tts 本地直连微软神经音色，不依赖第三方公共实例。"""
    try:
        import asyncio, edge_tts
    except ImportError:
        raise VoiceError('edge 模式需要 edge-tts：pip install edge-tts')
    r = int(rate or 0)

    async def go():
        c = edge_tts.Communicate(text, voice, rate='%+d%%' % r)
        await c.save(out_path)

    try:
        asyncio.run(go())
    except Exception as e:
        raise VoiceError('edge-tts 合成失败：%r；停止出片，不静音占位、不沿用上期' % (e,))
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 512:
        raise VoiceError('edge-tts 输出为空或过小')
    return out_path


def _cache_path(outdir, text, voice, rate):
    key = hashlib.md5((str(voice) + '|' + str(rate) + '|' + text).encode('utf-8')).hexdigest()[:20]
    return os.path.join(outdir, 'cache_' + key + '.mp3'), key


def _concat2(a, b, out):
    """把标题段与摘要段音频拼成同一句，返回输出路径。"""
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a, '-i', b,
                    '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[out]',
                    '-map', '[out]', '-ar', '24000', '-ac', '1',
                    '-c:a', 'libmp3lame', '-b:a', '96k', out], check=True)
    if not os.path.isfile(out) or os.path.getsize(out) < 512:
        raise VoiceError('分段音频拼接失败：' + out)
    return out


def _concat3(a, b, c, out):
    """r38：标题段 + 静音补齐 + 摘要段，三段同采样率/声道后拼接。"""
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a, '-i', b, '-i', c,
                    '-filter_complex',
                    '[0:a]aresample=24000,aformat=channel_layouts=mono[a0];'
                    '[1:a]aresample=24000,aformat=channel_layouts=mono[a1];'
                    '[2:a]aresample=24000,aformat=channel_layouts=mono[a2];'
                    '[a0][a1][a2]concat=n=3:v=0:a=1[out]',
                    '-map', '[out]', '-ar', '24000', '-ac', '1',
                    '-c:a', 'libmp3lame', '-b:a', '96k', out], check=True)
    if not os.path.isfile(out) or os.path.getsize(out) < 512:
        raise VoiceError('三段音频拼接失败：' + out)
    return out


def _split_spoken(seg):
    """返回 (标题段, 摘要段)；无法可靠拆分时回退整句合成。"""
    full = str(seg.get('text') or '')
    sub = str(seg.get('sub_text') or '')
    if sub and full.endswith(sub):
        lead = full[:-len(sub)].strip()
        body = sub.strip()
    elif '。' in full:
        q = full.find('。')
        lead, body = full[:q + 1].strip(), full[q + 1:].strip()
    else:
        return None
    if not lead or not body:
        return None
    return lead, body


def _synth_parallel(root, manifest, cfg, segs, outdir, fetcher, tag):
    """并发合成；frame 模式下标题段/摘要段分别实测时长，再拼成同一句音频。"""
    workers = min(16, max(1, int(cfg.get('concurrency', 16))))
    results = [None] * len(segs)
    tw = ((manifest.get('config') or {}).get('typewriter') or {})
    frame_mode = bool(tw.get('on', True)) and tw.get('target', 'frame') in ('frame', 'both')
    jobs = []
    for k, seg in enumerate(segs):
        p, key = _cache_path(outdir, seg['text'], cfg.get('voice', ''), cfg.get('rate', 0))
        jobs.append((k, seg, p, os.path.isfile(p) and os.path.getsize(p) > 512))

    def work(job):
        k, seg, p, hit = job
        parts = _split_spoken(seg) if frame_mode and seg.get('kind') == 'news' else None
        cached = hit
        lead_dur = 0.0
        if parts:
            lead_text, body_text = parts
            lp, _ = _cache_path(outdir, 'LEAD::' + lead_text, cfg.get('voice', ''), cfg.get('rate', 0))
            bp, _ = _cache_path(outdir, 'BODY::' + body_text, cfg.get('voice', ''), cfg.get('rate', 0))
            lhit = os.path.isfile(lp) and os.path.getsize(lp) > 512
            bhit = os.path.isfile(bp) and os.path.getsize(bp) > 512
            if not lhit:
                fetcher(lead_text, lp)
            if not bhit:
                fetcher(body_text, bp)
            if not (os.path.isfile(lp) and os.path.getsize(lp) > 512 and
                    os.path.isfile(bp) and os.path.getsize(bp) > 512):
                raise VoiceError('%s 第 %d 句分段输出为空' % (tag, k + 1))
            ld = _probe_dur(lp)
            bd = _probe_dur(bp)
            # r38：标题段/摘要段每字同速 —— 目标标题时长 = 摘要时长 × 标题字数 / 摘要字数。
            # 标题音频偏短时补静音，让 lead_dur 归一，人声摘要起点与文字摘要起点对齐。
            tn = len(lead_text)
            bn = max(1, len(body_text))
            target = bd * tn / bn
            pad = max(0.0, target - ld)
            if pad > .02:
                sil = os.path.join(outdir, 'sil_%s_%.3f.wav' % (key, pad))
                _wav_silence(sil, pad)
                _concat3(lp, sil, bp, p)
            else:
                _concat2(lp, bp, p)
            lead_dur = max(ld, target)
            cached = lhit and bhit
        elif not hit:
            fetcher(seg['text'], p)
        if not os.path.isfile(p) or os.path.getsize(p) < 512:
            raise VoiceError('%s 第 %d 句输出为空' % (tag, k + 1))
        return k, {'file': p, 'dur': _probe_dur(p), 'text': seg['text'],
                   'sub_text': seg.get('sub_text') or seg['text'],
                   'lead_text': parts[0] if parts else None,
                   'lead_dur': lead_dur, 'cached': cached}

    errors = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, j): j for j in jobs}
        for fut in as_completed(futs):
            try:
                k, item = fut.result()
                results[k] = item
            except Exception as e:
                errors.append('%r' % (e,))
    if errors:
        raise VoiceError('%s 并发合成失败（%d/%d）：%s；停止出片，不静音占位' %
                         (tag, len(errors), len(jobs), ' | '.join(errors[:4])))
    cached = sum(1 for x in results if x['cached'])
    print('人声：%s %d 句 / %d 路并发 / 缓存复用 %d 句 / 分段实测 %d 句' %
          (tag, len(results), workers, cached, sum(1 for x in results if x.get('lead_dur'))), flush=True)
    return results

def build_voice(root, manifest, mode=None):
    cfg = manifest['config']['voice']
    mode = mode or cfg.get('mode') or ('upload' if cfg.get('upload') else 'libretts')
    outdir = os.path.join(root, '.cache', 'voice')
    os.makedirs(outdir, exist_ok=True)
    segs = manifest['segments']
    result = []

    if mode == 'upload':
        up = cfg.get('upload')
        if not up or not os.path.isfile(os.path.join(root, up)):
            raise VoiceError('自定义上传人声不存在：%r' % up)
        src = os.path.join(root, up)
        dur = _probe_dur(src)
        result = [{'file': src, 'dur': dur, 'text': '（整段上传真人录音）',
                   'sub_text': '（整段上传真人录音）'}]
        return {'mode': 'upload', 'real_voice': True, 'total': dur, 'segments': result}

    if mode == 'dry-run':
        for s in segs:
            p = os.path.join(outdir, 's%03d.wav' % s['i'])
            # 冒烟用：每句压到 <=3s，避免把 30 条长稿编成十几分钟视频；真实模式不受影响
            dur = min(3.0, max(1.2, estimate(s['text'])))
            _wav_silence(p, dur)
            full = str(s.get('text') or '')
            sub = str(s.get('sub_text') or full)
            lead = max(0, len(full) - len(sub))
            lead_dur = float(s.get('lead_dur') or 0) or dur * lead / max(1, len(full))
            lead_dur = min(max(0.0, lead_dur), dur * .92) if s.get('kind') == 'news' else 0.0
            result.append({'file': p, 'dur': dur, 'text': s['text'],
                           'sub_text': sub, 'lead_text': s.get('lead_text'),
                           'lead_dur': lead_dur})
        return {'mode': 'dry-run', 'real_voice': False, 'total': sum(x['dur'] for x in result),
                'segments': result,
                'note': '本地静音占位且每句压到<=3s，仅验混音/字幕/封装链路；不是真人声，也不是成品时长'}

    if mode not in ('libretts', 'edge'):
        raise VoiceError('未知人声模式：' + str(mode))

    if mode == 'edge':
        def ef(text, p):
            _edge_fetch(text, cfg.get('voice', 'zh-CN-YunyangNeural'), cfg.get('rate', 0), p)
        result = _synth_parallel(root, manifest, cfg, segs, outdir, ef, 'edge-tts')
        return {'mode': 'edge', 'real_voice': True, 'total': sum(x['dur'] for x in result),
                'segments': result, 'voice': cfg.get('voice'),
                'note': 'edge-tts 直连微软神经音色，6 路并发 + 本地缓存'}

    endpoint = cfg.get('endpoint')
    if not endpoint:
        raise VoiceError('未配置 LibreTTS endpoint')
    contracts = []

    def lf(text, p):
        label = libretts_fetch(endpoint, text, cfg.get('voice', 'zh-CN-YunyangNeural'),
                               cfg.get('rate', 0), p,
                               timeout=int(cfg.get('timeout_s', 20)), retries=int(cfg.get('retries', 2)))
        contracts.append(label)

    result = _synth_parallel(root, manifest, cfg, segs, outdir, lf, 'LibreTTS')
    return {'mode': 'libretts', 'real_voice': True, 'total': sum(x['dur'] for x in result),
            'segments': result, 'endpoint': endpoint, 'voice': cfg.get('voice'),
            'api_contract': contracts[0] if contracts else None,
            'note': '6 路并发 + 本地缓存，不再 33 次串行等待'}


SUB_CHUNK_MAX = 30
_ACTIVE_LINES = 2   # r29：由 build_srt / build_ass 按 subtitle.max_lines（1–5）设置，ASS 不再夹到 3


def subtitle_chunks(text):
    """把一句长口播切成短字幕片段：优先在句末标点切；片段长度随显示行数变化。
    r28：1–5 行分别按 15/30/45/60/75 字分片，与页面 subChunks() 同源。"""
    s = re.sub(r'[\r\n]+', '', str(text or ''))
    ml = max(1, min(5, int(_ACTIVE_LINES)))
    # r28：1 行不再整句横向滚动；1–5 行按 15×行数 字分片，行数真生效
    cap = int(round(SUB_CHUNK_MAX * ml / 2))
    out, cur = [], ''
    # r31：句末标点只在片段接近满长时才切。旧版每个句号都切，
    # 3 行模式常切出十来字，再被均分成 3 行就成了「每行几个字居中」。
    for ch in s:
        cur += ch
        if len(cur) >= cap or (ch in '。！？；' and len(cur) >= cap * 0.75):
            out.append(cur)
            cur = ''
        elif ch in '，、' and len(cur) >= cap * 0.85:
            out.append(cur)
            cur = ''
    if cur:
        out.append(cur)
    return out or [' ']


SUB_LINE_UNITS = 15


def _sub_units(s):
    """显示宽度：中文/全角标点 1，ASCII 字母数字 .55，其余 .5。"""
    u = 0.0
    for ch in str(s):
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:
            u += 1.0
        elif ch.isascii() and (ch.isalnum() or ch in '._%-'):
            u += 0.55
        else:
            u += 0.5
    return u


def chunk_lines(text, ml, want=0):
    """r31：每行按 15 个全角单位填满、左对齐；不再按字数均分（旧版 per=ceil(len/ml)
    会把 20 字切成 3 行每行 6 字，居中后左右空一大块）。
    r31b：want = 同句所有片段共用的行数；短片段按更窄目标宽度补足到同样行数，
    选 N 行时全程 N 行，不再 2 行/3 行来回跳。
    数字 / 小数 / 英文串 / 单位整块不拆，标点不落行首。"""
    s = re.sub(r'[\r\n]+', '', str(text or ''))
    ml = max(1, min(5, int(ml)))
    if ml == 1 or len(s) < 4:
        return s
    toks = re.findall(
        r'\d+(?:\.\d+)?(?:%|元|点|时|分|秒|年|月|日|个|条|万|亿|升|米|公里|吨)?'
        r'|[A-Za-z][A-Za-z0-9._-]*|[\u4e00-\u9fa5]|[^\s]', s)
    lim = float(SUB_LINE_UNITS)

    def wrap_at(width):
        out, row = [], ''
        for tk in toks:
            if row and _sub_units(row + tk) > width and len(out) < ml - 1:
                out.append(row); row = tk
            else:
                row += tk
        if row:
            out.append(row)
        if len(out) > ml:
            out = out[:ml - 1] + [''.join(out[ml - 1:])]
        for i in range(1, len(out)):
            if out[i] and out[i][0] in '，。！？；：、,.!?;:' and out[i - 1]:
                out[i - 1] += out[i][0]
                out[i] = out[i][1:]
        return [r for r in out if r][:ml]

    rows = wrap_at(lim)
    target = max(1, min(ml, int(want or 0)))
    if target > 1 and len(rows) != target:
        lo, hi, best = 1.0, lim, rows
        for _ in range(24):
            mid = (lo + hi) / 2.0
            r = wrap_at(mid)
            if len(r) == target:
                best = r; break
            if len(r) > target:
                lo = mid
            else:
                hi = mid; best = r
        rows = best
        guard = 0
        while len(rows) < target and guard < 12:
            guard += 1
            bi = max(range(len(rows)), key=lambda i: _sub_units(rows[i]))
            r = rows[bi]
            if len(r) < 2:
                break
            cut = max(1, len(r) // 2)
            rows[bi:bi + 1] = [r[:cut], r[cut:]]
        rows = rows[:ml]
    return '\n'.join(rows)


def build_srt(root, voice, manifest, path):
    global _ACTIVE_LINES
    sub = manifest['config']['subtitle']
    if not sub.get('on'):
        return None
    _ACTIVE_LINES = max(1, min(5, int(sub.get('max_lines', 2))))

    def fmt(x):
        ms = int(round(x * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        sec, ms = divmod(ms, 1000)
        return '%02d:%02d:%02d,%03d' % (h, m, sec, ms)

    t, lines, idx = 0.0, [], 0
    for i, s in enumerate(voice['segments'], 1):
        st, en = t, t + s['dur']
        try:
            _k = str(manifest['segments'][i - 1].get('type') or '')
        except Exception:
            _k = ''
        if _k in ('open', 'close', 'opening', 'closing', 'window'):
            t = en
            continue
        if voice['mode'] != 'upload':
            full = s['text']
            text = s.get('sub_text') or s['text']
        else:
            m = manifest['segments'][i - 1]
            full = m['text']
            text = m.get('sub_text') or m['text']
        # r27：字幕不含标题，但人声念完整句（标题。摘要）。按标题字数占比
        # 扣掉这段朗读时长，字幕从人声念完标题那一刻才开始，逐字才同步。
        lead = max(0, len(str(full)) - len(str(text)))
        lead_dur = s['dur'] * lead / max(1, len(str(full)))
        _real_lead = float(s.get('lead_dur') or 0) if voice['mode'] != 'upload' else 0.0
        if _real_lead > 0:
            lead_dur = min(max(.01, _real_lead), s['dur'] * .92)
        st_sub = st + lead_dur
        dur_sub = max(0.2, s['dur'] - lead_dur)
        chunks = subtitle_chunks(text)
        # r31b：按可用宽度填满、行数 N 为上限；不按字数均分，与页面 canvas / ASS 一致
        tot = sum(len(c) for c in chunks) or 1
        ct = st_sub
        for chunk in chunks:
            cd = dur_sub * len(chunk) / tot
            idx += 1
            lines.append('%d\n%s --> %s\n%s\n' % (idx, fmt(ct), fmt(ct + cd),
                                                  chunk_lines(chunk, _ACTIVE_LINES)))
            ct += cd
        t = en
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path

def build_ass(root, voice, manifest, path, W, H):
    """逐字显现硬字幕：ASS 卡拉OK（\k 按字分配厘秒），未显现的字用全透明 SecondaryColour。

    一句一条 Dialogue，总时长严格等于该句音频时长；软轨与独立 SRT 仍为整句可读文本。
    """
    global _ACTIVE_LINES
    sub = manifest['config']['subtitle']
    _ACTIVE_LINES = max(1, min(5, int(sub.get('max_lines', 2))))
    tw = manifest['config'].get('typewriter') or {}

    def color(hexs, alpha='00'):
        h = str(hexs).lstrip('#')
        if len(h) != 6:
            h = 'FFFFFF'
        return '&H%s%s%s%s' % (alpha, h[4:6].upper(), h[2:4].upper(), h[0:2].upper())

    def ts(x):
        cs = int(round(max(0.0, x) * 100))
        h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
        return '%d:%02d:%02d.%02d' % (h, m, s, cs)

    def esc(c):
        return c.replace('\\', '／').replace('{', '(').replace('}', ')').replace('\n', ' ')

    fs = max(16, int(int(sub.get('font_size', 44)) * H / 1080.0))
    # r31b：与画面帧一致左对齐（1/4/7 是左列），不再让短行居中、两侧空一大块
    align = {'bottom': 1, 'center': 4, 'top': 7}.get(sub.get('position', 'bottom'), 1)
    border = 3 if sub.get('background', True) else 1
    margin_v = int(H * 0.05)
    margin_l = int(W * 0.045)
    primary = color(sub.get('color', '#FFFFFF'), '00')
    # &HFF...... = alpha FF = 完全透明，未「打」到的字不可见
    secondary = '&HFF000000'
    outline = '&H00000000'
    spacing = max(0, min(12, int(sub.get('letter_spacing', 0))))
    font = sub.get('font', 'WenQuanYi Micro Hei')

    lines = [
        '[Script Info]', 'ScriptType: v4.00+', 'WrapStyle: 2',
        'ScaledBorderAndShadow: yes', 'PlayResX: %d' % W, 'PlayResY: %d' % H, '',
        '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, '
        'BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, '
        'BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        'Style: Default,%s,%d,%s,%s,%s,&H80000000,0,0,0,0,100,100,%d,0,%d,0,0,%d,%d,10,%d,1'
        % (font, fs, primary, secondary, outline, spacing, border, align, margin_l, margin_v), '',
        '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ]
    t = 0.0
    for i, s in enumerate(voice['segments'], 0):
        st, en = t, t + s['dur']
        t = en
        try:
            _k = str(manifest['segments'][i].get('type') or '')
        except Exception:
            _k = ''
        if _k in ('open', 'close', 'opening', 'closing', 'window'):
            continue
        if voice['mode'] != 'upload':
            full = s['text']
            text = s.get('sub_text') or s['text']
        else:
            m = manifest['segments'][i]
            full = m['text']
            text = m.get('sub_text') or m['text']
        lead = max(0, len(str(full)) - len(str(text)))
        lead_dur = s['dur'] * lead / max(1, len(str(full)))
        _real_lead = float(s.get('lead_dur') or 0) if voice['mode'] != 'upload' else 0.0
        if _real_lead > 0:
            lead_dur = min(max(.01, _real_lead), s['dur'] * .92)
        st_sub = st + lead_dur
        dur_sub = max(0.2, s['dur'] - lead_dur)
        chunks = subtitle_chunks(text)
        # r31b：按可用宽度填满、行数 N 为上限；不按字数均分，与页面 canvas / SRT 一致
        tot = sum(len(c) for c in chunks) or 1
        ct = st_sub
        for chunk in chunks:
            dur = dur_sub * len(chunk) / tot
            ce = ct + dur
            rows = [r for r in chunk_lines(chunk, _ACTIVE_LINES).split('\n')]
            flat = [c for r in rows for c in r] or [' ']
            total_cs = max(1, int(round(dur * 100)))
            # 每字均分厘秒，余数摊到前几个字，保证总和严格等于本片段时长
            alloc = [total_cs // len(flat)] * len(flat)
            for k in range(total_cs - sum(alloc)):
                alloc[k % len(flat)] += 1
            # r31：ASS 硬换行与页面 / SRT 同用 chunk_lines 的语义单元折行，
            # 不再按字数均分（旧写法会切开「3600点」，也是 3 行时好时坏的根因）
            it = iter(alloc)
            body = ''
            for ri, row in enumerate(rows):
                if ri:
                    body += '{\\N}'
                for c in row:
                    body += '{\\k%d}%s' % (next(it), esc(c))
            lines.append('Dialogue: 0,%s,%s,Default,,0,0,0,,%s' % (ts(ct), ts(ce), body))
            ct = ce
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path

# -*- coding: utf-8 -*-
"""发布前硬校验：只读产物，不调用生成器；任一失败即 rc=1，让 Actions 直接红灯。"""
import os, re, json, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKS = []


def ck(name, ok, detail=''):
    CHECKS.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})
    if not ok:
        print('FAIL', name, detail)


def load(p):
    with open(os.path.join(ROOT, p), encoding='utf-8') as f:
        return json.load(f)


def main():
    yml = open(os.path.join(ROOT, '.github', 'workflows', 'daily.yml'), encoding='utf-8').read()
    ck('workflow 无 schedule', 'schedule:' not in yml)
    ck('workflow 无 cron 字面量', not re.search(r"cron\\s*:", yml))
    ck('保留 workflow_dispatch', 'workflow_dispatch:' in yml)
    html = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    for bad in ['id="schedMode"', 'id="ymFixed"', 'id="cronFixed"', '固定 cron', '定时重建安排']:
        ck('页面无定时残留 ' + bad, bad not in html)

    bs = load('BUILD_STATUS.json')
    ck('BUILD_STATUS ok', bs.get('ok'), bs.get('errors'))
    ck('分段计时齐全', all(k in bs.get('timings', {}) for k in
                          ['fetch_s', 'build_s', 'render_cover_s', 'tts_s', 'mux_s']), bs.get('timings'))
    ck('构建版本标记', bs.get('version') == '1.0', bs.get('version'))

    data = load('data.json')
    ct = load('cover_theme.json')
    cc = int(ct.get('count', 8))
    ck('封面条数可设置且合法', 1 <= cc <= 10, cc)
    js = open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    m = re.search(r'window\.__LIVE_DATA__=(\{.*\});', js, re.S)
    ck('data.js 可解析', bool(m))
    if m:
        live = json.loads(m.group(1))
        ck('data.js 与 data.json 标题逐字一致',
           [x['title'] for x in live.get('news', [])] == [x['title'] for x in data.get('news', [])])
        ck('data.js 封面基础数据 10 条', len(live.get('cover', [])) == 10)
        ck('data.js 显示条数同源', int(live.get('cover_count', cc)) == cc, live.get('cover_count'))
    ck('data.json 含 rebuilt_at', 'rebuilt_at' in data, data.get('rebuilt_at'))
    ck('页面初版标记', '初版 · 每日要闻工作台' in html)
    ck('页面无迭代话术', not any(x in html for x in
                            ['原文未' + '改', 'v' + '12.', 'v' + '13-', '沿用' + ' v',
                             '产品' + '版' + ' v', '修复' + '说明']))
    ck('片尾无「部分为预测或时点数据」', '部分为预测' not in html and '部分为预测' not in data.get('close', ''))
    _iss = data.get('issue_cfg', {})
    ck('开场按当天且封面日期同源',
       bool(_iss.get('date_cn')) and _iss['date_cn'] in data.get('open', '')
       and _iss.get('date') in data.get('date', ''), (_iss.get('date_cn'), data.get('open', '')[:60]))
    ck('口播文稿开场与数据同源', _iss.get('date_cn', 'X') in
       open(os.path.join(ROOT, '口播文稿.md'), encoding='utf-8').read()[:400])
    ck('data_source issue 同源', load('data_source.json').get('issue', {}).get('date') == _iss.get('date'))

    # ---- 封面/水印/页面初始日期与开场同源 ----
    _cti = ct.get('issue') or {}
    ck('cover_theme 日期与开场同源',
       _cti.get('date') == _iss.get('date') and _cti.get('date_cn') == _iss.get('date_cn')
       and _cti.get('date_line') == _iss.get('date_line'), (_cti.get('date'), _iss.get('date')))
    ck('水印文本日期与开场同源', _iss.get('date', 'X') in str((ct.get('wm') or {}).get('text', '')),
       (ct.get('wm') or {}).get('text'))
    ck('页面初始 meta 由本期日期运行时覆盖',
       "textContent=S.issue.date_line" in html and 'id="hdMeta"' in html, '')
    _dsct = load('data_source.json').get('cover_theme') or {}
    ck('data_source 内嵌封面日期与开场同源',
       (_dsct.get('issue') or {}).get('date') == _iss.get('date')
       and _iss.get('date', 'X') in str((_dsct.get('wm') or {}).get('text', '')),
       ((_dsct.get('issue') or {}).get('date'), (_dsct.get('wm') or {}).get('text')))
    _mfct = ((load('render_manifest.json').get('config') or {}).get('cover') or {})
    ck('manifest 封面日期与开场同源',
       (_mfct.get('issue') or {}).get('date') == _iss.get('date'),
       (_mfct.get('issue') or {}).get('date'))

    # ---- 期号：全链路阿拉伯数字，且中文旧值会被规范化 ----
    import source as SRC
    ck('norm_issue 中文数字/无补零/纯数字 → 第NN期',
       SRC.norm_issue('第\u4e00期') == '第01期' and SRC.norm_issue('第3期') == '第03期'
       and SRC.norm_issue('12') == '第12期' and SRC.norm_issue('第11期') == '第11期'
       and SRC.norm_issue('第十\u4e00期') == '第11期'
       and SRC.norm_issue('创刊号') == '创刊号',
       (SRC.norm_issue('第\u4e00期'), SRC.norm_issue('第3期'), SRC.norm_issue('第十\u4e00期')))
    ck('source 默认期号为第01期',
       SRC.auto_issue()['issue_no'] == '第01期', SRC.auto_issue()['issue_no'])
    _issno = str(_iss.get('issue_no') or '')
    ck('本期期号为阿拉伯数字格式', bool(re.fullmatch(r'第\d{2}期', _issno)), _issno)
    ck('data.json / data.js 顶层期号同源且为阿拉伯数字',
       data.get('issue') == _issno and bool(re.search(r'"issue":\s*"第\d{2}期"', js)),
       (data.get('issue'), _issno))
    ck('各数据契约期号同源',
       all(str((o.get('issue') or {}).get('issue_no') or o.get('issue_no') or '') == _issno
           for o in [ct, load('data_source.json'), load('data_source.json').get('cover_theme') or {}]),
       (ct.get('issue', {}).get('issue_no'), (load('data_source.json').get('issue') or {}).get('issue_no')))
    ck('manifest 期号与本期同源',
       str((load('render_manifest.json').get('issue') or {}).get('issue_no') or '') == _issno,
       ((load('render_manifest.json').get('issue') or {}).get('issue_no')))
    _bad_vals = []
    for _f in ['index.html', 'data.js', 'data.json', 'data_source.json', 'render_manifest.json',
               'cover_theme.json']:
        _t = open(os.path.join(ROOT, _f), encoding='utf-8').read()
        if any(x in _t for x in ['"issue": "第一期"', '"issue_no": "第一期"',
                                 'value="第一期"', '>第一期<']):
            _bad_vals.append(_f)
    ck('配置默认值无中文期号残留', not _bad_vals, _bad_vals)
    ck('Python 默认值字符串无中文期号',
       "'第一期'" not in open(os.path.join(ROOT, 'scripts', 'source.py'), encoding='utf-8').read()
       and "'第一期'" not in open(os.path.join(ROOT, 'scripts', 'render.py'), encoding='utf-8').read())
    ck('页面状态迁移会升级旧期号',
       'S.issue.issue_no=normIssue' in html and 'const STATE_VER=' in html and 'if(o.__ver!==STATE_VER)' in html
       and "function normIssue(" in html)
    ck('页面期号输入失焦会规范化', "$('issueNo').onchange" in html and 'normIssue($' in html)
    # ---- 报头日期间距：前后端同值且已拉开 ----
    ck('页面报头日期已拉开且字号放大', 'HEAD_DATE_GAP=82' in html and 'DATE_FS=38' in html
       and 'yy+HEAD_DATE_GAP*u' in html and 'HEAD_RULE_AT=126' in html)
    _rend = open(os.path.join(ROOT, 'scripts', 'render.py'), encoding='utf-8').read()
    ck('服务端报头日期与页面同值',
       'HEAD_DATE_GAP = 82' in _rend and 'HEAD_RULE_AT = 126' in _rend
       and 'DATE_FS = 38' in _rend and 'ISSUE_FS = 38' in _rend
       and _rend.count('HEAD_DATE_GAP * u') >= 1 and _rend.count('HEAD_RULE_AT * u') >= 2
       and 'def _date_badge(' in _rend and 'def _issue_badge(' in _rend)
    ck('服务端无旧的贴标题日期', "yy + 8 * u" not in _rend)
    # 日期牌 / 期号胶囊：实底白字，前后端同一套配色，不再用浅字淡底
    ck('服务端日期纯文字无底色、期号胶囊仍实底白字',
       'date_box=date_box' in _rend and 'badge_red=badge_red' in _rend
       and "co['badge_red']" in _rend and "co['badge_ink']" in _rend
       and "co['fg'], True, 'lm')" in _rend
       and "fill=co['date_box']" not in _rend
       and "txt(d, (bx + 26 * u, by + bh / 2), ds, f, co['date_ink']" not in _rend)
    ck('日期牌朱红竖杠已去掉（前后端）',
       'bar_x' not in _rend and 'x0+10*u,by+9*u' not in html
       and 'pad+10*u,by+9*u' not in html and 'co.acc;rr(ctx,x0+10*u' not in html)
    ck('日期牌与期号字号统一放大', 'DATE_BH = 62' in _rend and 'ISSUE_BH = 68' in _rend
       and 'DATE_BH=62' in html and 'ISSUE_BH=68' in html)
    ck('页面日期纯文字无底色、期号胶囊同封面',
       'badgeRed:T.dark?T.acc' in html and 'co.badgeRed' in html
       and "ctx.fillStyle=co.dateBox" not in html
       and "ctx.fillStyle=dBox;rr(ctx,pad,by,bw,bh" not in html
       and "ctx.fillText(dt,pad,y+HEAD_DATE_GAP*u)" in html
       and "co.dateInk" not in html)

    mf = load('render_manifest.json')
    ck('manifest 显示条数同源', mf.get('cover_count') == cc
       and mf['config']['cover'].get('count') == cc, (mf.get('cover_count'), cc))
    ck('data_source 显示条数同源', load('data_source.json').get('cover_count') == cc
       and load('data_source.json').get('cover_theme', {}).get('count') == cc)
    ck('封面清单条数 = 设置条数',
       len(re.findall(r'^\d+\. ', open(os.path.join(ROOT, '封面清单.md'), encoding='utf-8').read(), re.M)) == cc)
    nseg = len(mf['segments'])
    ck('句子/卡片数量一致', nseg == len(mf['cards']) + 2 +
       (1 if any(s['kind'] == 'window' for s in mf['segments']) else 0),
       '%d 句 / %d 卡' % (nseg, len(mf['cards'])))
    ck('封面 N 条 = 正文前 N 条标题',
       [c['title'] for c in data['cover'][:cc]] == [n['title'] for n in data['news'][:cc]], cc)
    ck('所有资讯卡带来源 URL',
       all(s.get('url') for c in mf['cards'] for s in c['sources'] if s.get('platform')))
    sub = mf['config']['subtitle']
    ck('字幕默认烧录（Chrome 可见）', sub.get('burn_in') is True)
    ck('字幕保留软轨', sub.get('soft_track') is True)
    ck('字幕开关存在', 'on' in sub)
    ck('打字机契约存在', 'on' in mf['config']['typewriter'])
    ck('打字机默认开启', mf['config']['typewriter'].get('on') is True)
    ck('打字机作用位置合法', mf['config']['typewriter'].get('target') in ('subtitle', 'frame', 'both'))
    ck('导出尺寸合法（五平台）', mf.get('export_size') in
       ('portrait', 'landscape', 'xhs', 'wechat', 'square'))
    ck('manifest 五平台尺寸', len(mf.get('sizes', {})) == 5)
    ck('无定时契约', mf['config'].get('trigger', {}).get('mode') == 'workflow_dispatch')
    ds = load('data_source.json')
    ck('资讯窗口声明', ds.get('news_window', {}).get('start') == '昨日 20:00'
       and ds.get('news_window', {}).get('end') == '今日 20:00', ds.get('news_window'))
    ck('data_source 无 fixed_cron', 'fixed_cron' not in ds and 'schedule_default' not in ds)

    ck('页面 30 独立编辑框容器', 'id="bodyEditors"' in html and 'renderBodyEditors' in html)
    ck('页面全屏按钮', 'id="btnFull"' in html and 'requestFullscreen' in html)
    ck('页面字幕设置齐备', all(('id="%s"' % x) in html for x in
                          ['subOn', 'subBurn', 'subSoft', 'subSize', 'subPos', 'subTypewriter']))
    ck('页面单一视频导出按钮', 'id="btnExpVideo"' in html and 'id="btnExpV"' not in html
       and 'id="btnExpH"' not in html)
    ck('播放器 rAF 连续推进', 'requestAnimationFrame(tick)' in html and 'function startPlay' in html)
    ck('TTS 并发 16 路且可调', 'VOICE_CONCURRENCY=16' in html and 'id="vcConc"' in html
       and "min(16, max(1, int(cfg.get('concurrency', 16))))" in open(os.path.join(ROOT, 'scripts', 'tts.py'), encoding='utf-8').read())
    ck('流程条 8 项定位', 'function goSec(' in html and html.count("['sec-") >= 8)

    vs = load('VIDEO_STATUS.json')
    ck('VIDEO_STATUS ok', vs.get('ok'), vs.get('errors'))
    ck('只出一版视频', len(vs.get('versions', {})) == 1, list(vs.get('versions', {})))
    ck('导出尺寸与 manifest 一致', vs.get('export_size') == mf.get('export_size'))
    ck('字幕已烧录', vs.get('subtitle_burned') is True)
    for k, v in vs.get('versions', {}).items():
        ck(k + ' 视频轨+音轨', v.get('video') and v.get('audio'), v.get('streams'))
        ck(k + ' 尺寸', v.get('size') in ([1080, 1920], [1920, 1080],
             [1080, 1440], [1080, 1260], [1080, 1080]), v.get('size'))
        ck(k + ' 体积字段', isinstance(v.get('bytes'), int) and v['bytes'] > 1024, v.get('bytes'))
    ck('字幕条数=句子数', vs.get('subtitle_count') == nseg if vs.get('subtitle_on') else True,
       vs.get('subtitle_count'))
    ck('卡片数=资讯条数', vs.get('card_count') == len(mf['cards']))
    ck('成品时长与音频一致',
       abs(next(iter(vs['versions'].values()))['duration'] - vs['audio']['duration']) <= 1.5
       if vs.get('versions') else False)

    esz = mf.get('export_size')
    ename = {'portrait': '竖版9比16', 'landscape': '横版16比9',
             'xhs': '小红书3比4', 'wechat': '视频号6比7', 'square': '方形1比1'}.get(esz, '竖版9比16')
    esz0 = mf.get('export_size')
    meta_path = os.path.join(ROOT, '.cache', 'cover_meta_%s.json' % esz0)
    if os.path.isfile(meta_path):
        cm = load(os.path.join('.cache', 'cover_meta_%s.json' % esz0))
        ck('封面渲染条数 = 设置条数', cm.get('count') == cc and len(cm.get('boxes', [])) == cc,
           (cm.get('count'), len(cm.get('boxes', []))))
        ck('封面内容不越界', cm.get('used', 0) <= cm.get('cell_h', 0) + 1,
           (cm.get('used'), cm.get('cell_h')))
    for f in ['media/今日播报.mp3', 'media/今日要闻.srt', 'media/timeline.json',
              'media/今日要闻_%s.mp4' % ename, 'media/封面_%s.png' % ename]:
        ck('成品存在 ' + f, os.path.isfile(os.path.join(ROOT, f))
           and os.path.getsize(os.path.join(ROOT, f)) > 512)

    # 三栏工作台 / 逐句音轨 / 封面留白 / 片尾帧 结构性断言
    prod = open(os.path.join(ROOT, 'scripts', 'produce.py'), encoding='utf-8').read()
    dep = open(os.path.join(ROOT, 'deploy.py'), encoding='utf-8').read()
    ck('deploy 提交后回读 ref 校验', "head != nc" in dep and "raise RuntimeError('提交后回读不一致" in dep)
    ck('deploy 自动触发 Actions', "actions/workflows/daily.yml/dispatches" in dep)
    ck('deploy 提交信息带时间戳', "%Y-%m-%dT%H:%MZ" in dep)
    ck('片头优先用本期封面图', "opening_from_cover" in prod and "s['kind'] == 'opening'" in prod)
    ck('五平台尺寸已进页面', all((k + ':{n:') in html
                              for k in ('xhs', 'wechat', 'square')))
    rend = open(os.path.join(ROOT, 'scripts', 'render.py'), encoding='utf-8').read()
    src = open(os.path.join(ROOT, 'scripts', 'source.py'), encoding='utf-8').read()
    ck('三栏工作台骨架', 'class="workbench"' in html and 'id="propsBody"' in html
       and 'id="navrail"' in html and 'id="stage"' in html)
    ck('八个工具栏固定在右侧同一位置', html.count('<section class="panel"') == 8
       and 'function applyTab(' in html and 'function switchTab(' in html)
    ck('点导航切内容、不滚动定位', 'function goSec(' in html and 'window.scrollTo' not in html)
    ck('仅顶部两个折叠按钮', 'id="btnFoldL"' in html and 'id="btnFoldR"' in html
       and 'id="btnFoldL2"' not in html and 'id="btnFoldR2"' not in html
       and "$('btnFoldL2').onclick" not in html)
    ck('封面字号不随条数放大（服务端）', 'while title_fs < max_fs' not in rend and 'fixed_font' in rend)
    ck('封面资讯整体垂直居中（前后端）', "'centered': True" in rend
       and 'centered:true' in html and 'whitespace:Math.round' in html)
    ck('内置曲库已移除', 'id="bgmLib"' not in html and 'id="btnBgmStop"' not in html
       and '"bgm_library":' not in open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
       and 'bgm_library_note' not in open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
       and not os.path.isdir(os.path.join(ROOT, 'assets', 'bgm')))
    ck('试听为单按钮 toggle', 'id="btnBgmPreview"' in html and 'id="btnBgmStop"' not in html
       and "a.pause();a.currentTime=0;" in html and 'bgmPreviewing=true' in html)
    ck('播放器四控件齐备', all(('id="%s"' % x) in html for x in
                          ('btnPlay', 'btnReplay', 'btnFull', 'btnSubToggle')))
    ck('本期状态条与画幅条已移除', 'id="stSize"' not in html and 'id="prodBar"' not in html
       and 'class="statusbox"' not in html)
    ck('期号胶囊无描边（服务端/页面）', 'outline=cap_edge' not in rend
       and "ctx.strokeStyle='rgba(255,255,255,.65)'" not in html)
    ck('开场/片尾帧按主题反色', 'ctx.fillStyle=T.txt' in html and 'th = R.THEMES.get' in prod)
    ck('片尾帧不再写死白底白字', "ctx.fillStyle='#fff';ctx.font='800 44px" not in html)
    ck('逐句合成写进真实音轨', 'VOICE_TRACK[k]=' in html and 'function buildMergedTrack(' in html)
    ck('播放由真实音频 currentTime 驱动', 'mergedAudio.play' in html and 'a.currentTime' in html)
    ck('预览与导出共用同一份音频缓冲', 'MERGED.url' in html and 'btnExportVoiceTrack' in html)
    ck('浏览器内按帧录制导出', 'btnRecordWebM' in html and 'captureStream' in html)
    ck('文稿变更使音轨失效', 'function invalidateVoice(' in html)
    tts_src = open(os.path.join(ROOT, 'scripts', 'tts.py'), encoding='utf-8').read()
    ck('人声响度归一化', 'loudnorm' in prod)
    ck('混音关闭自动衰减', 'normalize=0' in prod)
    ck('逐字字幕 ASS 契约', 'build_ass' in tts_src and 'build_ass' in prod)
    ck('成品音量已记录', isinstance(vs.get('audio', {}).get('mean_db'), (int, float)))
    ck('静帧编码 fps=8', 'fps=8' in prod)
    ck('静帧编码 crf=30', "'-crf', '30'" in prod)

    # ---- L1 语义编排（表格可选列驱动） ----
    src_py = open(os.path.join(ROOT, 'scripts', 'source.py'), encoding='utf-8').read()
    sem = data.get('semantic') or {}
    ck('L1 契约存在且标记为表格列驱动', sem.get('mode') == 'L1' and 'columns' in sem, sem.get('mode'))
    ck('L1 可选列 12 项', len(sem.get('columns', [])) == 12, len(sem.get('columns', [])))
    ck('L1 列解析只读表头（无正则抽取/词表）',
       'SEM_COLS' in src_py and 'sem_index(' in src_py and 'build_semantic(' in src_py
       and 'BOARD_TABLE' not in src_py and 'extract_hero' not in src_py)
    ck('L1 头条数值来自列', bool((sem.get('hero') or {}).get('value')),
       (sem.get('hero') or {}).get('value'))
    ck('L1 专题按专题ID分组（>=2 条）',
       all(len(t.get('items', [])) >= 2 for t in sem.get('topics', [])),
       [(t.get('id'), len(t.get('items', []))) for t in sem.get('topics', [])])
    ck('L1 板块去重统计', sem.get('stats', [{}] * 3)[1].get('num')
       == '%02d' % len(sem.get('boards', [])), sem.get('boards'))
    ck('L1 N 条全部有归属',
       sem.get('count') == 1 + sem.get('topic_count', 0) + sem.get('rest_count', 0),
       (sem.get('count'), sem.get('topic_count'), sem.get('rest_count')))
    ck('data.js 与 data.json 语义块同源',
       (m and json.loads(m.group(1)).get('semantic', {}).get('mode') == 'L1'))
    ck('data_source 声明 L1 列',
       ds.get('semantic_mode') == 'L1' and len(ds.get('semantic_columns', [])) == 12)
    ck('inline_payload 封面带 sem',
       all('sem' in c for c in ds.get('inline_payload', {}).get('cover', [])))
    ck('manifest 带语义块与列契约',
       mf.get('semantic', {}).get('mode') == 'L1'
       and mf.get('config', {}).get('semantic', {}).get('mode') == 'L1')
    ck('封面四套模板（含 semantic）',
       all(x in html for x in ("semantic:'语义编排'", 'rank:' + "'榜单卡片'"))
       and "cfg.get('tpl') == 'semantic'" in rend
       and 'if(S.cover.tpl===\'semantic\'' in html)
    ck('无可选列走等权列表、有可选列走杂志版，均不回退榜单',
       'def _render_equal_cover(' in rend and 'function drawEqualCover(' in html
       and "if not sem['enabled']" in rend and 'if(!sem.enabled)' in html
       and "return render_cover(root, payload, dict(cfg, tpl='rank')" not in rend)
    ck('等权列表：统计条隐藏、字号固定、整组居中',
       "'stats_hidden': True" in rend and "'fixed_font': True" in rend
       and "'centered': True" in rend and 'stats_hidden:true' in html
       and 'coverItemStyle(T,u,land)' in html)
    ck('等权列表：条目卡片化且三档间距真实生效',
       "SPACING = {'compact': (8, 10), 'standard': (11, 14), 'airy': (16, 20)}" in rend
       and 'card_gap' in rend and "'card_gap': round(gap, 2)" in rend
       and "SP={compact:[8,10],standard:[11,14],airy:[16,20]}" in html
       and 'card_gap:Math.round(gap)' in html
       and '\n    gap = 10 * u\n' not in rend and 'gap=10*u' not in html)
    ck('杂志版不画统计条（板块为空也不摆 00）',
       "'stats_hidden': True" in rend and 'stats_hidden:true' in html
       and "if sem['boards']:" not in rend
       and 'sem.boards.length?semStats' not in html)
    ck('杂志版精简为顺序行盒，文字块做相交自检',
       'def list_section(' in rend and 'const listSection=' in html
       and 'def draw_lines(' in rend and 'const drawLines=' in html
       and "'overlap_count': len(ov)" in rend and 'overlap_count:ov.length' in html
       and "cols = 2 if len(sem['rest']) >= 4 else 1" not in rend
       and "cols=sem.rest.length>=4?2:1" not in html)
    ck('杂志版删掉头条摘要/来源/角标与专题逐条来源',
       "'来源 · '" not in rend[rend.index('def render_semantic_cover'):]
       and "'来源 · '" not in html[html.index('function drawSemanticCover'):html.index('function drawCover')])
    ck('前后端语义块同逻辑',
       'function buildSemantic(' in html and 'def build_semantic(' in src_py
       and 'function drawSemanticCover(' in html and 'def render_semantic_cover(' in rend)
    ck('横版杂志版重排为报头横贯＋头条横带＋下半双栏',
       'def land_band(' in rend and 'land_fs, land_rh = land_band()' in rend
       and 'const ry0=496*u' in html and 'const landList=' in html
       and 'ly0, ly1 = head_bottom, H - footer_h' not in rend
       and 'lx1=W*.41' not in html)
    ck('横版资讯字号下限 30u 且两栏共用同一 fs',
       'fs = min(34 * u, cap)' in rend and 'let fs=Math.min(34*u,cap)' in html
       and 'max(26 * u, fs)' in rend and 'Math.max(26*u,fs)' in html)
    ck('默认封面模板为 semantic', ct.get('tpl') == 'semantic', ct.get('tpl'))
    if os.path.isfile(meta_path):
        cmv = load(os.path.join('.cache', 'cover_meta_%s.json' % esz0))
        if cmv.get('semantic'):
            _exp = ('equal' if not cmv.get('enabled')
                    else ('magazine_band' if cmv.get('size') == 'landscape' else 'magazine'))
            ck('语义封面渲染条数 = 设置条数', cmv.get('count') == cc, cmv.get('count'))
            ck('封面版式标识正确',
               cmv.get('layout') in ('equal', 'magazine', 'magazine_band'), cmv.get('layout'))
            ck('版式与本次表格素材一致', cmv.get('layout') == _exp,
               (cmv.get('layout'), _exp))
            if cmv.get('layout') == 'magazine_band':
                ck('横版资讯字号≥30 且两栏字号统一',
                   (cmv.get('land_fs') or 0) >= 30 and cmv.get('uniform_font') is True,
                   (cmv.get('land_fs'), cmv.get('uniform_font')))
                ck('横版双栏行高与导出字号同源',
                   (cmv.get('land_rh') or 0) >= 78
                   and abs((cmv.get('font_fs') or 0) - round(cmv.get('land_fs') or 0)) <= 1,
                   (cmv.get('land_rh'), cmv.get('font_fs'), cmv.get('land_fs')))
            ck('语义封面头条数值同源',
               cmv.get('layout') == 'equal'
               or cmv.get('hero_value') == (sem.get('hero') or {}).get('value'),
               cmv.get('hero_value'))
            ck('语义封面专题/其余条数同源',
               cmv.get('layout') == 'equal'
               or (cmv.get('topic_count') == sem.get('topic_count')
                   and cmv.get('rest_count') == sem.get('rest_count')))
            ck('杂志版文字块两两不相交',
               cmv.get('layout') == 'equal'
               or (cmv.get('overlap_count') == 0 and (cmv.get('text_boxes') or 0) >= 8),
               (cmv.get('overlap_count'), cmv.get('text_boxes'), cmv.get('overlaps')))

    closing_md = open(os.path.join(ROOT, '口播文稿.md'), encoding='utf-8').read()
    CLOSING = '以上是今日要闻速览，感谢收听，下期见。'
    ck('片尾只朗读这一句', data.get('close') == CLOSING
       and ds.get('closing') == CLOSING
       and mf['segments'][-1]['text'] == CLOSING
       and '# 片尾（可单独编辑）\n\n' + CLOSING in closing_md)
    ck('免责声明：页面与片尾帧展示，不朗读、不进口播、不进字幕',
       '免责声明（页面与片尾帧展示' in html
       and "const DISCLAIMER='内容依据公开信息整理" in html
       and "DISCLAIMER = '内容依据公开信息整理" in prod
       and '不构成投资' not in data.get('close', '')
       and '不构成投资' not in ds.get('closing', '')
       and 'disclaimer' in data
       and "ctx.fillText('内容依据公开信息整理 · 以官方发布为准'" not in html)
    ck('片尾帧无重复条数与窗口行、免责声明进帧',
       "item_count_shown:false" in html and 'window_once:true' in html
       and "ctx.fillText('本期 '+P.news.length" not in html
       and '免责声明' in prod and "'disclaimer': DISCLAIMER" in prod)
    ck('字幕烧进视频画面', '.sublayer{display:none!important}' in html
       and 'function drawSubtitleCanvas(' in html
               and "drawSubtitleCanvas(ctx,$('plCanvas').width||540" in html
        and 'band:window.__cardDrawSubBand' in html)
    ck('时间轴可拖动指针定位', all(x in html for x in
       ('id="pbarHead"', 'id="tlHead"', 'function seekToRatio(', 'function bindSeek(',
        'setPointerCapture')))
    ck('混声只有三项且前后端同源', all(('id="%s"' % x) in html for x in
       ('mixVoice', 'mixBgm', 'mixMaster'))
       and not any(('id="%s"' % x) in html for x in
                   ('mixDuck', 'mixDuckDb', 'mixFadeIn', 'mixFadeOut'))
       and 'function mixCfg(' in html and 'mix' in mf['config']
       and 'master_gain_db' in mf['config']['voice']
       and 'concurrency' in mf['config']['voice'])
    ck('默认响度提高、不再压低配乐与自动淡入淡出',
       float(ds.get('voice', {}).get('volume') or 0) > 1.0
       and float(ds.get('mix', {}).get('master_gain_db') or 0) > 0
       and ds.get('mix', {}).get('duck') is False
       and float(ds.get('mix', {}).get('fade_in', 1)) == 0
       and float(ds.get('mix', {}).get('fade_out', 1)) == 0
       and float(data.get('voice_volume_default') or 0) > 1.0
       and 'volume:1.35' in html and 'master_db:3' in html
       and 'function attachVoiceGain(' in html
       and "S.mix.duck=false;S.mix.fade_in=0;S.mix.fade_out=0" in html)
    ck('服务端混音 duck 与淡入淡出',
       'duck_db' in prod and 'afade=t=in' in prod and 'afade=t=out' in prod)
    ck('逐句合成增量复用与持久化缓存',
       'LAST_SIG' in html and 'indexedDB.open' in html
       and 'function cacheGet(' in html and '增量复用' in html)
    _SEPS = ('bands', 'cards', 'lines', 'bars', 'none', 'dashes', 'outline', 'accent', 'inset')
    ck('条目分隔九套方案 + 自由强度/强调色，前后端同源且写进配置',
       "const CV_SEPS={bands:'隔行底色',cards:'独立卡片',lines:'细线分隔',bars:'左侧色条',none:'纯留白'" in html
       and "dashes:'虚线分隔',outline:'描边框',accent:'朱红短杠',inset:'内缩双线'" in html
       and "SEP_MODES = ('bands', 'cards', 'lines', 'bars', 'none', 'dashes', 'outline', 'accent', 'inset')" in rend
       and 'id="sepStrength"' in html and 'id="sepAccent"' in html
       and 'sep_strength' in html and 'sep_accent' in html
       and 'def _sep_paint(d, co, mode, x0, y0, x1, y1, i, strong, u, cfg=None)' in rend
       and 'function sepMode(' in html and 'function sepPaint(' in html
       and 'def _sep_mode(' in rend and 'def _sep_paint(' in rend
       and 'id="cvSeps"' in html and "chips($('cvSeps'),CV_SEPS" in html
       and 'sep:sepMode()' in html and "'sep': sep_mode" in rend
       and 'sepPaint(ctx,sepCo' in html and '_sep_paint(d,' in rend
       and ct.get('sep') in _SEPS
       and ds.get('cover_theme', {}).get('sep') in _SEPS
       and mf['config'].get('cover', {}).get('sep') in _SEPS
       and "const tpl=S.cover.tpl" in html
       and "plain_num = (tpl == 'list')" in rend)
    ck('语义列表序号独立、行盒顺序推进且不复用 y',
       'def num_chip(' in rend and 'const numChip=' in html
       and 'lines.append((rh, row))' in rend and 'lines.push([rh,y=>' in html
       and 'def draw_lines(' in rend and 'const drawLines=' in html
       and "'divider': False" in rend
       and "T.dark?'#dbe8f8':T.txt" in html and '(219, 232, 248)' in rend)
    ck('杂志版精简编排：无统计条/摘要/来源/角标，字号下限 22u',
       'def _draw_stats(' not in rend and 'statH=56*u' not in html
       and 'stat_h = int(56 * u)' not in rend
       and 'def hero_lines(' in rend and 'const heroLines=' in html
       and '22 * u' in rend and '22*u' in html
       and '先看这一条' not in rend and '先看这一条' not in html)
    ck('榜单卡片无边框线（纯留白方案下连结构线也不画）',
       "if(i<3&&!noDecor)" in html and "if i < 3 and not no_decor:" in rend
       and 'noDecor=sepMode()' in html)
    ck('报头重点头条角标放大且移到右上角',
       "const tagTxt='头条',tagFs=Math.round(28*u)" in html and "tag_f = F(int(28 * u)" in rend)
    ck('v12 卡片来源只拼渠道名、无链接、无编号、无底色',
       "chans = [re.sub(" in rend and "card.get('sources', [])]" in rend
       and "src_s = '来源：' + ' · '.join(chans)" in rend
       and "const chans=(c.sources||[]).map(s=>String(s.platform||'')" in html
       and "const srcS='来源：'+chans.join(' · ')" in html
       and "'src_channels_only': True" in rend and "src_channels_only:!srcS.includes('http')" in html
       and "'src_red': False" in rend and 'src_red:false' in html)
    ck('v12 摘要恒等于内容摘要列、原文图片列仍随表解析',
       "def original_image_of(raw):" in src and "'bg_image': original_image_of(" in src
       and "function composeSummary(lead,body){return {summary:cleanSummaryText(body),lead:''}}" in html
       and "function originalImageOf(v)" in html and "bg_image:pi>=0?originalImageOf" in html
       and "return clean_summary_text(body), ''" in src)
    ck('v12 卡片来源只要渠道、无链接、无编号',
       "'来源：' + ' · '.join(chans)" in rend and "chans = [re.sub(" in rend
       and "const srcS='来源：'+chans.join(' · ')" in html
       and "'src_channels_only': True" in rend and "src_channels_only:!srcS.includes('http')" in html)
    ck('原文图片不再作背景：渲染层纯色、无异步加载与遮罩',
       "CARD_BG_ENABLED = False" in rend
       and "(_card_bg(root, card, W, H, theme) if CARD_BG_ENABLED else None)" in rend
       and "'bg_disabled': not CARD_BG_ENABLED" in rend
       and "bg_applied = False" in rend
       and "bg_disabled:true" in html and "bg_applied:false" in html
       and "function loadCardBg(" not in html and "CARD_BG_CACHE" not in html
       and "ctx.drawImage(bgIm" not in html and "crossOrigin='anonymous'" not in html)
    ck('日期下移且上横线位置保持不动（竖262/横226，线1 328/272）',
       "CARD_DATE_Y_P, CARD_DATE_Y_L = 262, 226" in rend
       and "date_y = card_geom('date_y', W, H)" in rend
       and "dateY=cg.dateY" in html
       and "CARD_LINE1_P, CARD_LINE1_L = 328, 272" in rend
       and "const line1=cg.line1" in html
        and "line1 = card_geom('line1', W, H)" in rend
        and "272 / 1080.0, 328 / 1920.0" in rend)
    ck('来源与下横线距离放大（竖96/横72），线2 位置不变',
       "CARD_SRC_GAP_P, CARD_SRC_GAP_L = 96, 72" in rend
       and "src_y = line2 + int((CARD_SRC_GAP_L if land else CARD_SRC_GAP_P) * u)" in rend
       and "srcY=line2+Math.round((land?72:96)*u)" in html
       and "CARD_LINE2_P, CARD_LINE2_L = 1512, 856" in rend)
    ck('v12 报头三件套竖横同字号 50/32/30 且日期纯文字',
       "CARD_BRAND_FS = 50" in rend and "CARD_DATE_FS = 32" in rend and "CARD_ISSUE_FS = 30" in rend
       and "const hdrFs=[50,32,30]" in html and "'date_no_bg': True" in rend
       and "date_no_bg:true" in html)
    ck('v12 两条横线与三段首行缩进、标题填满折行',
       "CARD_LINE1_P, CARD_LINE1_L = 328, 272" in rend
       and "CARD_LINE2_P, CARD_LINE2_L = 1512, 856" in rend
       and "def fill_wrap(d, text, font, maxw, indent=0):" in rend
       and "function fillWrapText(ctx,text,font,maxW,indent)" in html
       and "'line1_y': line1" in rend and "line1_y:line1" in html
       and "'three_blocks_aligned': True" in rend)
    ck('v12 序号+分类标签去掉、横版单栏、内容组靠上',
       "'no_label_row': True" in rend and "no_label_row:true" in html
       and "'content_group_top': True" in rend and "content_group_top:true" in html
       and "'landscape_single_column': True" in rend and "landscape_single_column:true" in html
       and "'src_anchored_bottom': False" in rend and "src_anchored_bottom:false" in html)
    ck('v12 标题色随主题反相、摘要冷蓝次级色差保持',
       "def card_title(theme)" in rend and "function cardInk(T)" in html
       and "SUM_BASE_MIX = .58" in rend and "SUM_COOL_MIX = .20" in rend
       and "function sumColorHex(T)" in html and "'title_color_sep': True" in rend)

    ck('取消后可立即再合成、断点续合',
       'let voiceBusy=false' in html and 'voiceRun++' in html and '断点' in html
       and 'Promise.all(missing.map' in html and 'Promise.all(raw.map' in html)
    ck('等权封面整组居中且每侧留白封顶',
       'const MAX_SIDE=84*u' in html and 'MAX_SIDE = 84 * u' in rend)
    ck('v12 卡片整卡等比、正文 42/38、来源不溢出',
       'const u=H/(land?1080:1920)' in html and 'u = H / (1080.0 if land else 1920.0)' in rend
       and 'u = H / (1080.0 if is_land(size) else 1920.0)' in rend
       and 'CARD_BODY_P, CARD_BODY_L = 42, 38' in rend
       and 'CARD_SRC_FS = 32' in rend and 'CARD_SRC_FS=32' in html
       and "'overflow': src_end > H" in rend and 'overflow:srcEnd>H' in html
       and 'card_overflow' in prod
       and (not vs.get('ok') or vs.get('card_overflow') == []))


    # 标题与摘要必须真实不同色，且摘要仍清晰可读（静态按同一套配色公式计算）
    def _lum(c):
        q = [x / 255.0 for x in c]
        q = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in q]
        return .2126 * q[0] + .7152 * q[1] + .0722 * q[2]
    def _cr(a, b):
        la, lb = _lum(a), _lum(b)
        return (max(la, lb) + .05) / (min(la, lb) + .05)
    def _hex(s):
        s = s.lstrip('#')
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    def _mix(a, b, t):
        return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
    _t = [('#0d1b2a', '#f4f8fd', '#a9bdd4', True), ('#14161a', '#f4f8fd', '#a7adb8', True),
          ('#101a38', '#f4f8fd', '#a9b8de', True), ('#f7f9fc', '#0e1724', '#5a6c82', False),
          ('#faf5ea', '#0e1724', '#756454', False), ('#f0f6fc', '#0e1724', '#5a7390', False)]
    _sep, _read = [], []
    for _bg, _fg, _sub, _dark in _t:
        _sum = _mix(_mix(_hex(_sub), _hex(_fg), .58),
                    _hex('#8fb2d4' if _dark else '#3c5a7d'), .20)
        _sep.append(sum(abs(a - b) for a, b in zip(_hex(_fg), _sum)))
        _read.append(_cr(_hex(_bg), _sum))
    ck('标题与摘要真实不同色（6 主题 RGB 总差均 >=60）', min(_sep) >= 60,
       [round(x, 1) for x in _sep])
    ck('摘要仍清晰可读，不回到浅灰小字（6 主题对比度均 >=6.5:1）', min(_read) >= 6.5,
       [round(x, 2) for x in _read])
    ck('标题比摘要更亮/更跳，层级方向正确（6 主题）',
       all(_cr(_hex(bg), _hex(fg)) > _cr(_hex(bg), _mix(
           _mix(_hex(sub), _hex(fg), .58), _hex('#8fb2d4' if dark else '#3c5a7d'), .20))
           for bg, fg, sub, dark in _t))

    ck('视频卡前后端均整卡等比（横屏来源不溢出）',
       'u=H/(W>H?1080:1920)' in html and 'u = H / (1080.0 if land else 1920.0)' in rend
       and 'const scale=Math.min(W,H)/1080' in html
       and (not vs.get('ok') or vs.get('card_overflow') == []))

    ck('封面默认显示 8 条，且各源同源',
       "count:8" in html and 'value="8"' in html
       and "payload.get('cover_count', 8)" in rend
       and "payload.get('cover_count') or 8" in src_py
       and int(data.get('cover_count', 0)) == cc
       and int(ds.get('cover_count', 0)) == cc
       and int(ct.get('count', 0)) == cc)
    ck('语义列表不再逐条缩字号，整组统一字号',
       'uniform_lines' in rend and 'uniformLines' in html
       and 'uniform_font_per_group' in rend and 'uniform_font_per_group:true' in html
       and "while d.textlength(text, font=f) > maxw and fs > minfs" not in rend
       and "while(ctx.measureText(text).width>maxW&&fs>minFs)" not in html
       and "one_line(txt1" not in rend and 'oneLine(it.label' not in html)
    ck('标题右侧不再提前折行（头条角标只占第一条）',
       "const maxW0=maxW-(S.cover.tpl==='headline'?120*u:0)" in html
       and "(S.cover.tpl==='headline'&&i===0)?maxW0:maxW" in html
       and "maxw0 = maxw - (int(120 * u) if tpl == 'headline' else 0)" in rend
       and "mw = maxw0 if (tpl == 'headline' and idx == 0) else maxw" in rend)
    ck('语义编排条目间距三档前后端真实生效（紧凑=旧标准/标准=旧宽松/宽松更大）',
       "const RG={compact:18,standard:34,airy:50}" in html
       and "const GL={compact:8,standard:15,airy:22}" in html
       and "{'compact': 18, 'standard': 34, 'airy': 50}.get(gap_cfg" in rend
       and "{'compact': 8, 'standard': 15, 'airy': 22}.get(gap_cfg" in rend
       and 'gapL=GL*u' in html and 'gapL = land_gap' in rend
       and "const RH_GAP=34*u,LH_GAP=28*u" in html and 'rh_gap, lh_gap = 34 * u, 28 * u' in rend
       and 'row_gap:Math.round(rowGap)' in html and "'land_gap': round(land_gap, 2)" in rend)
    ck('刷新在线音色一律中文名，不再把英文 id 当标签',
       'const VOICE_CN0=' in html and 'function cnVoiceName(' in html
       and 'VOICE_ALIAS=[' in html and "o.textContent=cnVoiceName(o.value)" in html
       and "'<option value="'+esc(id)+'">'+esc(nm)+'</option>'" not in html)
    ck('数据入口两个 sheet 各占一行，不再 flex-wrap 错位',
       '<label class="lb">文稿 sheet</label><input type="text" id="sheetScript"' in html
       and '<label class="lb">封面 sheet</label><input type="text" id="sheetCover"' in html
       and 'flex:0 0 60px' not in html)
    ck('点选项不跳回面板顶部（仅切 tab 才复位滚动）',
       "const _pb=$('propsBody'),_keep=_pb?_pb.scrollTop:0" in html
       and "if(_pb&&_pb.scrollTop!==_keep)_pb.scrollTop=_keep" in html
       and "if(_t!==id){pb.setAttribute('data-tab',id);pb.scrollTop=0;}" in html)
    ck('间距档位按旧档位整体放大一档：紧凑=旧标准/标准=旧宽松/宽松更大',
       "const GAPS={compact:'紧凑',standard:'标准',airy:'宽松'}" in html
       and '紧凑 / 标准 / 宽松' in html
       and "'compact': 16, 'standard': 28, 'airy': 40" in rend
       and "const SP={compact:[8,10],standard:[11,14],airy:[16,20]}" in html
       and "SPACING = {'compact': (8, 10), 'standard': (11, 14), 'airy': (16, 20)}" in rend)
    ck('v12 摘要恒等于内容摘要列、不分段、保留 Excel 首行缩进',
       "return clean_summary_text(body), ''" in src
       and "function composeSummary(lead,body){return {summary:cleanSummaryText(body),lead:''}}" in html
       and 'function splitSummary(' not in html and 'def _summary_paras(' not in rend
       and 'CARD_INDENT =' not in rend and "'no_paragraph_split': True" in rend
       and 'no_paragraph_split:true' in html
       and 'excel_indent' in rend and 'const lead=raw.match' in html
       and "'body_excel_indent_kept': sind > 0" in rend)

    ck('标题与摘要仍分级配色（页面与服务端同源）',
       'function sumColorHex(' in html and 'sumColorHex(T)' in html
       and 'sum_col = mix(mix(sub, title_col, SUM_BASE_MIX)' in rend
       and "'title_color_sep': True" in rend
       and "'summary_color_lift': True" in rend)
    ck('导出多格式：视频/音频/字幕/图片/文稿/配置共 11 种，单一主按钮',
       'id="expFmt"' in html and 'const EXPORT_FORMATS=' in html
       and html.count('<option value=') >= 11
       and 'export_format:exportFormat()' in html
       and "exportFormat()!=='mp4'" in html
       and "id==='btnExpVideo'&&sel&&sel.value!=='mp4'" in html
       and 'function buildAss(' in html)
    # ---- 全链路品牌名、旧状态迁移、URL 折行、卡片报头结构 ----
    _brand_files = ['index.html', 'cover_theme.json', 'data.json', 'data_source.json',
                    'render_manifest.json', 'data.js', 'scripts/render.py',
                    'scripts/produce.py', 'scripts/source.py']
    _old_brand = '每日' + '要闻速览'
    _residual = [f for f in _brand_files
                 if _old_brand in open(os.path.join(ROOT, f), encoding='utf-8').read()]
    ck('全链路品牌名统一为今日要闻速览', not _residual, _residual)
    _cfgs = ['cover_theme.json', 'data_source.json', 'data.json', 'render_manifest.json']
    ck('各配置层封面标题均为今日要闻速览',
       all(load(f)['cover_header']['title'] == '今日要闻速览' for f in _cfgs))
    ck('页面默认值与内嵌 payload 已改今日要闻速览',
       'value="今日要闻速览"' in html and '"title": "今日要闻速览"' in html)
    ck('旧浏览器状态自动迁移，换包刷新不会残留旧品牌名',
       "const STATE_VER='r27-1'" in html and "const OLD_BRAND='每日'+'要闻速览'" in html
       and "S.cover.title=DEF.cover.title" in html
       and "split(OLD_BRAND).join('今日要闻速览')" in html)


    ck('v12 报头三件套 50/32/30 竖横一致、日期纯文字无底色',
       "CARD_BRAND_FS = 50" in rend and "CARD_DATE_FS = 32" in rend and "CARD_ISSUE_FS = 30" in rend
       and "const hdrFs=[50,32,30]" in html and 'header_aligned_cover:true' in html
       and 'date_no_bg:true' in html and "'date_no_bg': True" in rend
       and "'header_aligned_cover': True" in rend
       and "hdr_fs:hdrFs[1]" in html and "issue_fs:hdrFs[2]" in html)

    # 真实执行 node --check：静态字符串全绿也可能整段 JS 语法错误导致白屏
    import subprocess, tempfile, shutil
    _js = '\n'.join(re.findall(r'<script>([\s\S]*?)</script>', html))
    _node = shutil.which('node')
    if _node:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as _f:
            _f.write(_js)
            _tmp = _f.name
        try:
            _r = subprocess.run([_node, '--check', _tmp], capture_output=True,
                                text=True, timeout=60)
            ck('页面内联 JS 真实语法检查（node --check）', _r.returncode == 0,
               (_r.stdout + _r.stderr)[-200:])
        finally:
            os.unlink(_tmp)
    else:
        ck('页面内联 JS 真实语法检查（无 node，退化为正则字面量断言）',
           'URL_SEG=/' in html and 'URL_SEG=[^' not in html)

    ck('标题色随主题反相：浅冰蓝不再用主题蓝，6 主题对比度 >=10',
       'function cardInk(T)' in html and 'def card_title(theme)' in rend
       and "CARD_INK_LIGHT = '#0e1724'" in rend and "'#0e1724'" in html
       and all(_cr(_hex(bg), _hex(fg)) >= 10 for bg, fg, _, _ in _t),
       [round(_cr(_hex(bg), _hex(fg)), 2) for bg, fg, _, _ in _t])
    ck('浅冰蓝标题改为中性深墨且不再沿用主题蓝',
       max(_hex('#0e1724')) < 60
       and sum(abs(a - b) for a, b in zip(_hex('#0e1724'), _hex('#12263d'))) >= 40)
    ck('v12 序号+分类标签整行去掉、两条浅色横线、内容组靠上',
       "'no_label_row': True" in rend and "no_label_row:true" in html
       and "ctx.fillText('NO.'+String(idx+1)" not in html
       and "'line1_y': line1" in rend and 'line1_y:line1' in html
       and "CARD_LINE1_P, CARD_LINE1_L = 328, 272" in rend
       and "CARD_LINE2_P, CARD_LINE2_L = 1512, 856" in rend
       and "'content_group_top': True" in rend and "content_group_top:true" in html)


    # ---- r14 四项反馈的防回归断言 ----
    ck('四套封面模板标题字号默认与语义编排一致（竖38 / 横34）',
       'title_fs = int(_cis[1])' in rend and 'base_fs = _cis[1]' in rend
       and '(land?34:38)' in html and 'baseFs=(land?38:44)*u' not in html)
    ck('标题样式控件齐全（字体 / 字号 / 颜色 / 随主题 / 加粗）',
       all(('id="%s"' % x) in html for x in
           ('cvItemFont', 'cvItemFs', 'cvItemColor', 'cvItemAutoColor', 'cvItemBold')))
    ck('标题样式前后端同源且导出配置携带',
       'function coverItemStyle(' in html and 'def cover_item_style(' in rend
       and 'def CF(' in rend and 'COVER_ITEM_FONT_MAP' in rend
       and 'item_style:itemStyleCfg()' in html and 'item_style' in ct)
    ck('字体映射含随包 ttc 两个真实 face',
       "'mono':  [('assets/fonts/wqy-microhei.ttc', 1)" in rend)
    ck('折行去掉词组表、只保留数字单位原子与单字',
       '_FILL_PAIR' not in rend and '浓雾|大雾|机构' not in html
       and '_FILL_TOK = re.compile' in rend and 'FILL_TOK=/[0-9A-Za-z' in html)
    ck('字幕分片函数前后端同源（30 字上限）',
       'def subtitle_chunks(' in tts_src and 'SUB_CHUNK_MAX = 30' in tts_src
       and 'function subChunks(' in html and 'SUB_CHUNK_MAX=30' in html
       and 'function subChunkAt(' in html)
    ck('SRT / ASS / 页面预览三处按片段替换',
       'chunks = subtitle_chunks(text)' in tts_src
       and 'for chunk in chunks:' in tts_src
       and 'subChunks(txt)' in html and 'subChunkAt(text,ratio)' in html
               and 'wrapText(ctx,shown,maxW,ml)' in html
        and 'const ml=Math.max(1,Math.min(3,+cfg.max_lines||2))' in html)
    ck('片尾帧顺序行盒登记 bbox 且做重叠自检',
       'overlap' in prod and 'outro_meta_' in prod and 'boxes' in prod)
    ck('生产段 opening/closing 归一化，片尾不 fallback 成窗口说明',
       "'opening': 'open'" in prod and "'closing': 'close'" in prod
       and 'kind_norm' in prod and 'labels.get(kind_norm' in prod
       and "if kind_norm == 'close'" in prod)
    ck('旧浏览器状态迁移到 r25-1', "const STATE_VER='r27-1'" in html
       and 'itemFont' in html and "if(o.__ver!==STATE_VER)" in html)

    ck('stillimage 调优', "'-tune', 'stillimage'" in prod)
    ck('音频 64k 单声道', "'-b:a', '64k'" in prod and "'-ac', '1'" in prod)

    # r16：短画幅整卡等比 —— 真跑渲染器检查文字块两两不相交，
    # 不再只看「有没有画出画布」（上一版 3:4 / 6:7 / 1:1 全绿却叠字，就是漏了这项）
    ck('短画幅整卡等比缩放前后端同源',
       "u = H / (1080.0 if land else 1920.0)" in rend
       and "u = H / (1080.0 if is_land(size) else 1920.0)" in rend
       and "const u=H/(land?1080:1920)" in html)
    try:
        import importlib.util as _ilu
        _sp = os.path.join(ROOT, 'scripts', 'render.py')
        _spec = _ilu.spec_from_file_location('_vr_render_r16', _sp)
        _R = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_R)
        _hdr = {'title': '今日要闻速览', 'date': '2026年11月16日 · 星期一',
                'issue': '第01期', 'show_title': True, 'show_date': True, 'show_issue': True}
        _cfg0 = dict((mf.get('config') or {}).get('video_card') or {})
        _c = (mf.get('cards') or [{}])[0]
        _tmp = os.path.join(ROOT, '.cache', '_r16_boxes')
        os.makedirs(_tmp, exist_ok=True)
        _pairs = [('kicker', 'brand'), ('brand', 'date'), ('date', 'line1'),
                  ('line1', 'title'), ('title', 'summary'), ('summary', 'line2'), ('line2', 'src')]
        for _sz in ('portrait', 'landscape', 'xhs', 'wechat', 'square'):
            _mm = _R.render_card(ROOT, _c,
                                 dict(_cfg0, size=_sz, card_header=_hdr, theme='deep_blue'),
                                 os.path.join(_tmp, _sz + '.png'))
            _b = _mm['boxes']
            _errs = ['%s底> %s顶' % (a, c) for a, c in _pairs
                     if _b[a][1] > _b[c][0] + 2]
            if _b['src'][1] > _mm['h'] + 1:
                _errs.append('来源出画布')
            ck('文字块不相交 ' + _sz, not _errs, ';'.join(_errs))
    except Exception as _e:
        ck('短画幅文字块不相交', False, repr(_e))

    # ---- r19：短画幅大字优先 + 下横线/来源随内容下移（真跑渲染器，不只看源码字符串）----
    ck('短画幅正文放大与来源内容驱动前后端同源',
       'CARD_SHORT_FS_BOOST' in rend and 'CARD_SHORT_BOTTOM_PAD' in rend
       and 'const short=u<1,fsU=short?1.12:u' in html
       and 'fs_u = max(u, CARD_SHORT_FS_MIN) * CARD_SHORT_FS_BOOST if short else u' in rend
       and "'src_follows_summary': bool(short)" in rend
       and 'src_follows_summary:short' in html
       and 'line2 = min(sum_end + int(CARD_SHORT_LINE_GAP * u), max_line2)' in rend)
    try:
        import importlib.util as _ilu3
        _sp3 = os.path.join(ROOT, 'scripts', 'render.py')
        _sp3o = _ilu3.spec_from_file_location('_vr_render_r17', _sp3)
        _R3 = _ilu3.module_from_spec(_sp3o); _sp3o.loader.exec_module(_R3)
        _hdr3 = {'title': '今日要闻速览', 'date': '2026年11月16日 · 星期一',
                 'issue': '第01期', 'show_title': True, 'show_date': True, 'show_issue': True}
        _cfg3 = dict((mf.get('config') or {}).get('video_card') or {})
        _c3 = (mf.get('cards') or [{}])[0]
        _tmp3 = os.path.join(ROOT, '.cache', '_r17_boxes'); os.makedirs(_tmp3, exist_ok=True)
        for _sz3 in ('portrait', 'landscape', 'xhs', 'wechat', 'square'):
            _m3 = _R3.render_card(ROOT, _c3, dict(_cfg3, size=_sz3, card_header=_hdr3, theme='deep_blue'),
                                  os.path.join(_tmp3, _sz3 + '.png'))
            if _sz3 in ('xhs', 'wechat', 'square'):
                ck('短画幅摘要明显放大 ' + _sz3, _m3['sum_fs'] >= 40, _m3['sum_fs'])
                ck('短画幅无大块留白 ' + _sz3, _m3['whitespace_below'] <= 160, _m3['whitespace_below'])
                ck('短画幅横线与来源随内容下移 ' + _sz3,
                   _m3['content_driven_rule'] and _m3['src_follows_summary']
                   and 0 <= _m3['line2_y'] - _m3['summary_bottom'] <= 60
                   and _m3['src_bottom'] <= _m3['h'],
                   (_m3['line2_y'] - _m3['summary_bottom'], _m3['src_bottom']))
            else:
                ck('基准画幅字号未变 ' + _sz3, abs(_m3['fs_scale'] - 1.0) < 1e-9, _m3['fs_scale'])
                ck('基准画幅横线与来源未变 ' + _sz3,
                   not _m3['content_driven_rule'] and _m3['line2_y'] in (1512, 856),
                   _m3['line2_y'])
            # r18：报头（标题/日期/期号）独立下限，短画幅不再随 u 线性缩到看不清
            if _sz3 in ('xhs', 'wechat', 'square'):
                ck('短画幅报头字号可读 ' + _sz3,
                   _m3['header_fs'][0] >= 42 and _m3['header_fs'][1] >= 26
                   and _m3['header_fs'][2] >= 25, _m3['header_fs'])
            else:
                ck('基准画幅报头字号未变 ' + _sz3,
                   _m3['header_fs'] == [50, 32, 30], _m3['header_fs'])
    except Exception as _e3:
        ck('短画幅字号与留白回归', False, repr(_e3))

    ck('短画幅报头放大且起点上移前后端同源',
       'CARD_SHORT_HDR_MIN = .84' in rend and 'const hdrU=u<1?Math.max(u,.84):u' in html
       and 'hdr_u = max(u, CARD_SHORT_HDR_MIN) if short else u' in rend
       and 'brand_y = int((124 if land else (CARD_SHORT_BRAND_AT if short else 148)) * u)' in rend
       and 'brandY=Math.round((land?124:(short?136:148))*u)' in html
       and 'brand_fs = int(CARD_BRAND_FS * hdr_u)' in rend
       and 'date_fs = int(CARD_DATE_FS * hdr_u)' in rend)

    # ---- r17：文稿删除 / 调序 / 只保留前 N 条 ----
    ck('文稿可删除 / 上移 / 下移',
       all(x in html for x in ('function delNews(', 'function moveNews(', 'data-a="del"',
                               'data-a="up"', 'data-a="down"')))
    ck('资讯条数可设置且只保留前 N 条',
       'function setNewsLimit(' in html and 'function applyNewsView(' in html
       and "chips($('newsLimitChips')" in html and 'newsLimit' in html)
    _srcpy = open(os.path.join(ROOT, 'scripts', 'source.py'), encoding='utf-8').read()
    _dpy = open(os.path.join(ROOT, 'scripts', 'daily_update.py'), encoding='utf-8').read()
    ck('导出 / 编排 / 取数三处 news_limit 同源',
       'news_limit:S.script.limit' in html and "'news_limit': cfg.get('news_limit')" in _dpy
       and "cfg.get('news_limit')" in _srcpy)
    ck('硬闸不再写死 30 条', 'items.length===30' not in html
       and '正文条数 = 设置的前 N 条' in html)

    prod = open(os.path.join(ROOT, 'scripts', 'produce.py'), encoding='utf-8').read()

    # ---- r22：方案 D 沉浸文稿 / 配置共用 / 导航联动 / 字幕底色行数 / 播放器同源 ----
    ck('沉浸文稿全宽长卷 DOM 与函数',
       all(x in html for x in ('id="docImm"', 'id="docList"', 'id="docRail"', 'id="docMini"',
                               'function renderDoc(', 'function openDoc(', 'function docCommit(',
                               'function docItems(', 'id="btnDocImm"')))
    ck('沉浸文稿全文不截断、上下滚动看全貌',
       '#docScroll{flex:1 1 auto;overflow-y:auto' in html
       and '.docSummary{font-size:1em' in html and 'overflow:hidden;min-height:3.5em' in html
       and 'text-overflow' not in html.split('#docImm')[1].split('#docMini')[0])
    ck('沉浸文稿可调序与只保留前 N 条',
       all(x in html for x in ('data-a="top"', 'data-a="up"', 'data-a="down"', 'data-a="del"',
                               "e.altKey&&(e.key==='ArrowUp'||e.key==='ArrowDown')",
                               "go('docLimit').onchange=e=>{setNewsLimit(e.target.value);")))
    ck('尺寸/主题配置合并共用一份',
       'shared:{theme:' in html and 'function syncShared()' in html
       and 'function setShared(k,v)' in html
       and "chips($('cvThemes'),THEMES,S.shared.theme,k=>setShared('theme',k))" in html
       and "chips($('cvSizes'),SIZES,S.shared.size,k=>setShared('size',k))" in html
       and 'id="cdSharedEcho"' in html and 'id="btnGoCoverCfg"' in html)
    ck('预览三按钮同步定位右侧工具栏',
       "const PV_TAB_MAP={cover:'sec-cover',card:'sec-card',player:'sec-sub'}" in html
       and "S.pv=c.dataset.v;S.tab=PV_TAB_MAP[S.pv]||S.tab" in html)
    ck('播放器统一走卡片渲染器真实画幅',
       ' const W=sz.w,H=sz.h;' in html and "if($('plCanvas').width!==_sz.w" in html
       and "ctx.scale(PW/540,PH/960)" in html
       and 'band:window.__cardDrawSubBand' in html)
    ck('字幕底色四选一与显示行数 1/2/3',
       all(x in html for x in ('id="subLines"', 'value="none"', 'value="navy"', 'value="accent"',
                               'const SUB_BG=', 'function subMaxLines()', 'function subtitleSafeU()')))
    ck('字幕配置导出同源',
       "background_style:S.subtitle.background_style" in html
       and "max_lines:Math.max(1,Math.min(3,+S.subtitle.max_lines||2))" in html)
    ck('字幕安全带前后端同源且不压来源',
       'const subSafeU=subtitleSafeU(),subSafe=Math.min(Math.round(subSafeU*H/1920)' in html
       and 'safe_u = min(int(SUBTITLE_SAFE_U * H / 1920.0)' in rend
       and 'srcY=line2+Math.round((land?72:96)*u)+subSafe' in html
       and 'src_y = line2 + int((CARD_SRC_GAP_L if land else CARD_SRC_GAP_P) * u) + safe_u' in rend
       and 'def subtitle_safe_u(cfg)' in rend
       and "R.SUBTITLE_SAFE_U = R.subtitle_safe_u(src_cfg.get('subtitle'))" in _dpy)
    ck('服务端字幕样式支持底色与行数',
       "background_style" in prod and "max_lines" in prod and "'navy': '&H8C2A1B0D'" in prod)
    ck('STATE_VER 升级且旧状态迁移', "const STATE_VER='r27-1'" in html and 'S.shared={theme:' in html)
    # ---- r23 防回归 ----
    ck('r23 文稿改标题/删除/调序/条数后封面同源重绘',
       '__ALL_COVER[k].title' in html and 'drawCover();docPreview();' in html
       and '封面标题与当前生效文稿同源' in html)
    ck('r24 语义封面专题行跟随当前文稿标题（前后端同源）',
       "it.title||it.brief" in html and "it.brief||it.title" not in html
       and "(it['title'] or it.get('brief') or '')" in rend
       and "(it.get('brief') or it['title'])" not in rend)
    ck('r23 画面不再显示字幕安全区标识',
       "fillText('字幕安全区'" not in html and "'字幕安全区'" not in rend
       and '字幕占位：' in html)
    ck('r27 字幕行数真生效（1行不滚动15字 / 2行30字 / 3行45字，前后端同源）',
       "if(ml===1)return[s||' ']" not in html and 'const scroll=false' in html
       and "sub.style.transform='none'" in html
       and 'const cap=Math.round(SUB_CHUNK_MAX*ml/2)' in html
       and '_ACTIVE_LINES' in tts_src and 'cap = int(round(SUB_CHUNK_MAX * ml / 2))' in tts_src
       and 'chunk_lines(chunk, _ACTIVE_LINES)' in tts_src and 'j % per == 0' in tts_src)
    ck('r23 片尾标题一行不换行（前后端同源）',
       'wrapText(ctx,label,460,2)' not in html and 'while(bigFs>36' in html
       and 'while big > int(52 * u)' in prod and 'lines = [label]' in prod
       and 'title_lines:1' in html)
    ck('r23 片尾字幕带避开免责声明',
       'window.__cardDrawSubBand=[Math.round(PH*.60),Math.round(PH*.78)]' in html)


    # ---- r25 防回归：片头 / 字幕 / 分类纹样 / 可见构建标记 ----
    ck('r25 片头=本期封面，且不再回退自建资讯窗口页',
       "os.path.join(root, 'media', '封面_%s.png' % ename)" in prod
       and 'R.render_cover(root, payload, cv, tmp)' in prod
       and 'd.rounded_rectangle([pad, by, W - pad, by + bh]' not in prod
       and prod.count('opening_from_cover(root, size, p, manifest)') == 2)
    ck('r25 字幕不含资讯标题（页面 / 数据契约 / 出片三处同源）',
       'function subtitleSegments()' in html and 'function subTextOf(t,idx)' in html
       and "'sub_text': _sub_text(s, i)" in src
       and "text = s.get('sub_text') or s['text']" in tts_src
       and 'no_title:S.subtitle.no_title!==false' in html
       and "const sub=$('plSub'),full=subtitleSegments()[i]||'',fullSeg=seg[i]||''" in html)
    ck('r25 字幕逐句时长按真实音轨 offsets 差分，不再与估算时长错位',
       'MERGED.offsets.length===seg.length' in html
       and '(i+1<o.length?o[i+1]:(MERGED.dur||0))-x' in html)
    ck('r27 分类标签纹样背景前后端同源，且由「卡片背景图」开关控制（默认关）',
       'CAT_ART_RULES' in rend and 'def draw_category_art(' in rend
       and 'const CAT_ART_RULES=' in html and 'function drawCategoryArt(' in html
       and 'id="cdArtOn"' in html
       and "category_art:'off'" in html
       and 'drawCategoryArt(ctx,W,H,c,S.card.category_art' in html
       and "category_art:S.card.category_art||'off'" in html)
    ck('r25 页面有可见构建标记，Ctrl+F5 后可确认线上是否已换包',
       'r27 · 11-16' in html)
    ck('r25 分类纹样下移到中下部留白区，前后端同源且不再压标题与摘要',
       'cy=H*.66' in html and 'int(H * 0.66)' in rend
       and 'Math.min(W,H)*.17' in html and 'int(min(W, H) * 0.17)' in rend
       and 'cy=H*.30' not in html and 'int(H * 0.30)' not in rend)

    ck('r27 页面片头直接画本期封面（不再自建资讯窗口页）',
       "drawCover($('plCanvas'))" in html and "if(i===0){" in html
       and "kind:'open',cover:true" in html)
    ck('r27 卡片标题与摘要始终完整，逐字只作用于字幕层',
       'const title=String(c.title)' in html and 'const raw=String(c.summary)' in html
       and "slice(0,Math.ceil(String(c.title).length*rv))" not in html
       and "ttl = str(card['title'])" in rend
       and "drawCard($('plCanvas'),cardIdx,true,1)" in html)
    ck('r27 字幕起始对齐人声：扣掉标题朗读时长（页面 / SRT / ASS 同源）',
       'leadRatio' in html and 'lead_dur' in tts_src and 'st_sub' in tts_src)
    ck('r27 卡片背景图开关：开才画、关纯色（前后端与导出同源）',
       'id="cdArtOn"' in html and "category_art:S.card.category_art||'off'" in html
       and '"category_art": "off"' in open(os.path.join(ROOT, 'video_card_theme.json'), encoding='utf-8').read())

    bad = [c for c in CHECKS if not c['ok']]
    print('共 %d 项，失败 %d 项' % (len(CHECKS), len(bad)))
    with open(os.path.join(ROOT, 'RELEASE_CHECK.json'), 'w', encoding='utf-8') as f:
        json.dump({'checks': CHECKS, 'failed': len(bad)}, f, ensure_ascii=False, indent=2)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

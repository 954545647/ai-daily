#!/usr/bin/env python3
"""AI 日报 · 逐条学习页生成器

把当天的日报渲染成一个单文件 HTML：一次只显示一条，点「下一条」才切换，
进度会记在浏览器里，明天换新的一天自动重置。

用法：
    python3 reader.py                 # 生成今天的
    python3 reader.py --date 2026-10-28
    python3 reader.py --open          # 生成并直接用浏览器打开
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
DIGESTS = ROOT / "digests"
WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0d12">
<title>AI 每天学一点 · __DATE_LABEL__</title>
<style>
  :root{
    --bg:#0b0d12; --card:#151922; --fg:#e8ecf4; --dim:#8b94a7;
    --accent:#4c8dff; --line:#232936; --ok:#3ddc97;
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html,body{max-width:100%;overflow-x:hidden;word-break:break-word;overflow-wrap:anywhere}
  body{
    margin:0;background:var(--bg);color:var(--fg);
    font:16px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif;
    display:flex;flex-direction:column;min-height:100vh;min-height:100dvh;
  }
  header{
    position:sticky;top:0;z-index:10;background:rgba(11,13,18,.92);
    backdrop-filter:blur(12px);border-bottom:1px solid var(--line);
    padding:14px 18px calc(10px + env(safe-area-inset-top,0px));
  }
  .bar{display:flex;align-items:center;justify-content:space-between;gap:12px}
  .date{font-size:13px;color:var(--dim);letter-spacing:.02em}
  .prog{font-variant-numeric:tabular-nums;font-size:13px;color:var(--accent);font-weight:600}
  .track{height:3px;background:var(--line);border-radius:2px;margin-top:10px;overflow:hidden}
  .fill{height:100%;background:var(--accent);width:0;transition:width .28s ease;border-radius:2px}

  main{flex:1;padding:22px 18px 0;max-width:680px;width:100%;margin:0 auto}
  .slide{display:none;animation:in .26s ease}
  .slide.on{display:block}
  @keyframes in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

  .tags{margin-bottom:10px}
  .tag{
    display:inline-block;font-size:11px;padding:2px 9px;border-radius:20px;
    background:rgba(76,141,255,.12);color:#7aa9ff;margin-right:6px;
    border:1px solid rgba(76,141,255,.22)
  }
  h1{font-size:23px;line-height:1.45;margin:0 0 20px;letter-spacing:-.01em}
  .block{margin-bottom:19px}
  .label{
    font-size:11px;color:var(--dim);letter-spacing:.12em;text-transform:uppercase;
    margin-bottom:5px;font-weight:600
  }
  .text{font-size:16px;color:#d5dbe8}
  .text.hl{color:var(--fg);border-left:2px solid var(--accent);padding-left:13px}
  a.src{
    display:inline-flex;align-items:center;gap:6px;margin-top:4px;
    font-size:14px;color:var(--accent);text-decoration:none;
    border-bottom:1px solid rgba(76,141,255,.3);padding-bottom:1px
  }
  .srcname{font-size:12px;color:var(--dim);margin-left:8px}

  /* 首尾页 */
  .hero h2{font-size:13px;color:var(--dim);font-weight:600;letter-spacing:.1em;margin:0 0 12px}
  .hero p{font-size:19px;line-height:1.7;margin:0 0 22px;color:#e8ecf4}
  .toc{list-style:none;padding:0;margin:8px 0 0}
  .toc li{
    padding:10px 0;border-bottom:1px solid var(--line);font-size:14px;color:var(--dim);
    display:flex;gap:10px
  }
  .toc li b{color:var(--accent);font-variant-numeric:tabular-nums;font-weight:600}
  .task{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}
  .task .label{color:var(--ok)}

  footer{
    position:sticky;bottom:0;background:linear-gradient(transparent,var(--bg) 22%);
    padding:16px 18px calc(18px + env(safe-area-inset-bottom,0px));
    max-width:680px;width:100%;margin:0 auto;display:flex;gap:10px
  }
  button{
    flex:1;border:none;border-radius:13px;padding:15px;font-size:16px;font-weight:600;
    font-family:inherit;cursor:pointer;transition:transform .12s,opacity .12s
  }
  button:active{transform:scale(.975)}
  .next{background:var(--accent);color:#fff}
  .next.done{background:var(--ok);color:#04160d}
  .prev{flex:0 0 88px;background:var(--card);color:var(--dim);border:1px solid var(--line)}
  .prev:disabled{opacity:.3}
  .hint{
    text-align:center;font-size:12px;color:var(--dim);padding:0 18px 8px;
    max-width:680px;margin:0 auto
  }
</style>
</head>
<body>
<header>
  <div class="bar">
    <span class="date">__DATE_LABEL__ __WEEKDAY__</span>
    <span class="prog"><span id="cur">1</span> / <span id="tot">__TOTAL__</span></span>
  </div>
  <div class="track"><div class="fill" id="fill"></div></div>
</header>

<main id="main"></main>

<p class="hint">← → 键或空格切换 · 手机上左右滑动</p>

<footer>
  <button class="prev" id="prev">上一条</button>
  <button class="next" id="next">下一条 →</button>
</footer>

<script>
const DATA = __DATA__;
const STORE = 'aidaily-pos-' + DATA.date;
let i = 0;

function esc(s){return String(s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function slides(){
  const out = [];
  // 封面
  out.push(`<section class="slide hero" id="s0">
    <h2>今天的主线</h2>
    <p>${esc(DATA.intro)}</p>
    <h2>共 ${DATA.items.length} 条</h2>
    <ul class="toc">${DATA.items.map((it,n)=>
      `<li><b>${String(n+1).padStart(2,'0')}</b><span>${esc(it.title)}</span></li>`).join('')}</ul>
  </section>`);
  // 每一条
  DATA.items.forEach((it, n) => {
    out.push(`<section class="slide" id="s${n+1}">
      <div class="tags">${(it.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
      <h1>${esc(it.title)}</h1>
      <div class="block"><div class="label">讲了什么</div><div class="text">${esc(it.summary)}</div></div>
      ${it.so_what ? `<div class="block"><div class="label">为什么值得看</div><div class="text hl">${esc(it.so_what)}</div></div>` : ''}
      ${it.how_to_use ? `<div class="block"><div class="label">可以怎么用</div><div class="text">${esc(it.how_to_use)}</div></div>` : ''}
      <div class="block"><a class="src" href="${esc(it.url)}" target="_blank" rel="noopener">读原文 →</a>
        <span class="srcname">${esc(it.source||'')}</span></div>
    </section>`);
  });
  // 收尾
  out.push(`<section class="slide hero" id="s${DATA.items.length+1}">
    <h2>今天花 10 分钟</h2>
    <div class="task"><div class="label">动手</div><div class="text">${esc(DATA.action||'')}</div></div>
    ${DATA.watch ? `<div class="task"><div class="label" style="color:#7aa9ff">值得盯的一条线</div><div class="text">${esc(DATA.watch)}</div></div>` : ''}
    <p style="font-size:14px;color:#8b94a7;margin-top:18px">${esc(DATA.sources_note||'')}</p>
  </section>`);
  return out;
}

const SLIDES = slides();
document.getElementById('main').innerHTML = SLIDES.join('');
document.getElementById('tot').textContent = SLIDES.length;

function render(){
  document.querySelectorAll('.slide').forEach((s,n)=>s.classList.toggle('on', n===i));
  document.getElementById('cur').textContent = i+1;
  document.getElementById('fill').style.width = ((i+1)/SLIDES.length*100) + '%';
  document.getElementById('prev').disabled = i===0;
  const nx = document.getElementById('next');
  nx.textContent = i === SLIDES.length-1 ? '✓ 今天学完了' : (i===0 ? '开始 →' : '下一条 →');
  nx.classList.toggle('done', i === SLIDES.length-1);
  window.scrollTo({top:0, behavior:'smooth'});
  try{localStorage.setItem(STORE, i)}catch(e){}
  try{history.replaceState(null,'','#s'+i)}catch(e){}
}

function go(n){
  if(n<0||n>=SLIDES.length) return;
  i=n; render();
}
document.getElementById('next').onclick = ()=> i===SLIDES.length-1 ? render() : go(i+1);
document.getElementById('prev').onclick = ()=> go(i-1);
document.addEventListener('keydown', e=>{
  if(e.key==='ArrowRight'||e.key===' ') {e.preventDefault(); go(i+1);}
  if(e.key==='ArrowLeft'){e.preventDefault(); go(i-1);}
});

let sx=0, sy=0;
document.addEventListener('touchstart', e=>{sx=e.touches[0].clientX; sy=e.touches[0].clientY;},{passive:true});
document.addEventListener('touchend', e=>{
  const dx=e.changedTouches[0].clientX-sx, dy=e.changedTouches[0].clientY-sy;
  if(Math.abs(dx)>60 && Math.abs(dx)>Math.abs(dy)*1.6){ dx<0 ? go(i+1) : go(i-1); }
},{passive:true});

const m = location.hash.match(/^#s([0-9]+)$/);
if(m){ const h = +m[1]; if(h>=0 && h<SLIDES.length) i = h; }
else { try{ const saved = +localStorage.getItem(STORE); if(!isNaN(saved) && saved>0 && saved<SLIDES.length) i = saved; }catch(e0){} }
render();
</script>
</body>
</html>
"""


def build(date: str) -> Path:
    p = DIGESTS / f"{date}.json"
    if not p.exists():
        sys.exit(f"❌ 找不到 {p}，先跑 summarize.py")
    d = json.loads(p.read_text(encoding="utf-8"))

    dt = datetime.strptime(date, "%Y-%m-%d")
    html = (TEMPLATE
            .replace("__DATA__", json.dumps(d, ensure_ascii=False))
            .replace("__DATE_LABEL__", f"{dt.month}月{dt.day}日")
            .replace("__WEEKDAY__", WEEKDAY[dt.weekday()])
            .replace("__TOTAL__", str(len(d["items"]) + 2)))

    out = DIGESTS / f"{date}.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    out = build(args.date)
    kb = out.stat().st_size / 1024
    print(f"✅ 已生成 {out.relative_to(ROOT)}（{kb:.1f} KB，单文件、无外部依赖）")
    if args.open:
        subprocess.run(["open", str(out)])


if __name__ == "__main__":
    main()

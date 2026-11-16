# Helper script to update index.html with CapCut suite
import os

target_path = r'c:\attiq\clipping software\clipforge\clipforge_web\static\index.html'

with open(target_path, 'r', encoding='utf-8') as f:
    text = f.read()

start_marker = 'function buildEditor(){'
end_marker = 'function sizePhone(){'

idx1 = text.find(start_marker)
idx2 = text.find(end_marker)

assert idx1 != -1, "start_marker not found"
assert idx2 != -1, "end_marker not found"
assert idx1 < idx2, "markers out of order"

replacement = """function buildEditor(){
  const c=S.clip,el=$('#editor');
  el.innerHTML=`<div class="ed"><div class="edbody stack">
   <div class="row"><h2 style="flex:1">CapCut Editor</h2><button id="close" class="ghost" aria-label="Close editor">✕</button></div>
   <div class="phone" id="phone">
     <video id="pv" playsinline preload="auto" muted></video>
     <canvas id="stackcv" width="270" height="480" hidden></canvas>
     <div id="bannerBox" class="bannerBox" hidden></div>
     <div id="cap"></div>
     <div class="facehint" id="facehint" hidden></div>
   </div>
   <div class="row"><button id="play">Play</button><label style="margin:0" class="fit"><input type="checkbox" id="loop" checked> Loop</label><label style="margin:0" class="fit"><input type="checkbox" id="snd"> Sound</label></div>

   <!-- CapCut 5 Tabs -->
   <div class="capcut-tabs" id="edTabs">
     <button class="cptab on" data-tab="cam">🎛️ Streamer Cam</button>
     <button class="cptab" data-tab="banner">🏷️ Hook Text</button>
     <button class="cptab" data-tab="captions">💬 Captions</button>
     <button class="cptab" data-tab="audio">🎵 Audio & SFX</button>
     <button class="cptab" data-tab="trim">✂️ Trim & Format</button>
   </div>

   <!-- Panel 1: Streamer Cam -->
   <div class="cptab-panel on" id="panel-cam">
     <div><label>Streamer Placement</label>
       <div class="seg" id="camPos">
         <button data-pos="top">⬆️ Top (Dual-Cam 40/60)</button>
         <button data-pos="bottom">⬇️ Bottom (Gameplay on top)</button>
         <button data-pos="pip_bottom">🎯 Floating Lower (Speed Style)</button>
         <button data-pos="pip_top">🎯 Floating Upper</button>
       </div>
     </div>
     <div><label>Cam Frame Shape</label>
       <div class="seg" id="camShape">
         <button data-shape="rect">⬛ Rectangle Frame</button>
         <button data-shape="circle">⭕ Circle Frame</button>
       </div>
     </div>
     <div>
       <label>Streamer Zoom: <b id="zoomVal">${Math.round((c.cam_zoom || 1.0) * 100)}%</b></label>
       <input id="camZoom" type="range" min="0.5" max="2.5" step="0.05" value="${c.cam_zoom || 1.0}" aria-label="Streamer Cam Zoom">
       <div class="row muted small"><span>0.5x Wide</span><span style="flex:1;text-align:center">1.0x Normal</span><span>2.5x Close-Up</span></div>
     </div>
     <div>
       <label>Gameplay Horizontal Pan</label>
       <input id="cx" type="range" min="0" max="1" step="0.01" value="${c.crop_x}" aria-label="Crop position">
     </div>
     <div class="row" style="margin-top:4px">
       <button id="camEdit" class="fit">🎯 Adjust facecam bounding box</button>
     </div>
     <div>
       <label class="muted small">Framing Engine</label>
       <div class="seg" id="layout">
         <button data-l="stack">🎮 Dual-Cam (2 Screens)</button>
         <button data-l="pip">🎮 PiP Overlay</button>
         <button data-l="follow">Follow Face</button>
         <button data-l="crop">Center Crop</button>
         <button data-l="blur">Blurred Fit</button>
       </div>
       <p class="muted small" style="margin:4px 0 0" id="layoutDesc"><b>Dual-Cam layout:</b> Splits into 2 screens stacked vertically. Top captures streamer reaction, bottom captures gameplay.</p>
     </div>
   </div>

   <!-- Panel 2: Hook Text -->
   <div class="cptab-panel" id="panel-banner">
     <div>
       <label for="bannerText">Hook / Viral Headline Text (Top of Clip)</label>
       <input id="bannerText" placeholder="e.g. One of the peak streams of his career.... 😂💀" value="${esc(c.banner_text || '')}">
       <div class="preset-chips" id="presetChips">
         <button data-txt="One of the peak streams of his career.... 😂💀">Peak stream 😂💀</button>
         <button data-txt="WAIT TILL THE END 😱🔥">WAIT TILL THE END 😱</button>
         <button data-txt="SPEED COULD NOT BELIEVE THIS 😭">SPEED CAN'T BELIEVE 😭</button>
         <button data-txt="BRO DID NOT JUST DO THAT 💀">BRO DID NOT 💀</button>
         <button data-txt="WATCH TILL THE VERY END ⚠️">WATCH TILL END ⚠️</button>
       </div>
     </div>
     <div>
       <label>Banner Card Style</label>
       <div class="seg" id="bannerStyle">
         <button data-bs="white_box">📄 White Card (Black Text)</button>
         <button data-bs="dark_box">⬛ Dark Box (White Text)</button>
         <button data-bs="neon">⚡ Neon Glow</button>
         <button data-bs="none">🚫 Hidden / Off</button>
       </div>
       <p class="muted small" style="margin:4px 0 0">Viral headline cards are displayed at the top of the video throughout the clip, just like viral TikTok/Reels edits.</p>
     </div>
   </div>

   <!-- Panel 3: Captions -->
   <div class="cptab-panel" id="panel-captions">
     <div><label for="title">Clip Title (Internal)</label><input id="title" value="${esc(c.title)}"></div>
     <div><label>Caption Style Preset</label><div class="styles" id="tpls"></div>
       <div class="row" style="margin-top:8px;gap:12px;flex-wrap:wrap">
         <label style="margin:0" class="fit"><input type="checkbox" id="capon" ${c.captions?'checked':''}> Burn captions</label>
         <label style="margin:0" class="fit"><input type="checkbox" id="hookzoom" ${c.hook_zoom!==0?'checked':''}> ⚡ 3s Hook Zoom</label>
         <label style="margin:0" class="fit"><input type="checkbox" id="censor" ${c.censor?'checked':''}> 🤬 Censor swear words</label>
       </div>
     </div>
     <hr><h3 style="margin:4px 0">Word-by-word Subtitles</h3>
     <p class="muted small" style="margin:2px 0 6px">Fix any word. Timing stays with the words you keep.</p>
     <div id="cues"></div>
   </div>

   <!-- Panel 4: Audio & SFX -->
   <div class="cptab-panel" id="panel-audio">
     <div class="row">
       <div><label for="music">Music</label><select id="music">${optList(S.audio.music,c.music,'None')}</select></div>
       <div><label for="sfx1">Intro Hook SFX</label><select id="sfx1">${optList(S.audio.sfx,c.sfx_intro,'None')}</select></div>
       <div><label for="sfx2">Peak SFX (Deep 808/Boom)</label><select id="sfx2">${optList(S.audio.sfx,c.sfx_peak,'Auto Deep Drop')}</select></div>
     </div>
     <div>
       <label>Sound effects</label>
       <div class="row">
         <button id="sfxAuto" class="primary fit">Auto-add effects</button>
         <select id="sfxPick" aria-label="Effect to add">${optList(S.audio.sfx,'whoosh.wav')}</select>
         <button id="sfxAdd" class="fit">Add at playhead</button>
       </div>
       <p class="muted small" style="margin:6px 0 0">Auto-add puts a whoosh at the start, a riser and boom on the big moment and pops on reaction words. Turn on Sound to hear them in the preview.</p>
       <div id="sfxList"></div>
     </div>
   </div>

   <!-- Panel 5: Trim & Format -->
   <div class="cptab-panel" id="panel-trim">
     <div><label>Trim: drag the ends, click to jump</label>
       <div class="trim"><div class="trk" id="trk"><svg id="twave" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"></svg>
         <div class="sel" id="tsel"><i data-h="s" title="Drag to set the start"></i><i data-h="e" title="Drag to set the end"></i></div><div id="tsfx"></div><div class="ph" id="tph"></div></div>
         <div class="row muted small" style="margin-top:3px"><span id="tlo"></span><span id="tlen" style="text-align:center"></span><span id="thi" style="text-align:right"></span></div></div>
     </div>
     <div class="tm">
       <div><label for="st">Start (s)</label><input id="st" type="number" step="0.1" value="${c.start.toFixed(1)}"><div class="nudge"><button data-n="st:-1">−1s</button><button data-n="st:-.5">−.5</button><button data-n="st:.5">+.5</button><button data-n="st:1">+1s</button><button id="stNow">Playhead</button></div></div>
       <div><label for="en">End (s)</label><input id="en" type="number" step="0.1" value="${c.end.toFixed(1)}"><div class="nudge"><button data-n="en:-1">−1s</button><button data-n="en:-.5">−.5</button><button data-n="en:.5">+.5</button><button data-n="en:1">+1s</button><button id="enNow">Playhead</button></div></div>
     </div>
     <p class="muted small" id="dur" style="margin:0"></p>
     <div><label>Aspect ratio</label>
       <div class="seg" id="aspectRatio">
         <button data-aspect="9:16" class="on">📱 9:16 Vertical (Shorts/TikTok/Reels)</button>
         <button data-aspect="1:1">⬛ 1:1 Square</button>
         <button data-aspect="16:9">🖥️ 16:9 Landscape</button>
       </div>
     </div>
     <div><label>Quality Resolution</label>
       <div class="seg" id="res"><button data-r="1080">1080p</button><button data-r="1440">2K</button><button data-r="2160">4K</button></div>
     </div>
     <div><label>Why this clip</label><ul class="why">${(c.reasons||[]).map(r=>`<li>${esc(r)}</li>`).join('')}</ul></div>
   </div>

  </div><div class="edfoot"><button id="reject" class="ghost">Reject</button><button id="approve" class="primary"><i class="fill"></i><span></span></button></div></div>`;
  $('#tpls').innerHTML=Object.entries(S.tpl).map(([n,t])=>`<button class="style ${n===c.template?'on':''}" data-t="${n}"><span class="s" style="color:${t.active};text-shadow:${t.box?'none':tplShadow(t,.08)};${t.box?'background:#000b;border-radius:4px;padding:0 4px':''}">${t.upper?'WORD':'Word'}</span><small>${n.replace(/_/g,' ')}</small></button>`).join('');
  const v=$('#pv');v.src='/api/clips/'+c.id+'/source#t='+c.start;
  v.addEventListener('loadedmetadata',()=>{v.currentTime=S.clip.start;drawCaption();drawBanner();applyLayout();drawTrim()});
  v.addEventListener('timeupdate',onTime);v.addEventListener('seeked',()=>{drawCaption();drawBanner();applyLayout()});
  v.addEventListener('play',()=>{$('#play').textContent='Pause';(function loop(){drawCaption();drawBanner();applyLayout();drawPh();sfxTick();if(!v.paused)requestAnimationFrame(loop)})()});
  v.addEventListener('pause',()=>$('#play').textContent='Play');
  sizePhone();markSeg();drawCues();updateApproveUI();updDur();drawTrim();trimEvents();drawBanner();
  $('#close').onclick=()=>{S.cid=null;S.clip=null;showEditor(false);drawCands();drawMap()};
  $('#play').onclick=playClip;$('#snd').onchange=e=>v.muted=!e.target.checked;
  $('#approve').onclick=guard(()=>approve(S.cid));
  $('#reject').onclick=guard(()=>save({status:'rejected'}).then(()=>toast('Rejected.')));
  $('#title').onchange=guard(e=>save({title:e.target.value}));
  $('#st').onchange=guard(()=>setTimes(+$('#st').value,+$('#en').value));$('#en').onchange=guard(()=>setTimes(+$('#st').value,+$('#en').value));
  $('#stNow').onclick=guard(()=>setTimes(v.currentTime,S.clip.end));$('#enNow').onclick=guard(()=>setTimes(S.clip.start,v.currentTime));
  el.querySelectorAll('[data-n]').forEach(b=>b.onclick=guard(()=>{const [k,d]=b.dataset.n.split(':');k==='st'?setTimes(S.clip.start+ +d,S.clip.end):setTimes(S.clip.start,S.clip.end+ +d)}));

  // CapCut Tab Switcher
  $('#edTabs').onclick=e=>{
    const b=e.target.closest('.cptab');if(!b)return;
    const tab=b.dataset.tab;
    $('#edTabs').querySelectorAll('.cptab').forEach(t=>t.classList.toggle('on',t===b));
    el.querySelectorAll('.cptab-panel').forEach(p=>p.classList.toggle('on',p.id==='panel-'+tab));
  };

  // Streamer Placement
  $('#camPos').onclick=guard(async e=>{
    const b=e.target.closest('[data-pos]');if(!b)return;
    const pos=b.dataset.pos;
    const layout = pos.startsWith('pip') ? 'pip' : 'stack';
    await save({cam_pos:pos, layout:layout});
    markSeg();applyLayout();
  });

  // Streamer Shape
  $('#camShape').onclick=guard(async e=>{
    const b=e.target.closest('[data-shape]');if(!b)return;
    await save({cam_shape:b.dataset.shape});
    markSeg();applyLayout();
  });

  // Streamer Zoom
  const zoomInp=$('#camZoom'), zoomVal=$('#zoomVal');
  if(zoomInp){
    zoomInp.oninput=e=>{
      S.clip.cam_zoom = +e.target.value;
      if(zoomVal) zoomVal.textContent = Math.round(S.clip.cam_zoom * 100) + '%';
      applyLayout();
    };
    zoomInp.onchange=guard(e=>save({cam_zoom:+e.target.value}));
  }

  // Hook Text & Styles
  $('#bannerText').oninput=e=>{
    S.clip.banner_text=e.target.value;
    drawBanner();
  };
  $('#bannerText').onchange=guard(e=>save({banner_text:e.target.value}));
  $('#presetChips').onclick=guard(async e=>{
    const b=e.target.closest('button');if(!b)return;
    const txt=b.dataset.txt;
    $('#bannerText').value=txt;
    S.clip.banner_text=txt;
    drawBanner();
    await save({banner_text:txt});
  });
  $('#bannerStyle').onclick=guard(async e=>{
    const b=e.target.closest('[data-bs]');if(!b)return;
    await save({banner_style:b.dataset.bs});
    markSeg();drawBanner();
  });

  $('#layout').onclick=guard(async e=>{
    const b=e.target.closest('[data-l]');if(!b)return;
    await save({layout:b.dataset.l});
    $('#cx').hidden=!['crop','stack','pip'].includes(S.clip.layout);
    if($('#camEdit'))$('#camEdit').hidden=!['stack','pip'].includes(S.clip.layout);
    const ld=$('#layoutDesc');
    if(ld){
      ld.innerHTML=b.dataset.l==='stack'?'<b>Dual-Cam layout:</b> Splits into 2 screens stacked vertically. Top screen captures streamer reaction, bottom captures gameplay.':(b.dataset.l==='pip'?'<b>PiP layout:</b> Full gameplay screen with floating streamer reaction webcam.':'<b>Standard framing:</b> Single focused screen.');
    }
    markSeg();loadFraming();
  });
  if($('#camEdit'))$('#camEdit').onclick=camEditor;
  $('#aspectRatio').onclick=e=>{
    const b=e.target.closest('[data-aspect]');if(!b)return;
    $('#aspectRatio').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
    const asp=b.dataset.aspect,ph=$('#phone');
    if(asp==='1:1')ph.style.aspectRatio='1/1';
    else if(asp==='16:9')ph.style.aspectRatio='16/9';
    else ph.style.aspectRatio='9/16';
    toast(`Aspect ratio set to ${asp}.`);
  };
  $('#res').onclick=guard(async e=>{const b=e.target.closest('[data-r]');if(!b)return;await save({res:+b.dataset.r});markSeg()});
  $('#cx').oninput=e=>{S.clip.crop_x=+e.target.value;applyLayout()};$('#cx').onchange=guard(e=>save({crop_x:+e.target.value}));
  $('#tpls').onclick=guard(async e=>{const b=e.target.closest('[data-t]');if(!b)return;await save({template:b.dataset.t});el.querySelectorAll('#tpls .style').forEach(x=>x.classList.toggle('on',x===b));drawCaption()});
  $('#capon').onchange=guard(e=>save({captions:e.target.checked?1:0}).then(drawCaption));
  $('#music').onchange=guard(e=>save({music:e.target.value}));
  $('#sfxAuto').onclick=guard(async()=>{const c=await send('POST','/api/clips/'+S.cid+'/sfx/auto');Object.assign(S.clip,c);drawSfx();await loadClips();updateApproveUI();
    toast(c.sfx.length?`Added ${c.sfx.length} effects.`:'No effects found in the library.')});
  $('#sfxAdd').onclick=guard(()=>saveSfx([...S.clip.sfx,{f:$('#sfxPick').value,t:+$('#pv').currentTime.toFixed(2),v:.7}]));
  $('#sfxList').onchange=guard(e=>{const i=+e.target.closest('[data-i]').dataset.i,l=S.clip.sfx.map(x=>({...x}));
    if(e.target.dataset.k==='f')l[i].f=e.target.value;else if(e.target.dataset.k==='t')l[i].t=S.clip.start+(+e.target.value);else l[i].v=+e.target.value;return saveSfx(l)});
  $('#sfxList').onclick=guard(e=>{const b=e.target.closest('button');if(!b)return;const i=+b.closest('[data-i]').dataset.i,x=S.clip.sfx[i];
    if(b.dataset.a==='del')return saveSfx(S.clip.sfx.filter((_,j)=>j!==i));
    if(b.dataset.a==='play')playSfx(x);if(b.dataset.a==='go'){$('#pv').currentTime=x.t;drawPh()}});
  drawSfx();$('#sfx1').onchange=guard(e=>save({sfx_intro:e.target.value}));
  if($('#sfx2'))$('#sfx2').onchange=guard(e=>save({sfx_peak:e.target.value}));
  if($('#hookzoom'))$('#hookzoom').onchange=guard(e=>save({hook_zoom:e.target.checked?1:0}));
  if($('#censor'))$('#censor').onchange=guard(e=>save({censor:e.target.checked?1:0}));
}
function drawBanner(){
  const box=$('#bannerBox'),c=S.clip;
  if(!box||!c)return;
  const txt=(c.banner_text||'').trim();
  const st=c.banner_style||'white_box';
  if(!txt||st==='none'){box.hidden=true;box.innerHTML='';return}
  box.hidden=false;
  const cls=st==='dark_box'?'card_dark':(st==='neon'?'card_neon':'card_white');
  box.innerHTML=`<div class="${cls}">${esc(txt)}</div>`;
}
function markSeg(){
  const c=S.clip;if(!c)return;
  $('#layout').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.l===c.layout));
  $('#res').querySelectorAll('button').forEach(b=>b.classList.toggle('on',+b.dataset.r===c.res));
  if($('#camPos'))$('#camPos').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.pos===(c.cam_pos||'top')));
  if($('#camShape'))$('#camShape').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.shape===(c.cam_shape||'rect')));
  if($('#bannerStyle'))$('#bannerStyle').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.bs===(c.banner_style||'white_box')));
}
function updDur(){const c=S.clip;$('#dur').textContent=`Clip length ${(c.end-c.start).toFixed(1)}s.`+(c.stream_offset?` In the stream it starts at ${fmtLong(c.start+c.stream_offset)}; start and end here count inside the saved excerpt.`:' Captions exist only where speech was heard, about 5 seconds either side of the picked moment.')}
async function saveSfx(list){await save({sfx:list});drawSfx()}
function playSfx(x){try{const a=new Audio('/api/audio/sfx/'+encodeURIComponent(x.f));a.volume=Math.min(1,x.v);a.play()}catch{}}
function drawSfx(){const box=$('#sfxList');if(!box||!S.clip)return;const c=S.clip,l=c.sfx||[];
  box.innerHTML=l.map((x,i)=>{const out=x.t<c.start||x.t>=c.end;return `<div class="sfxi${out?' out':''}" data-i="${i}" ${out?'title="Outside the clip, so it is not used"':''}>
    <button data-a="play" title="Listen" aria-label="Listen">▶</button><select data-k="f" aria-label="Effect">${optList(S.audio.sfx,x.f)}</select>
    <input data-k="t" type="number" step="0.1" value="${(x.t-c.start).toFixed(1)}" aria-label="Seconds into the clip" title="Seconds into the clip">
    <input data-k="v" type="range" min="0" max="1.5" step="0.05" value="${x.v}" aria-label="Volume" title="Volume">
    <button data-a="go" title="Jump here" aria-label="Jump here">⌖</button><button data-a="del" title="Remove" aria-label="Remove">✕</button></div>`}).join('');
  drawTrim()}
function sfxTick(){const v=$('#pv');if(!v||!S.clip)return;const t=v.currentTime,p=S.lastT??t;S.lastT=t;
  if(v.paused||v.muted||t<p||t-p>.5)return;(S.clip.sfx||[]).forEach(x=>{if(x.t>p&&x.t<=t)playSfx(x)})}
const T={lo:0,hi:1,drag:false};
function tlTotal(){const v=$('#pv');return v&&isFinite(v.duration)&&v.duration>0?v.duration:(S.video&&S.video.duration)||S.clip.end+30}
function drawTrim(s,e){
  if(!$('#trk')||!S.clip)return;s=s??S.clip.start;e=e??S.clip.end;
  if(!T.drag){const pad=Math.max(10,(S.clip.end-S.clip.start)*.6);T.lo=Math.max(0,S.clip.start-pad);T.hi=Math.max(T.lo+1,Math.min(tlTotal(),S.clip.end+pad))}
  const X=t=>(t-T.lo)/(T.hi-T.lo)*100;
  $('#tsel').style.left=X(s)+'%';$('#tsel').style.width=Math.max(0,X(e)-X(s))+'%';
  $('#tlo').textContent=fmtLong(T.lo);$('#thi').textContent=fmtLong(T.hi);$('#tlen').textContent=(e-s).toFixed(1)+'s';
  const c=S.video&&S.video.curve,svg=$('#twave');
  if(!c||S.clip.stream_offset)svg.innerHTML='';
  else{const n=c.v.length,dur=S.video.duration||1,p=[];
    for(let i=0;i<=80;i++){const t=T.lo+(T.hi-T.lo)*i/80,y=c.v[Math.min(n-1,Math.floor(t/dur*n))]||0;p.push((i/80*100).toFixed(2)+','+(30-y*26).toFixed(2))}
    svg.innerHTML=`<path d="M0,30 L${p.join(' L')} L100,30 Z" fill="#8c9bff40"/>`}
  $('#tsfx').innerHTML=(S.clip.sfx||[]).filter(x=>x.t>=T.lo&&x.t<=T.hi).map(x=>`<i style="left:${X(x.t)}%" title="${esc(x.f)}"></i>`).join('');
  drawPh()}
function drawPh(){const v=$('#pv'),p=$('#tph');if(!v||!p)return;const t=v.currentTime;p.hidden=t<T.lo||t>T.hi;p.style.left=(t-T.lo)/(T.hi-T.lo)*100+'%'}
function trimEvents(){
  const trk=$('#trk'),v=$('#pv');
  trk.onpointerdown=e=>{
    const r=trk.getBoundingClientRect(),at=x=>T.lo+(T.hi-T.lo)*Math.min(1,Math.max(0,(x-r.left)/r.width)),h=e.target.dataset.h;
    if(!h){v.currentTime=at(e.clientX);drawPh();return}
    e.preventDefault();trk.setPointerCapture(e.pointerId);T.drag=true;let s=S.clip.start,en=S.clip.end;
    trk.onpointermove=m=>{const t=at(m.clientX);if(h==='s')s=Math.min(t,en-3);else en=Math.max(t,s+3);
      drawTrim(s,en);$('#st').value=s.toFixed(1);$('#en').value=en.toFixed(1);v.currentTime=h==='s'?s:en};
    trk.onpointerup=trk.onpointercancel=guard(async()=>{trk.onpointermove=trk.onpointerup=trk.onpointercancel=null;T.drag=false;
      if(Math.abs(s-S.clip.start)>.05||Math.abs(en-S.clip.end)>.05)await setTimes(+s.toFixed(2),+en.toFixed(2));else drawTrim()})};
}
async function setTimes(s,e){await save({start:s,end:e});$('#st').value=S.clip.start.toFixed(1);$('#en').value=S.clip.end.toFixed(1);drawTrim();
  await loadCues();drawCues();updDur();const v=$('#pv');v.currentTime=S.clip.start;drawCaption();drawBanner();loadFraming()}
function posAt(t){const p=S.framing&&S.framing.pts;if(!p||!p.length)return null;let lo=0,hi=p.length-1;
  while(hi-lo>1){const m=(lo+hi)>>1;p[m][0]<=t?lo=m:hi=m}
  const a=p[lo],b=p[hi];if(t<=a[0])return a[1];if(t>=b[0])return b[1];return a[1]+(b[1]-a[1])*(t-a[0])/Math.max(b[0]-a[0],1e-6)}
function drawStack(v,f,c){
  const cv=$('#stackcv'),g=cv.getContext('2d'),W=cv.width,H=cv.height;
  if(!v.videoWidth)return;
  const k=v.videoWidth/f.w;
  let camBox=(f.pip&&f.box ? f.box : f.cam).map(n=>n*k);
  let [cx,cy,cw,ch]=camBox;

  // Center-anchored streamer cam zoom
  const zoom = Math.max(0.2, Math.min(3.0, c.cam_zoom || 1.0));
  const boxCenterX = cx + cw / 2;
  const boxCenterY = cy + ch / 2;
  const zw = Math.min(v.videoWidth, cw / zoom);
  const zh = Math.min(v.videoHeight, ch / zoom);
  const zx = Math.max(0, Math.min(v.videoWidth - zw, boxCenterX - zw / 2));
  const zy = Math.max(0, Math.min(v.videoHeight - zh, boxCenterY - zh / 2));

  const isPip = c.layout === 'pip' || (c.cam_pos && c.cam_pos.startsWith('pip'));
  const isBottom = c.cam_pos === 'bottom';
  const shape = c.cam_shape || 'rect';
  const vh = v.videoHeight;

  if(isPip){
    // Full screen gameplay
    const gw = Math.min(v.videoWidth, vh * 9 / 16);
    const gx = (v.videoWidth - gw) * (c.crop_x ?? 0.5);
    g.drawImage(v, gx, 0, gw, vh, 0, 0, W, H);

    // Floating overlay cam (Speed reaction cutout style)
    const pw = Math.round(W * (shape === 'circle' ? 0.44 : (f.size || 0.46)));
    const ph = shape === 'circle' ? pw : Math.round(pw * (ch / cw));
    let px = Math.round((W - pw) / 2);
    let py = Math.round(H * 0.65);
    if(c.cam_pos === 'pip_top') py = Math.round(H * 0.12);
    else if(c.cam_pos === 'pip_center') py = Math.round((H - ph) / 2);
    if(c.cam_pos_x != null && c.cam_pos_y != null){
      px = Math.round((W - pw) * c.cam_pos_x);
      py = Math.round((H - ph) * c.cam_pos_y);
    }

    g.save();
    if(shape === 'circle'){
      g.beginPath();
      g.arc(px + pw/2, py + ph/2, Math.min(pw, ph)/2, 0, Math.PI * 2);
      g.clip();
    }
    g.drawImage(v, zx, zy, zw, zh, px, py, pw, ph);
    g.restore();

    g.beginPath();
    if(shape === 'circle'){
      g.arc(px + pw/2, py + ph/2, Math.min(pw, ph)/2, 0, Math.PI * 2);
    } else {
      g.rect(px, py, pw, ph);
    }
    g.strokeStyle = '#ffffff80';
    g.lineWidth = 2;
    g.stroke();
    return;
  }

  // Dual-cam stacked
  if(isBottom){
    // Gameplay on top (60%), streamer bottom (40%)
    const gh = Math.round(H * 0.6), ch_dst = H - gh;
    const gw = Math.min(v.videoWidth, vh * W / gh), gx = (v.videoWidth - gw) * (c.crop_x ?? 0.5);
    g.drawImage(v, gx, 0, gw, vh, 0, 0, W, gh);

    g.save();
    if(shape === 'circle'){
      g.fillStyle = '#0f1117';
      g.fillRect(0, gh, W, ch_dst);
      const diam = Math.min(W * 0.85, ch_dst * 0.95);
      const cx_dst = (W - diam) / 2, cy_dst = gh + (ch_dst - diam) / 2;
      g.beginPath();
      g.arc(cx_dst + diam/2, cy_dst + diam/2, diam/2, 0, Math.PI * 2);
      g.clip();
      g.drawImage(v, zx, zy, zw, zh, cx_dst, cy_dst, diam, diam);
      g.restore();
      g.beginPath();
      g.arc(cx_dst + diam/2, cy_dst + diam/2, diam/2, 0, Math.PI * 2);
      g.strokeStyle = '#ffffff60';
      g.lineWidth = 2;
      g.stroke();
    } else {
      g.drawImage(v, zx, zy, zw, zh, 0, gh, W, ch_dst);
      g.restore();
    }
  } else {
    // Streamer on top (40%), gameplay below (60%)
    const th = Math.round(H * (f.top || 0.4)), bh = H - th;
    const gw = Math.min(v.videoWidth, vh * W / bh), gx = (v.videoWidth - gw) * (c.crop_x ?? 0.5);
    g.drawImage(v, gx, 0, gw, vh, 0, th, W, bh);

    g.save();
    if(shape === 'circle'){
      g.fillStyle = '#0f1117';
      g.fillRect(0, 0, W, th);
      const diam = Math.min(W * 0.85, th * 0.95);
      const cx_dst = (W - diam) / 2, cy_dst = (th - diam) / 2;
      g.beginPath();
      g.arc(cx_dst + diam/2, cy_dst + diam/2, diam/2, 0, Math.PI * 2);
      g.clip();
      g.drawImage(v, zx, zy, zw, zh, cx_dst, cy_dst, diam, diam);
      g.restore();
      g.beginPath();
      g.arc(cx_dst + diam/2, cy_dst + diam/2, diam/2, 0, Math.PI * 2);
      g.strokeStyle = '#ffffff60';
      g.lineWidth = 2;
      g.stroke();
    } else {
      g.drawImage(v, zx, zy, zw, zh, 0, 0, W, th);
      g.restore();
    }
  }
}
function drawBlur(v,cv){   // like the render: blurred fill behind the whole picture
  const g=cv.getContext('2d'),W=cv.width,H=cv.height,vw=v.videoWidth,vh=v.videoHeight,cw=vh*W/H,h=W*vh/vw;
  g.filter='blur(12px) brightness(.7)';g.drawImage(v,(vw-cw)/2,0,cw,vh,-20,-20,W+40,H+40);g.filter='none';
  g.drawImage(v,0,(H-h)/2,W,h)
}
function applyLayout(){const v=$('#pv');if(!v||!S.clip)return;const c=S.clip,f=S.framing;
  const stack=['stack','pip'].includes(c.layout)&&f&&f.stack&&f.cam,cv=$('#stackcv');
  const blur=v.videoWidth&&(c.layout==='blur'||(['stack','pip'].includes(c.layout)&&f&&f.stack&&!f.cam));
  cv.hidden=!stack&&!blur;v.style.visibility=stack||blur?'hidden':'';
  if(stack)drawStack(v,f,c);else if(blur)drawBlur(v,cv);
  v.style.objectFit=(c.layout==='blur'||(['stack','pip'].includes(c.layout)&&f&&f.stack&&!f.cam))?'contain':'cover';
  let x=.5;if(c.layout==='crop')x=c.crop_x;else if(c.layout==='follow'){const p=posAt(v.currentTime-c.start);x=p==null?.5:p}
  v.style.objectPosition=(x*100)+'% 50%'}
"""

updated_text = text[:idx1] + replacement + text[idx2:]

with open(target_path, 'w', encoding='utf-8') as f:
    f.write(updated_text)

print('Updated index.html successfully! New length:', len(updated_text))


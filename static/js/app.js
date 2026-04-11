// ═══════════ STATE ═══════════
let currentMonth  = '';
let transactions  = [], templates = [];
let monthCounts   = {};
let payeeBadges   = {}, tmplBadges = {};
let balChart      = null;
let chartVisible  = true;
let payeeDefaults = {};

// All-transactions view state
let allTransactions   = [];
let allPayeeBadges    = {};
let editingAllTxnId   = null;

let connModalVisible = false;
let connLostSinceMs  = null;
let connHintTimer    = null;
const API_RETRY_CAP_MS = 8000;

const nativeFetch = window.fetch.bind(window);

// Sort state: bodyId → {col, dir}
let sortState = {};

// Edit marker used only to avoid re-sorting mid-edit.
let editingTxnId  = null;  // txn.id currently open for editing (or null)
let editingTmplId = null;  // tmpl.id currently open for editing (or null)

function valuesEqual(field, a, b){
  if(field==='amount') return Math.abs((parseFloat(a)||0) - (parseFloat(b)||0)) < 0.0001;
  return (a??'') === (b??'');
}

function getTxnById(id){
  return transactions.find(t=>t.id===id) || null;
}

function getTmplById(id){
  return templates.find(t=>t.id===id) || null;
}

function hasActiveEditor(){
  return !!document.querySelector('td.editable input,td.editable select,td.teditable input,td.teditable select');
}

function applyLocalTxnField(id, field, value){
  const i = transactions.findIndex(t=>t.id===id);
  if(i===-1) return;
  transactions[i] = {...transactions[i], [field]: value};
  if(field==='payee' && value) addPayee(value);
  if(field==='category' && value){
    addCat(value);
    if(transactions[i].payee) payeeDefaults[transactions[i].payee] = value;
  }
}

function applyLocalTmplField(id, field, value){
  const i = templates.findIndex(t=>t.id===id);
  if(i===-1) return;
  templates[i] = {...templates[i], [field]: value};
  if(field==='payee' && value) addPayee(value);
  if(field==='category' && value) addCat(value);
}

window.addEventListener('blur', ()=>{ _hideAC(); });

function sleep(ms){
  return new Promise(resolve=>setTimeout(resolve, ms));
}

function nextBackoffMs(attempt){
  const base = 500;
  const exp = Math.min(API_RETRY_CAP_MS, base * (2 ** Math.min(attempt, 6)));
  const jitter = Math.floor(Math.random() * 250);
  return exp + jitter;
}

function showConnModal(){
  if(!connModalVisible){
    document.getElementById('conn-modal').classList.add('open');
    connModalVisible = true;
  }
  if(connLostSinceMs==null){
    connLostSinceMs = Date.now();
    clearTimeout(connHintTimer);
    connHintTimer = setTimeout(()=>{
      if(connModalVisible){
        document.getElementById('conn-modal-extra').style.display='block';
      }
    }, 20000);
  }
}

function hideConnModal(){
  if(!connModalVisible) return;
  document.getElementById('conn-modal').classList.remove('open');
  document.getElementById('conn-modal-extra').style.display='none';
  connModalVisible = false;
  connLostSinceMs = null;
  clearTimeout(connHintTimer);
}

function isRetryableApiFailure(err, responseStatus){
  if(responseStatus!=null) return responseStatus===502 || responseStatus===503 || responseStatus===504;
  return err instanceof TypeError;
}

async function resilientApiFetch(input, init){
  let attempt = 0;
  while(true){
    try{
      const response = await nativeFetch(input, init);
      if(response.status === 401){
        // Session expired or not authenticated — redirect to login
        window.location.href = '/login';
        // Return a never-resolving promise so callers don't continue
        return new Promise(()=>{});
      }
      if(isRetryableApiFailure(null, response.status)){
        showConnModal();
        await sleep(nextBackoffMs(attempt));
        attempt += 1;
        continue;
      }
      hideConnModal();
      return response;
    }catch(err){
      if(!isRetryableApiFailure(err, null)) throw err;
      showConnModal();
      await sleep(nextBackoffMs(attempt));
      attempt += 1;
    }
  }
}

async function doLogout(){
  await nativeFetch('/api/logout', {method:'POST'});
  window.location.href = '/login';
}

window.fetch = function(input, init){
  const url = typeof input==='string' ? input : (input?.url || '');
  if(url.startsWith('/api/')) return resilientApiFetch(input, init);
  return nativeFetch(input, init);
};

// ═══════════ UTILS ═══════════
const fmt = n => {
  if(n==null||isNaN(n)) return '—';
  const abs=Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',');
  return n<0 ? `($${abs})` : `$${abs}`;
};
// HTML accounting cell for transaction amounts (debit=red, credit=green)
function fmtTxnAmt(amount, entryType){
  const abs=parseFloat(amount||0).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',');
  const cls=entryType==='debit'?'cur-neg':'cur-pos';
  return `<span class="cur-cell ${cls}"><span class="cur-sign">$</span><span class="cur-amt">${abs}</span></span>`;
}
// HTML accounting cell for balance values (positive=green, negative=red+parens)
function fmtBal(n){
  if(n==null||isNaN(n)) return '—';
  const abs=Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',');
  const neg=n<0;
  const cls=neg?'cur-neg':'cur-pos';
  const val=neg?`(${abs})`:abs;
  return `<span class="cur-cell ${cls}"><span class="cur-sign">$</span><span class="cur-amt">${val}</span></span>`;
}
function fmtG(n, el) {
  el.textContent=fmt(n); el.className='gval '+(n>=0?'pos':'neg');
}
function toast(msg, type='ok') {
  const d=document.createElement('div'); d.className=`ft ${type}`; d.textContent=msg;
  document.getElementById('ta').appendChild(d); setTimeout(()=>d.remove(),3200);
}
const MONS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// ═══════════ CATEGORIES & PAYEES ═══════════
let categories = new Set();
let payees     = new Set();

function updateDL() {
  const dl=document.getElementById('cat-list'); if(!dl) return; dl.innerHTML='';
  [...categories].sort().forEach(c=>{const o=document.createElement('option');o.value=c;dl.appendChild(o);});
}
function addCat(c){ if(c&&!categories.has(c)){categories.add(c);updateDL();} }
function addPayee(p){ if(p&&!payees.has(p)) payees.add(p); }

// ═══════════ CUSTOM AUTOCOMPLETE ═══════════
let _acDrop=null, _acOnPick=null, _acActiveIdx=-1;
let _acInput=null, _acScrollCleanup=null;

function _acPosition(input){
  if(!_acDrop) return;
  const r=input.getBoundingClientRect();
  _acDrop.style.left=r.left+'px';
  _acDrop.style.top=(r.bottom+2)+'px';
}

function _hideAC(){
  if(_acDrop){_acDrop.remove();_acDrop=null;}
  if(_acScrollCleanup){_acScrollCleanup();_acScrollCleanup=null;}
  _acOnPick=null; _acActiveIdx=-1; _acInput=null;
}

function _acItems(){
  if(!_acDrop) return [];
  return Array.from(_acDrop.querySelectorAll('.ac-item'));
}

function _acSetActive(idx){
  const items=_acItems();
  if(!items.length){_acActiveIdx=-1;return;}
  const clamped=Math.max(0,Math.min(idx,items.length-1));
  items.forEach((it,i)=>it.classList.toggle('active',i===clamped));
  _acActiveIdx=clamped;
  items[clamped].scrollIntoView({block:'nearest'});
}

function _acMove(delta){
  const items=_acItems();
  if(!items.length) return false;
  const start=_acActiveIdx<0 ? (delta>0 ? -1 : items.length) : _acActiveIdx;
  _acSetActive(start+delta);
  return true;
}

function _acPickFromInput(input){
  if(!_acDrop || !_acOnPick) return false;
  const items=_acItems();
  if(!items.length) return false;
  const idx=_acActiveIdx>=0 ? _acActiveIdx : 0;
  const m=(items[idx].textContent||'').trim();
  input.value=m;
  const cb=_acOnPick;
  _hideAC();
  cb(m);
  return true;
}

function _showAC(input, opts, onPick, onTab){
  _hideAC();
  _acOnPick=onPick; _acInput=input;
  const val=input.value.toLowerCase();
  const matches=val ? opts.filter(o=>o.toLowerCase().includes(val)) : opts;
  if(!matches.length) return;
  const dd=document.createElement('div'); dd.className='ac-dropdown';
  const r=input.getBoundingClientRect();
  dd.style.minWidth=Math.max(r.width,150)+'px';
  matches.slice(0,12).forEach((m, idx)=>{
    const item=document.createElement('div'); item.className='ac-item';
    item.textContent=m;
    item.onmouseenter=()=>_acSetActive(idx);
    // preventDefault keeps focus on the input so blur doesn't fire before pick
    item.onmousedown=e=>{ e.preventDefault(); input.value=m; onPick(m); _hideAC(); };
    dd.appendChild(item);
  });
  document.body.appendChild(dd); _acDrop=dd;
  _acPosition(input); // set initial position after appending
  // Reposition whenever anything in the page scrolls
  const onScroll=()=>_acPosition(input);
  document.addEventListener('scroll', onScroll, {capture:true, passive:true});
  _acScrollCleanup=()=>document.removeEventListener('scroll', onScroll, {capture:true});
}

function acBind(input, getOpts, onPick, onTab){
  input.addEventListener('focus', ()=>_showAC(input,getOpts(),onPick,onTab));
  input.addEventListener('input', ()=>_showAC(input,getOpts(),onPick,onTab));
  // Hide dropdown whenever this input loses focus
  input.addEventListener('blur', ()=>_hideAC());
  // Arrow keys navigate the open dropdown without stealing focus from the input
  input.addEventListener('keydown', ev=>{
    if(!_acDrop) return;
    if(ev.key==='ArrowDown'){ ev.preventDefault(); _acMove(1); }
    else if(ev.key==='ArrowUp'){ ev.preventDefault(); _acMove(-1); }
  });
}

async function refreshSuggestions(){
  const [cats,pList]=await Promise.all([
    fetch('/api/categories').then(r=>r.json()).catch(()=>[]),
    fetch('/api/payees').then(r=>r.json()).catch(()=>[]),
  ]);
  categories=new Set(cats.filter(Boolean));
  payees=new Set(pList.filter(Boolean));
  templates.forEach(t=>{if(t.category)categories.add(t.category);if(t.payee)payees.add(t.payee);});
}

function getPayeeDefaultCategory(payee){
  if(!payee) return null;
  const tmplMatch=templates.filter(t=>t.payee===payee&&t.category).sort((a,b)=>b.id-a.id)[0];
  if(tmplMatch) return tmplMatch.category;
  const txnMatch=transactions.filter(t=>t.payee===payee&&t.category).sort((a,b)=>b.id-a.id)[0];
  if(txnMatch) return txnMatch.category;
  return payeeDefaults[payee]||null;
}

// ═══════════ SORT ═══════════
function sortRows(rows, bodyId, defaultCol){
  const ss=sortState[bodyId]||{col:defaultCol||'date',dir:1};
  return [...rows].sort((a,b)=>{
    let av=a[ss.col]??'', bv=b[ss.col]??'';
    if(ss.col==='amount'||ss.col==='day_of_month'){av=parseFloat(av)||0;bv=parseFloat(bv)||0;}
    const cmp=av<bv?-1:av>bv?1:0;
    if(cmp!==0) return cmp*ss.dir;
    // secondary: payee alphabetical
    return (a.payee||'').localeCompare(b.payee||'');
  });
}

function setSort(bodyId, col){
  const cur=sortState[bodyId]||{col,dir:1};
  if(cur.col===col) sortState[bodyId]={col,dir:-cur.dir};
  else sortState[bodyId]={col,dir:1};
  refreshSortIcons(bodyId);
  // Re-render relevant section
  if(bodyId==='income-body') renderSection('income-body',transactions.filter(t=>t.entry_type==='credit'));
  else if(bodyId==='expense-body') renderSection('expense-body',transactions.filter(t=>t.entry_type==='debit'));
  else if(bodyId==='tmpl-income-body') renderTmplSection('tmpl-income-body',templates.filter(t=>t.entry_type==='credit'));
  else if(bodyId==='tmpl-expense-body') renderTmplSection('tmpl-expense-body',templates.filter(t=>t.entry_type==='debit'));
  else if(bodyId==='all-body') renderAllTransactions();
}

function refreshSortIcons(bodyId){
  const ss=sortState[bodyId];
  if(!ss) return;
  document.querySelectorAll(`[data-sort^="${bodyId}:"]`).forEach(th=>{
    const col=th.dataset.sort.split(':')[1];
    // find sort-icon span inside this th
    const icon=th.querySelector('.sort-icon');
    if(!icon) return;
    if(col===ss.col) icon.textContent=ss.dir===1?'↑':'↓';
    else icon.textContent='';
  });
}

function resetSortState(bodyIds, defaultCol){
  bodyIds.forEach(id=>{ sortState[id]={col:defaultCol||'date',dir:1}; });
}

// delegated click handler for sortable th
document.addEventListener('click', e=>{
  const th=e.target.closest('th[data-sort]');
  if(!th) return;
  const [body,col]=th.dataset.sort.split(':');
  setSort(body,col);
});

// ═══════════ VIEW SWITCHING ═══════════
function showView(v){
  document.getElementById('view-monthly').classList.toggle('active', v==='monthly');
  document.getElementById('view-template').classList.toggle('active', v==='template');
  document.getElementById('view-all').classList.toggle('active', v==='all');
  document.getElementById('tab-monthly').classList.toggle('active', v==='monthly');
  document.getElementById('tab-template').classList.toggle('active', v==='template');
  document.getElementById('tab-all').classList.toggle('active', v==='all');
  if(v==='template') loadTemplates();
  if(v==='all') loadAllTransactions();
}

// ═══════════ CAROUSEL ═══════════
function carouselMonths() {
  const today=new Date(), result=new Set();
  for(let i=-36;i<=6;i++){
    const d=new Date(today.getFullYear(),today.getMonth()+i,1);
    result.add(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`);
  }
  Object.keys(monthCounts).forEach(m=>result.add(m));
  return [...result].sort();
}
function buildCarousel() {
  const track=document.getElementById('carousel-track');
  track.innerHTML='';
  carouselMonths().forEach(m=>{
    const btn=document.createElement('button');
    const hasData=!!monthCounts[m];
    btn.className='cm'+(m===currentMonth?' active':'')+(hasData?'':' empty');
    btn.dataset.month=m;
    const[y,mo]=m.split('-');
    btn.innerHTML=`<div class="cm-mon">${MONS[+mo-1]}</div><div class="cm-yr">${y}</div>`;
    btn.onclick=()=>loadMonth(m);
    track.appendChild(btn);
  });
  scrollCarouselTo(currentMonth);
}
function scrollCarouselTo(month) {
  setTimeout(()=>{
    const el=document.querySelector(`.cm[data-month="${month}"]`);
    if(el) el.scrollIntoView({behavior:'smooth',block:'nearest',inline:'center'});
  },60);
}
function shiftCarousel(dir) {
  const months=carouselMonths(), idx=months.indexOf(currentMonth);
  const next=months[Math.max(0,Math.min(months.length-1,idx+dir))];
  if(next&&next!==currentMonth) loadMonth(next);
}
function jumpToday(){
  const today=new Date();
  const m=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`;
  if(m!==currentMonth) loadMonth(m); else scrollCarouselTo(m);
}
function buildJumpPicker(){
  const ym=document.getElementById('jp-month'), yy=document.getElementById('jp-year');
  ym.innerHTML=''; yy.innerHTML='';
  MONS.forEach((n,i)=>{const o=document.createElement('option');o.value=i+1;o.textContent=n;ym.appendChild(o);});
  const thisYear=new Date().getFullYear();
  for(let y=thisYear-10;y<=thisYear+5;y++){
    const o=document.createElement('option');o.value=y;o.textContent=y;yy.appendChild(o);
  }
}
function toggleJump(){
  const pp=document.getElementById('jump-popup'), open=pp.classList.toggle('open');
  if(open){ const[y,m]=currentMonth.split('-');
    document.getElementById('jp-month').value=+m;
    document.getElementById('jp-year').value=+y; }
}
function doJump(){
  const mo=String(document.getElementById('jp-month').value).padStart(2,'0');
  const yr=document.getElementById('jp-year').value;
  document.getElementById('jump-popup').classList.remove('open');
  loadMonth(`${yr}-${mo}`);
}
document.addEventListener('click',e=>{
  if(!document.getElementById('jump-popup').contains(e.target)&&
     !document.getElementById('jump-btn').contains(e.target))
    document.getElementById('jump-popup').classList.remove('open');
});

// ═══════════ BALANCE SUMMARY ═══════════
// Small helper — formats a balance value with bs-val class (11 px, sign-coloured)
function fmtBs(n){
  if(n==null||isNaN(n)) return '<span class="bs-val">—</span>';
  const cls='bs-val'+(n>0?' pos':n<0?' neg':'');
  return `<span class="${cls}">${fmt(n)}</span>`;
}

function renderBalanceSummary(bals){
  // ── date labels ──────────────────────────────────────────────
  const[y,m]=currentMonth.split('-').map(Number);
  const mo=new Date(y,m-1,1).toLocaleString('en-US',{month:'short'});
  const lastDay=new Date(y,m,0).getDate();
  document.getElementById('bs-lbl-first').textContent=`${mo} 1`;
  document.getElementById('bs-lbl-last').textContent=`${mo} ${lastDay}`;

  // ── row 1: balance forward ──
  [['bs-first-est-cell',bals.bf_est],
   ['bs-first-act-cell',bals.bf_act],
   ['bs-first-rec-cell',bals.bf_rec]].forEach(([cellId,v])=>{
    const cell=document.getElementById(cellId);
    if(cell) cell.innerHTML=fmtBs(v);
  });

  // ── row 2: net — populated by updateSums() after transactions load ──

  // ── row 3: end-of-month balance ──
  [['bs-last-est',bals.estimated],['bs-last-act',bals.actual],['bs-last-rec',bals.reconciled]]
    .forEach(([id,v])=>{ const el=document.getElementById(id); if(el) el.innerHTML=fmtBs(v); });
}



// ═══════════ LOAD MONTH ═══════════
async function loadMonth(month){
  currentMonth=month;
  // Reset sort state for transaction tables on every month load
  resetSortState(['income-body','expense-body'],'date');
  buildCarousel();
  const[mData,txns,bals]=await Promise.all([
    fetch(`/api/months/${month}`).then(r=>r.json()),
    fetch(`/api/months/${month}/transactions`).then(r=>r.json()),
    fetch(`/api/months/${month}/balances`).then(r=>r.json()),
  ]);
  transactions=txns;
  transactions.forEach(t=>{ if(t.category) addCat(t.category); if(t.payee) addPayee(t.payee); });
  computePayeeBadges();
  renderBalanceSummary(bals);
  renderTransactions();
  loadChart(month);
}

async function refreshBalances(){
  const bals=await fetch(`/api/months/${currentMonth}/balances`).then(r=>r.json());
  renderBalanceSummary(bals);
  updateSums();
  loadGlobalBalance();
  loadChart(currentMonth);
}

async function loadGlobalBalance(){
  const g=await fetch('/api/balances/global').then(r=>r.json());
  fmtG(g.estimated,  document.getElementById('g-est'));
  fmtG(g.actual,     document.getElementById('g-act'));
  fmtG(g.reconciled, document.getElementById('g-rec'));
}

// ═══════════ CHART ═══════════
// IQR-based y-axis clipping: exclude values outside Q1 ± 3×IQR / Q3 ± 3×IQR
// (Tukey's outer fence). Scale is set from the remaining values.
// The data line still renders through clipped regions — nothing is hidden.
function robustYBounds(vals){
  const v = vals.filter(x => x != null).sort((a, b) => a - b);
  if(!v.length) return {yMin: -50, yMax: 50};
  const n = v.length;
  const q1 = v[Math.floor(n * 0.25)];
  const q3 = v[Math.floor(n * 0.75)];
  const iqr = q3 - q1;
  let useMin, useMax;
  if(iqr > 0){
    const lo = q1 - 3 * iqr;
    const hi = q3 + 3 * iqr;
    const inliers = v.filter(x => x >= lo && x <= hi);
    useMin = inliers.length ? inliers[0]              : v[0];
    useMax = inliers.length ? inliers[inliers.length-1] : v[n-1];
  } else {
    useMin = v[0]; useMax = v[n-1];
  }
  const lo = Math.min(0, useMin);
  const hi = Math.max(0, useMax);
  const pad = Math.max((hi - lo) * 0.08, 50);
  return {yMin: lo - pad, yMax: hi + pad};
}

function toggleChart(){
  chartVisible=!chartVisible;
  const p=document.getElementById('chart-panel'), b=document.getElementById('chart-toggle-btn');
  p.classList.toggle('collapsed',!chartVisible);
  b.innerHTML=chartVisible?'<i class="bi bi-chevron-up"></i> hide':'<i class="bi bi-chevron-down"></i> chart';
  if(chartVisible&&currentMonth) loadChart(currentMonth);
}


// Plugin: floating label annotations for the monthly min and max actual balance.
// Draws a small pill-shaped callout above the max point and below the min point,
// with a thin leader line connecting it to the data point.
const minMaxAnnotationPlugin={
  id:'minMaxAnnotation',
  afterDatasetsDraw(chart){
    const meta=chart.getDatasetMeta(1);
    if(!meta||!meta.data.length) return;
    const{ctx,chartArea:{left,right,top,bottom}}=chart;
    const rawData=chart.data.datasets[1].data;
    const n=rawData.length;

    // Find single min and max indices
    let minI=-1,maxI=-1;
    for(let i=0;i<n;i++){
      const v=rawData[i];
      if(v==null) continue;
      if(minI===-1||v<rawData[minI]) minI=i;
      if(maxI===-1||v>rawData[maxI]) maxI=i;
    }
    if(minI===-1) return;

    function drawCallout(idx,isMax){
      const pt=meta.data[idx];
      const val=rawData[idx];
      const text=(isMax?'max: ':'min: ')+fmt(val);
      const ptX=pt.x, ptY=pt.y;

      ctx.save();
      ctx.font='bold 9px system-ui,sans-serif';
      const tw=ctx.measureText(text).width;
      const pH=4, pW=6, rnd=3;
      const boxW=tw+pW*2, boxH=14+pH*2;
      const gap=6;  // space between point and box

      // Always place the label toward zero: below the point when value >= 0
      // (zero is below a positive balance), above when value < 0.
      // This prevents labels being pushed off the top/bottom of the chart.
      const goBelow=val>=0;
      const bx=Math.max(left+boxW/2+2, Math.min(right-boxW/2-2, ptX));
      const by=goBelow?ptY+gap:ptY-gap-boxH;

      // Clip callout to chart area so it doesn't overflow into axes
      ctx.beginPath();
      ctx.rect(left,top,right-left,bottom-top);
      ctx.clip();

      // Pill background — blue for both, slightly lighter for max
      const bg=isMax?'rgba(79,126,248,.92)':'rgba(59,100,220,.92)';
      ctx.fillStyle=bg;
      ctx.beginPath();
      ctx.roundRect(bx-boxW/2, by, boxW, boxH, rnd);
      ctx.fill();

      // Leader line: from point toward zero (same direction as box placement)
      const lineY0=goBelow?ptY+3:ptY-3;
      const lineY1=goBelow?by:by+boxH;
      if(Math.abs(lineY1-lineY0)>2){
        ctx.beginPath();
        ctx.moveTo(ptX,lineY0);
        ctx.lineTo(ptX,lineY1);
        ctx.strokeStyle=bg;
        ctx.lineWidth=1.5;
        ctx.stroke();
      }

      // Label text
      ctx.fillStyle='#fff';
      ctx.textAlign='center';
      ctx.textBaseline='middle';
      ctx.fillText(text, bx, by+boxH/2);
      ctx.restore();
    }

    // Draw min first (below line) then max (above) so max is on top if they overlap
    if(minI!==maxI){ drawCallout(minI,false); }
    drawCallout(maxI,true);
  }
};

// Plugin: canvas-clipped fill for actual line — green above zero, red below zero.
// Chart.js's built-in fill is disabled (fill:false on dataset); this plugin draws
// two filled regions using rect-clipping so the colour split is exact at y=0.
const actualFillPlugin={
  id:'actualFill',
  beforeDatasetsDraw(chart){
    const meta=chart.getDatasetMeta(0);
    if(!meta||!meta.data.length) return;
    const{ctx,scales:{y},chartArea:{left,right,top,bottom}}=chart;
    const zeroY=Math.max(top,Math.min(bottom,y.getPixelForValue(0)));
    const pts=meta.data;
    const rawData=chart.data.datasets[0].data;
    const n=pts.length;
    if(n<1) return;

    // Draw filled area for one half (above or below zero).
    // Uses bezier control points stored on each PointElement (set by Chart.js
    // during layout) to match the rendered tension curve exactly.
    function fillSide(color, clipT, clipH){
      if(clipH<=0) return;
      ctx.save();
      ctx.beginPath(); ctx.rect(left,clipT,right-left,clipH); ctx.clip();

      // Walk segments; restart path at each gap caused by null data
      let segStart=-1;
      const flush=(end)=>{
        const seg=pts.slice(segStart,end);
        if(seg.length<1){segStart=-1;return;}
        ctx.beginPath();
        ctx.moveTo(seg[0].x, zeroY);
        ctx.lineTo(seg[0].x, seg[0].y);
        for(let j=1;j<seg.length;j++){
          const p=seg[j-1],c=seg[j];
          if(p.cp2&&c.cp1){
            ctx.bezierCurveTo(p.cp2.x,p.cp2.y,c.cp1.x,c.cp1.y,c.x,c.y);
          } else {
            ctx.lineTo(c.x,c.y);
          }
        }
        ctx.lineTo(seg[seg.length-1].x, zeroY);
        ctx.closePath();
        ctx.fillStyle=color;
        ctx.fill();
        segStart=-1;
      };
      for(let i=0;i<=n;i++){
        const isNull=(i===n)||rawData[i]==null||pts[i].skip;
        if(!isNull&&segStart<0){ segStart=i; }
        else if(isNull&&segStart>=0){ flush(i); }
      }
      ctx.restore();
    }

    fillSide('rgba(34,197,94,.22)', top,   zeroY-top);      // green above zero
    fillSide('rgba(239,68,68,.22)', zeroY, bottom-zeroY);   // red below zero
  }
};

// Custom Chart.js plugin for month-boundary vertical lines
const monthBoundaryPlugin={
  id:'monthBoundary',
  afterDraw(chart,args,opts){
    if(!opts.lines||!opts.lines.length) return;
    const{ctx,scales:{x,y}}=chart;
    opts.lines.forEach(idx=>{
      const meta=chart.getDatasetMeta(0);
      if(!meta.data.length) return;
      // interpolate pixel between index floor and ceil
      const lo=Math.floor(idx), hi=Math.ceil(idx), frac=idx-lo;
      const xLo=lo>=0&&lo<meta.data.length?meta.data[lo].x:null;
      const xHi=hi>=0&&hi<meta.data.length?meta.data[hi].x:null;
      if(xLo==null&&xHi==null) return;
      const xPos=xLo!=null&&xHi!=null?(xLo+(xHi-xLo)*frac):(xLo??xHi);
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(xPos,y.top);
      ctx.lineTo(xPos,y.bottom);
      ctx.strokeStyle='rgba(255,255,255,0.75)';
      ctx.lineWidth=1.5;
      ctx.setLineDash([]);
      ctx.stroke();
      ctx.restore();
    });
  }
};

async function loadChart(month){
  if(!chartVisible) return;
  // Determine prev/next months
  const[y,m]=month.split('-').map(Number);
  const prevD=new Date(y,m-2,1), nextD=new Date(y,m,1);
  const prevMonth=`${prevD.getFullYear()}-${String(prevD.getMonth()+1).padStart(2,'0')}`;
  const nextMonth=`${nextD.getFullYear()}-${String(nextD.getMonth()+1).padStart(2,'0')}`;
  const hasPrev=!!monthCounts[prevMonth];
  const hasNext=!!monthCounts[nextMonth];

  const fetches=[fetch(`/api/months/${month}/daily-balances`).then(r=>r.json())];
  if(hasPrev) fetches.push(fetch(`/api/months/${prevMonth}/daily-balances`).then(r=>r.json()));
  if(hasNext) fetches.push(fetch(`/api/months/${nextMonth}/daily-balances`).then(r=>r.json()));

  const results=await Promise.all(fetches);
  const currData=results[0];
  const prevData=hasPrev?results[1]:null;
  const nextData=hasNext?results[hasPrev?2:1]:null;

  // Build 7-day null placeholder for a month (last 7 days of prevMonth, first 7 of nextMonth)
  function prevPlaceholders(){
    const daysInPrev=new Date(y,m-1,0).getDate();
    const pm=m===1?12:m-1, py=m===1?y-1:y;
    return Array.from({length:7},(_,i)=>{
      const d=daysInPrev-6+i;
      return{date:`${py}-${String(pm).padStart(2,'0')}-${String(d).padStart(2,'0')}`,estimated:null,actual:null};
    });
  }
  function nextPlaceholders(){
    const nm=m===12?1:m+1, ny=m===12?y+1:y;
    return Array.from({length:7},(_,i)=>({
      date:`${ny}-${String(nm).padStart(2,'0')}-${String(i+1).padStart(2,'0')}`,estimated:null,actual:null
    }));
  }

  // Always produce exactly 7-day wings; use real data if available, nulls otherwise
  const prevSlice=prevData?prevData.slice(-7):prevPlaceholders();
  const nextSlice=nextData?nextData.slice(0,7):nextPlaceholders();
  const allData=[...prevSlice,...currData,...nextSlice];

  const labels=allData.map(d=>d.date.slice(5)); // MM-DD
  const estData=allData.map(d=>d.estimated);
  const actData=allData.map(d=>d.actual);

  // Boundary lines always present at fixed positions (7 days in + 7 days out)
  const boundaryLines=[prevSlice.length-0.5, prevSlice.length+currData.length-0.5];

  // Compute y-axis bounds with outlier-spike resistance
  const {yMin, yMax} = robustYBounds([...actData,...estData]);

  // Per-point radius/color: uniform small dot, colour reflects sign of balance
  const actRadii=actData.map(v=>v==null?0:2);
  const actPtColors=actData.map(v=>{
    if(v==null) return 'transparent';
    return v>=0?'rgba(34,197,94,.55)':'rgba(239,68,68,.55)';
  });

  const ctx=document.getElementById('bal-chart').getContext('2d');
  if(balChart){ balChart.destroy(); balChart=null; }
  const gridC='rgba(44,47,62,.5)', tickC='#6b7280';
  balChart=new Chart(ctx,{
    type:'line',
    data:{labels,datasets:[
      {label:'Actual',data:actData,
       borderColor:'rgba(34,197,94,.85)',
       backgroundColor:'transparent',
       fill:false,tension:.3,spanGaps:false,
       borderWidth:1.5,
       pointRadius:actRadii,
       pointHoverRadius:actRadii.map(r=>r?r+1.5:2),
       pointBackgroundColor:actPtColors,
       pointBorderColor:actPtColors,
       segment:{
         borderColor:ctx=>{
           const y0=ctx.p0.parsed.y, y1=ctx.p1.parsed.y;
           return (y0<0||y1<0)?'rgba(239,68,68,.85)':undefined;
         }
       }
      },
      {label:'Estimated',data:estData,
       borderColor:'rgba(79,126,248,.6)',
       backgroundColor:'transparent',fill:false,tension:.3,
       pointRadius:0,borderWidth:1.5,borderDash:[4,3],
       segment:{
         borderColor:ctx=>ctx.p1.parsed.y<0?'rgba(239,68,68,.65)':undefined
       }
      },
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:400},
      plugins:{
        legend:{display:true,position:'top',labels:{color:tickC,font:{size:10},boxWidth:18,padding:10}},
        tooltip:{mode:'index',intersect:false,
          callbacks:{label:ctx=>`${ctx.dataset.label}: ${fmt(ctx.raw)}`},
          backgroundColor:'rgba(26,29,39,.95)',titleColor:'#e2e4ed',bodyColor:'#9ca3af',
          borderColor:'rgba(44,47,62,.8)',borderWidth:1},
        monthBoundary:{lines:boundaryLines}
      },
      scales:{
        x:{grid:{color:gridC},ticks:{color:tickC,font:{size:9},maxTicksLimit:12}},
        y:{min:yMin,max:yMax,
           grid:{color:ctx=>ctx.tick.value===0?'rgba(200,200,200,.4)':gridC},
           ticks:{color:tickC,font:{size:9},maxTicksLimit:6,callback:v=>fmt(v)},
           position:'left'}
      }
    },
    plugins:[actualFillPlugin,minMaxAnnotationPlugin,monthBoundaryPlugin]
  });
}

// ═══════════ ALL-TRANSACTIONS CHART ═══════════
let allChart        = null;
let allChartVisible = true;
let allChartScope   = 'all'; // 'all' | 'filtered'

function toggleAllChart(){
  allChartVisible = !allChartVisible;
  const p = document.getElementById('all-chart-panel');
  const b = document.getElementById('all-chart-toggle-btn');
  p.classList.toggle('collapsed', !allChartVisible);
  b.innerHTML = allChartVisible
    ? '<i class="bi bi-chevron-up"></i> hide'
    : '<i class="bi bi-chevron-down"></i> chart';
  if(allChartVisible) renderAllChart();
}

function setAllChartScope(scope){
  allChartScope = scope;
  document.getElementById('ac-scope-all').classList.toggle('active', scope==='all');
  document.getElementById('ac-scope-vis').classList.toggle('active', scope==='filtered');
  renderAllChart();
}

function renderAllChart(){
  if(!allChartVisible) return;
  const canvas = document.getElementById('all-bal-chart');
  if(!canvas) return;

  const sourceRows = allChartScope === 'filtered'
    ? applyAllFilters(allTransactions)
    : allTransactions;

  // Rows with valid dates
  const dated = sourceRows.filter(t => t.date && t.date.length >= 10);
  if(!dated.length){
    if(allChart){ allChart.destroy(); allChart = null; }
    return;
  }

  const allDates = dated.map(t => t.date.slice(0,10));
  const minDate  = allDates.reduce((a,b) => a<b?a:b);
  const maxDate  = allDates.reduce((a,b) => a>b?a:b);

  // Starting balance = sum of in-scope transactions strictly before minDate
  let startEst = 0, startAct = 0;
  for(const t of dated){
    const d = t.date.slice(0,10);
    if(d >= minDate) continue;
    const s = (t.entry_type === 'credit' ? 1 : -1) * parseFloat(t.amount || 0);
    startEst += s;
    if(t.status === 'actual' || t.status === 'reconciled') startAct += s;
  }

  // Daily deltas within range
  const estDelta = {}, actDelta = {};
  for(const t of dated){
    const d = t.date.slice(0,10);
    if(d < minDate || d > maxDate) continue;
    const s = (t.entry_type === 'credit' ? 1 : -1) * parseFloat(t.amount || 0);
    estDelta[d] = (estDelta[d] || 0) + s;
    if(t.status === 'actual' || t.status === 'reconciled')
      actDelta[d] = (actDelta[d] || 0) + s;
  }

  // Enumerate every day in range
  const labels = [], estData = [], actData = [], boundaryLines = [];
  const today = new Date().toISOString().slice(0,10);
  let bal = startEst, actBal = startAct, prevMonth = null, idx = 0;
  const cur = new Date(minDate + 'T00:00:00');
  const end = new Date(maxDate + 'T00:00:00');
  while(cur <= end){
    const ds = cur.toISOString().slice(0,10);
    const mo = ds.slice(0,7);
    if(prevMonth && mo !== prevMonth) boundaryLines.push(idx - 0.5);
    prevMonth = mo;
    bal    = Math.round((bal    + (estDelta[ds] || 0)) * 100) / 100;
    actBal = Math.round((actBal + (actDelta[ds] || 0)) * 100) / 100;
    labels.push(ds);
    estData.push(bal);
    actData.push(ds <= today ? actBal : null);
    cur.setDate(cur.getDate() + 1);
    idx++;
  }

  // Smart tick label: MM-DD for ≤180 days, YYYY-MM at month starts otherwise
  const spanDays = labels.length;
  const tickCb = (val, i) => {
    const ds = labels[i];
    if(!ds) return '';
    if(spanDays <= 180) return ds.slice(5);          // MM-DD
    if(ds.slice(8) === '01') return ds.slice(0,7);  // YYYY-MM on first of month
    return '';
  };

  // Y-axis bounds with outlier-spike resistance
  const {yMin, yMax} = robustYBounds([...estData, ...actData]);

  const actRadii = actData.map(v => v == null ? 0 : 2);
  const actPtColors = actData.map(v => {
    if(v == null) return 'transparent';
    return v >= 0 ? 'rgba(34,197,94,.55)' : 'rgba(239,68,68,.55)';
  });

  const ctx = canvas.getContext('2d');
  if(allChart){ allChart.destroy(); allChart = null; }
  const gridC = 'rgba(44,47,62,.5)', tickC = '#6b7280';
  allChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Actual', data: actData,
        borderColor: 'rgba(34,197,94,.85)', backgroundColor: 'transparent',
        fill: false, tension: .3, spanGaps: false, borderWidth: 1.5,
        pointRadius: actRadii,
        pointHoverRadius: actRadii.map(r => r ? r+1.5 : 2),
        pointBackgroundColor: actPtColors, pointBorderColor: actPtColors,
        segment: { borderColor: c => {
          const y0=c.p0.parsed.y, y1=c.p1.parsed.y;
          return (y0<0||y1<0) ? 'rgba(239,68,68,.85)' : undefined;
        }}
      },
      { label: 'Estimated', data: estData,
        borderColor: 'rgba(79,126,248,.6)', backgroundColor: 'transparent',
        fill: false, tension: .3, pointRadius: 0, borderWidth: 1.5,
        borderDash: [4,3],
        segment: { borderColor: c => c.p1.parsed.y < 0 ? 'rgba(239,68,68,.65)' : undefined }
      },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      plugins: {
        legend: { display: true, position: 'top',
          labels: { color: tickC, font: { size: 10 }, boxWidth: 18, padding: 10 }},
        tooltip: { mode: 'index', intersect: false,
          callbacks: { label: c => `${c.dataset.label}: ${fmt(c.raw)}`,
                       title: ts => ts[0]?.label || '' },
          backgroundColor: 'rgba(26,29,39,.95)', titleColor: '#e2e4ed',
          bodyColor: '#9ca3af', borderColor: 'rgba(44,47,62,.8)', borderWidth: 1 },
        monthBoundary: { lines: boundaryLines }
      },
      scales: {
        x: { grid: { color: gridC },
             ticks: { color: tickC, font: { size: 9 }, maxTicksLimit: 14,
                      callback: tickCb }},
        y: { min: yMin, max: yMax,
             grid: { color: c => c.tick.value === 0 ? 'rgba(200,200,200,.4)' : gridC },
             ticks: { color: tickC, font: { size: 9 }, maxTicksLimit: 6,
                      callback: v => fmt(v) },
             position: 'left' }
      }
    },
    plugins: [actualFillPlugin, minMaxAnnotationPlugin, monthBoundaryPlugin]
  });
}

// ═══════════ PAYEE BADGES ═══════════
function computePayeeBadges(){
  payeeBadges={};
  const sorted=[...transactions].sort((a,b)=>(a.date||'9').localeCompare(b.date||'9')||a.id-b.id);
  const seen={};
  for(const t of sorted){
    const k=`${t.payee}|${t.entry_type}`; seen[k]=(seen[k]||0)+1; payeeBadges[t.id]=seen[k];
  }
}
function computeTmplBadges(){
  tmplBadges={};
  const sorted=[...templates].sort((a,b)=>a.sort_order-b.sort_order||a.id-b.id);
  const seen={};
  for(const t of sorted){
    const k=`${t.payee}|${t.entry_type}`; seen[k]=(seen[k]||0)+1; tmplBadges[t.id]=seen[k];
  }
}

// ═══════════ PUSH-TO-TEMPLATE STATUS ═══════════
function pushStatus(txn){
  const myOrder=payeeBadges[txn.id]||1;
  const peers=templates.filter(t=>t.payee===txn.payee&&t.entry_type===txn.entry_type)
    .sort((a,b)=>a.sort_order-b.sort_order||a.id-b.id);
  const match=peers[myOrder-1];
  if(!match) return 'pnew';
  const txnDay=txn.date?parseInt(txn.date.slice(8),10):null;
  const exact=match.category===txn.category&&Math.abs(match.amount-txn.amount)<0.005&&
    match.is_automatic===txn.is_automatic&&(match.notes||'')===(txn.notes||'')&&
    (match.day_of_month==null||txnDay==null||match.day_of_month===txnDay);
  return exact?'pexact':'pdiff';
}

// ═══════════ TAB NAVIGATION ═══════════
function getNextTxnTarget(currentTd,shiftKey){
  const tr=currentTd.closest('tr'),tbody=tr.closest('tbody');
  const eds=Array.from(tr.querySelectorAll('td.editable'));
  const ti=eds.indexOf(currentTd),txnId=parseInt(tr.dataset.id);
  const rows=Array.from(tbody.querySelectorAll('tr:not(.ghost-row)'));
  const ri=rows.indexOf(tr);
  if(!shiftKey){
    if(ti<eds.length-1) return{txnId,fieldIdx:ti+1};
    if(ri<rows.length-1) return{txnId:parseInt(rows[ri+1].dataset.id),fieldIdx:0};
    return{type:'ghost',tbodyId:tbody.id};
  }else{
    if(ti>0) return{txnId,fieldIdx:ti-1};
    if(ri>0){const pe=rows[ri-1].querySelectorAll('td.editable');
      return{txnId:parseInt(rows[ri-1].dataset.id),fieldIdx:pe.length-1};}
    return null;
  }
}
function applyTxnTarget(t, attempts=0){
  if(!t) return;
  if(t.type==='ghost'){
    const pfx = t.tbodyId==='income-body' ? 'gi-inc' : 'gi-exp';
    const el = document.getElementById(`${pfx}-date`);
    if(el) el.focus();
    return;
  }else{
    const row=document.querySelector(`tr.txn-row[data-id="${t.txnId}"]`);
    if(!row) return;
    const eds=row.querySelectorAll('td.editable');
    if(eds[t.fieldIdx]) eds[t.fieldIdx].click();
  }
}
function getNextTmplTarget(currentTd,shiftKey){
  const tr=currentTd.closest('tr'),tbody=tr.closest('tbody');
  const eds=Array.from(tr.querySelectorAll('td.teditable'));
  const ti=eds.indexOf(currentTd),tmplId=parseInt(tr.dataset.id);
  const rows=Array.from(tbody.querySelectorAll('tr.tmpl-row'));
  const ri=rows.indexOf(tr);
  if(!shiftKey){
    if(ti<eds.length-1) return{tmplId,fieldIdx:ti+1};
    if(ri<rows.length-1) return{tmplId:parseInt(rows[ri+1].dataset.id),fieldIdx:0};
    return{type:'ghost',tbodyId:tbody.id};
  }else{
    if(ti>0) return{tmplId,fieldIdx:ti-1};
    if(ri>0){const pe=rows[ri-1].querySelectorAll('td.teditable');
      return{tmplId:parseInt(rows[ri-1].dataset.id),fieldIdx:pe.length-1};}
    return null;
  }
}
function applyTmplTarget(t){
  if(!t) return;
  if(t.type==='ghost'){
    const pfx = t.tbodyId==='tmpl-income-body' ? 'gt-inc' : 'gt-exp';
    const el = document.getElementById(`${pfx}-payee`);
    if(el) el.focus();
  }else{
    const row=document.querySelector(`tr.tmpl-row[data-id="${t.tmplId}"]`);
    if(!row) return;
    const eds=row.querySelectorAll('td.teditable');
    if(eds[t.fieldIdx]) eds[t.fieldIdx].click();
  }
}

// ═══════════ EDITABLE CELL — TXN ═══════════
function makePayeeSpan(txn, section){
  const span=document.createElement('span');
  span.textContent=txn.payee||'';
  const total=section.filter(t=>t.payee===txn.payee&&t.entry_type===txn.entry_type).length;
  if(total>1){
    const b=document.createElement('span');
    b.className='pbadge'; b.textContent='#'+(payeeBadges[txn.id]||1);
    span.appendChild(b);
  }
  return span;
}

function makeEC(txn, field, type, extraClass, section){
  const td=document.createElement('td');
  td.className='editable '+(extraClass||'');
  let span;
  if(field==='payee'&&section) span=makePayeeSpan(txn,section);
  else{
    span=document.createElement('span');
    if(field==='amount'){
      span.innerHTML=fmtTxnAmt(txn.amount, txn.entry_type);
    }else if(field==='entry_type'){
      span.textContent=txn.entry_type==='credit'?'Income':'Expense';
    }else if(field==='date'){
      span.textContent=txn.date?String(parseInt(txn.date.slice(8),10)):'';
    }else{ span.textContent=txn[field]||''; }
  }
  td.appendChild(span);

  td.onclick=e=>{
    if(td.querySelector('input,select')) return;
    // Mark this row as being edited
    editingTxnId=txn.id;
    span.style.display='none';
    let el;

    const repaintStatic=()=>{
      const latest=getTxnById(txn.id) || txn;
      if(field==='payee'&&section){
        span.replaceWith(makePayeeSpan(latest, section));
        span = td.querySelector('span');
      }else if(field==='amount'){
        span.innerHTML=fmtTxnAmt(latest.amount, latest.entry_type);
      }else if(field==='entry_type'){
        span.textContent=latest.entry_type==='credit'?'Income':'Expense';
      }else if(field==='date'){
        span.textContent=latest.date?String(parseInt(latest.date.slice(8),10)):'';
      }else{
        span.textContent=latest[field]||'';
      }
    };

    const closeEditor=()=>{
      if(el&&el.parentNode===td) el.remove();
      repaintStatic();
      span.style.display='';
      editingTxnId=null;
    };

    // Helper: build onTab callback for this cell
    const makeOnTab=(shiftKey)=>{
      el.onblur=null; _hideAC();
      doSave();
      closeEditor();
      const t=getNextTxnTarget(td,shiftKey);
      // If next target is the ghost row, let browser Tab move naturally to tfoot inputs
      if(t && t.type!=='ghost') setTimeout(()=>applyTxnTarget(t),80);
    };

    if(field==='category'){
      el=document.createElement('input'); el.type='text'; el.className='cell-input'; el.value=txn[field]||'';
      acBind(el, ()=>[...categories].sort(), v=>{ el.value=v; }, makeOnTab);
    }else if(field==='payee'){
      el=document.createElement('input'); el.type='text'; el.className='cell-input'; el.value=txn[field]||'';
      acBind(el, ()=>[...payees].sort(), v=>{ el.value=v; }, makeOnTab);
    }else if(field==='entry_type'){
      el=document.createElement('select'); el.className='cell-select';
      ['credit','debit'].forEach(v=>{
        const o=document.createElement('option'); o.value=v;
        o.textContent=v==='credit'?'Income':'Expense';
        if(v===txn[field]) o.selected=true; el.appendChild(o);});
    }else if(field==='date'){
      el=document.createElement('input'); el.type='number'; el.className='cell-input';
      el.style.width='48px'; el.style.textAlign='center';
      const[yr,mo]=currentMonth.split('-');
      const lastDay=new Date(+yr,+mo,0).getDate();
      el.min='1'; el.max=String(lastDay);
      el.value=txn.date?String(parseInt(txn.date.slice(8),10)):'';
    }else{
      el=document.createElement('input'); el.type=type||'text'; el.className='cell-input';
      el.value=field==='amount'?txn.amount.toFixed(2):(txn[field]||'');
    }
    td.appendChild(el); el.focus();
    if(el.tagName==='INPUT'){try{el.select()}catch(x){}}

    const doSave=()=>{
      let v=field==='amount'?parseFloat(el.value)||0:el.value;
      // Reconstruct full YYYY-MM-DD from bare day number entered by user
      if(field==='date'&&v){
        const[yr,mo]=currentMonth.split('-');
        const lastDay=new Date(+yr,+mo,0).getDate();
        const day=Math.min(Math.max(1,parseInt(v,10)||1),lastDay);
        v=`${currentMonth}-${String(day).padStart(2,'0')}`;
      }
      const latest=getTxnById(txn.id) || txn;
      if(valuesEqual(field, latest[field], v)) return false;
      if(field==='category'&&v) addCat(v);
      if(field==='payee'&&v) addPayee(v);
      updateField(txn.id,field,v);
      return true;
    };
    el.onblur=()=>{ _hideAC(); doSave(); closeEditor(); };
    el.onkeydown=ev=>{
      if(ev.key==='Escape'){
        ev.preventDefault();el.onblur=null;_hideAC();closeEditor();
        return;
      }
      if(ev.key==='Tab'){
        ev.preventDefault();
        _acPickFromInput(el);
        makeOnTab(ev.shiftKey);
        return;
      }
      if(ev.key==='Enter'){
        ev.preventDefault();
        if(_acDrop && _acPickFromInput(el)){ makeOnTab(false); return; }
        el.blur();
      }
    };
    e.stopPropagation();
  };
  return td;
}

// ═══════════ FLAG & STATUS CELLS ═══════════
function makeFlagCell(txn,field,icon){
  const td=document.createElement('td'); td.className='w-fl';
  const btn=document.createElement('button');
  btn.className='flag-btn'+(txn[field]?' on':'');
  btn.innerHTML=`<i class="bi bi-${icon}${txn[field]?'-fill':''}"></i>`;
  btn.onclick=()=>updateField(txn.id,field,txn[field]?0:1);
  td.appendChild(btn); return td;
}
function makePushCell(txn){
  const td=document.createElement('td'); td.className='w-fl';
  const st=pushStatus(txn);
  const btn=document.createElement('button'); btn.className=`push-btn ${st}`;
  const icons={pnew:'bi-arrow-right-circle',pdiff:'bi-arrow-right-circle-fill',pexact:'bi-check-circle-fill'};
  const titles={pnew:'Not in template — click to add',pdiff:'In template (values differ) — click to update',pexact:'In template (exact match)'};
  btn.innerHTML=`<i class="bi ${icons[st]}"></i>`; btn.title=titles[st];
  if(st!=='pexact') btn.onclick=()=>doPushToTemplate(txn.id);
  td.appendChild(btn); return td;
}
function makeStatusCell(txn){
  const td=document.createElement('td'); td.className='w-st';
  const div=document.createElement('div'); div.className='status-group';
  [['estimated','Est','ae'],['actual','Act','aa'],['reconciled','Rec','ar']].forEach(([key,lbl,cls])=>{
    const b=document.createElement('button');
    b.className='sb'+(txn.status===key?' '+cls:''); b.textContent=lbl;
    b.onclick=()=>updateField(txn.id,'status',key); div.appendChild(b);
  });
  td.appendChild(div); return td;
}

// ═══════════ RENDER TRANSACTIONS ═══════════
function updateSums(){
  const inc=transactions.filter(t=>t.entry_type==='credit');
  const exp=transactions.filter(t=>t.entry_type==='debit');
  const s=arr=>arr.reduce((acc,t)=>acc+(t.entry_type==='credit'?t.amount:-t.amount),0);
  const incTotal=s(inc), expTotal=s(exp);
  document.getElementById('income-sum').textContent=fmt(incTotal);
  document.getElementById('expense-sum').textContent=fmt(-expTotal);
  // Net row in balance summary — broken out by status
  const sa=t=>t.entry_type==='credit'?t.amount:-t.amount;
  const netEst=transactions.reduce((acc,t)=>acc+sa(t),0);
  const netAct=transactions.filter(t=>['actual','reconciled'].includes(t.status)).reduce((acc,t)=>acc+sa(t),0);
  const netRec=transactions.filter(t=>t.status==='reconciled').reduce((acc,t)=>acc+sa(t),0);
  [['bs-net-est',netEst],['bs-net-act',netAct],['bs-net-rec',netRec]]
    .forEach(([id,v])=>{ const el=document.getElementById(id); if(el) el.innerHTML=fmtBs(v); });
}
function renderTransactions(){
  renderSection('income-body',  transactions.filter(t=>t.entry_type==='credit'));
  renderSection('expense-body', transactions.filter(t=>t.entry_type==='debit'));
  updateSums();
}
function renderSection(bodyId, rows){
  const hasEditing=editingTxnId&&rows.some(r=>r.id===editingTxnId);
  const sorted=hasEditing?[...rows]:sortRows(rows, bodyId, 'date');
  const tbody=document.getElementById(bodyId); tbody.innerHTML='';
  sorted.forEach(txn=>{
    const tr=document.createElement('tr'); tr.className='txn-row'; tr.dataset.id=txn.id;
    tr.appendChild(makeEC(txn,'date',   'date',   'w-dt'));
    tr.appendChild(makeEC(txn,'payee',  'text',   'w-py', sorted));
    tr.appendChild(makeEC(txn,'category','text',  'w-ca'));
    tr.appendChild(makeEC(txn,'amount', 'number', 'w-am'));
    tr.appendChild(makeEC(txn,'notes',  'text',   'w-no'));
    tr.appendChild(makeStatusCell(txn));
    tr.appendChild(makeFlagCell(txn,'is_automatic','lightning'));
    tr.appendChild(makePushCell(txn));
    const delTd=document.createElement('td'); delTd.className='w-de';
    const db=document.createElement('button'); db.className='del-btn';
    db.innerHTML='<i class="bi bi-x-lg"></i>'; db.onclick=()=>delTxn(txn.id);
    delTd.appendChild(db); tr.appendChild(delTd);
    tbody.appendChild(tr);
  });
  refreshSortIcons(bodyId);
}
// ═══════════ MUTATIONS — TXN ═══════════
async function updateField(id, field, value){
  const txn=getTxnById(id);
  if(!txn || valuesEqual(field, txn[field], value)) return;

  applyLocalTxnField(id, field, value);
  const patch = {[field]: value};
  if(field==='payee'){
    const txnNow=getTxnById(id);
    if(txnNow && !txnNow.category){
      const def=getPayeeDefaultCategory(value);
      if(def){
        applyLocalTxnField(id, 'category', def);
        patch.category = def;
      }
    }
  }

  const data=await fetch(`/api/transactions/${id}`,
    {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)}).then(r=>r.json());
  const i=transactions.findIndex(t=>t.id===id);
  if(i!==-1) transactions[i]={...transactions[i],...data};
  computePayeeBadges();
  if(!hasActiveEditor()) renderTransactions();
  else updateSums();
  await refreshBalances();
  refreshSuggestions();
}

async function delTxn(id){
  await fetch(`/api/transactions/${id}`,{method:'DELETE'});
  transactions=transactions.filter(t=>t.id!==id);
  computePayeeBadges(); renderTransactions(); refreshBalances();
  monthCounts[currentMonth]=Math.max(0,(monthCounts[currentMonth]||1)-1);
  buildCarousel();
  refreshSuggestions();
}

async function doPushToTemplate(txnId){
  await fetch(`/api/transactions/${txnId}/to-template`,{method:'POST'});
  templates=await fetch('/api/templates').then(r=>r.json());
  templates.forEach(t=>{if(t.category)addCat(t.category);if(t.payee)addPayee(t.payee);});
  computeTmplBadges(); renderTransactions();
  toast('Pushed to Template Builder');
}

function initMonthFromTemplate(){
  if(transactions.length===0){ doInit('replace_all'); return; }
  document.getElementById('init-modal-desc').textContent=
    `This month has ${transactions.length} transaction(s). Choose how to apply the template:`;
  document.getElementById('init-modal').classList.add('open');
}
async function doInit(mode){
  closeModal('init-modal');
  if(mode==='replace_all'){
    for(const t of transactions.filter(t=>!isDraftTxn(t)))
      await fetch(`/api/transactions/${t.id}`,{method:'DELETE'});
    transactions=[];
  }
  const data=await fetch(`/api/months/${currentMonth}/init`,
    {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})}).then(r=>r.json());
  toast(`Initialized: ${data.count} transactions (${mode==='replace_all'?'replaced all':'merged'})`);
  const txns=await fetch(`/api/months/${currentMonth}/transactions`).then(r=>r.json());
  transactions=txns;
  transactions.forEach(t=>{if(t.category)addCat(t.category);if(t.payee)addPayee(t.payee);});
  computePayeeBadges(); renderTransactions(); refreshBalances();
  monthCounts[currentMonth]=transactions.length; buildCarousel();
}
function closeModal(id){document.getElementById(id).classList.remove('open');}

// ═══════════ TEMPLATE BUILDER ═══════════
async function loadTemplates(){
  // Reset template sort state on each view open
  resetSortState(['tmpl-income-body','tmpl-expense-body'],'day_of_month');
  templates=await fetch('/api/templates').then(r=>r.json());
  templates.forEach(t=>{if(t.category)addCat(t.category);if(t.payee)addPayee(t.payee);});
  computeTmplBadges(); renderTemplates();
}
function updateTmplNet(){
  const net=templates.reduce((acc,t)=>acc+(t.entry_type==='credit'?1:-1)*parseFloat(t.amount||0),0);
  const el=document.getElementById('template-net');
  if(el) el.innerHTML=fmtBal(net);
}
function renderTemplates(){
  renderTmplSection('tmpl-income-body', templates.filter(t=>t.entry_type==='credit'));
  renderTmplSection('tmpl-expense-body',templates.filter(t=>t.entry_type==='debit'));
  updateTmplNet();
}
function makeTmplPayeeSpan(tmpl, section){
  const span=document.createElement('span');
  span.textContent=tmpl.payee||'';
  const total=section.filter(t=>t.payee===tmpl.payee&&t.entry_type===tmpl.entry_type).length;
  if(total>1){
    const b=document.createElement('span');
    b.className='pbadge'; b.textContent='#'+(tmplBadges[tmpl.id]||1);
    span.appendChild(b);
  }
  return span;
}
function makeTmplEC(tmpl,field,type,style,section){
  const td=document.createElement('td'); td.className='teditable';
  if(style) td.style.cssText=style;
  let span;
  if(field==='payee'&&section) span=makeTmplPayeeSpan(tmpl,section);
  else{
    span=document.createElement('span');
    if(field==='amount'){
      span.innerHTML=fmtTxnAmt(parseFloat(tmpl.amount||0), tmpl.entry_type);
    }else{
      span.textContent=tmpl[field]??'';
    }
  }
  td.appendChild(span);
  td.onclick=e=>{
    if(td.querySelector('input,select')) return;
    // Mark this row as being edited
    editingTmplId=tmpl.id;
    span.style.display='none';
    let el;

    const repaintStatic=()=>{
      const latest=getTmplById(tmpl.id) || tmpl;
      if(field==='payee'&&section){
        span.replaceWith(makeTmplPayeeSpan(latest, section));
        span = td.querySelector('span');
      }else if(field==='amount'){
        span.innerHTML=fmtTxnAmt(parseFloat(latest.amount||0), latest.entry_type);
      }else{
        span.textContent=latest[field]??'';
      }
    };

    const closeEditor=()=>{
      if(el&&el.parentNode===td) el.remove();
      repaintStatic();
      span.style.display='';
      editingTmplId=null;
    };

    const makeOnTab=(shiftKey)=>{
      el.onblur=null; _hideAC();
      doSave();
      closeEditor();
      const t=getNextTmplTarget(td,shiftKey);
      setTimeout(()=>applyTmplTarget(t),80);
    };

    if(field==='category'){
      el=document.createElement('input');el.type='text';el.className='cell-input';el.value=tmpl[field]||'';
      acBind(el, ()=>[...categories].sort(), v=>{ el.value=v; }, makeOnTab);
    }else if(field==='payee'){
      el=document.createElement('input');el.type='text';el.className='cell-input';el.value=tmpl[field]||'';
      acBind(el, ()=>[...payees].sort(), v=>{ el.value=v; }, makeOnTab);
    }else{
      el=document.createElement('input');el.type=type||'text';el.className='cell-input';
      el.value=field==='amount'?parseFloat(tmpl.amount||0).toFixed(2):(tmpl[field]??'');
      if(field==='day_of_month'){el.min=1;el.max=31;}
    }
    td.appendChild(el);el.focus();
    if(el.type!=='date'){try{el.select()}catch(x){}}
    const doSave=()=>{
      let v=el.value;
      if(field==='amount') v=parseFloat(v)||0;
      else if(field==='day_of_month') v=parseInt(v)||null;
      const latest=getTmplById(tmpl.id) || tmpl;
      if(valuesEqual(field, latest[field], v)) return false;
      if(field==='category'&&v) addCat(v);
      if(field==='payee'&&v) addPayee(v);
      updateTmpl(tmpl.id,field,v);
      return true;
    };
    el.onblur=()=>{ _hideAC(); doSave(); closeEditor(); };
    el.onkeydown=ev=>{
      if(ev.key==='Escape'){
        ev.preventDefault();el.onblur=null;_hideAC();closeEditor();
        return;
      }
      if(ev.key==='Tab'){
        ev.preventDefault();
        _acPickFromInput(el);
        makeOnTab(ev.shiftKey);
        return;
      }
      if(ev.key==='Enter'){
        ev.preventDefault();
        if(_acDrop && _acPickFromInput(el)){ makeOnTab(false); return; }
        el.blur();
      }
    };
    e.stopPropagation();
  };
  return td;
}

function renderTmplSection(bodyId, rows){
  const hasEditing=editingTmplId&&rows.some(r=>r.id===editingTmplId);
  const sorted=hasEditing?[...rows]:sortRows(rows, bodyId, 'day_of_month');
  const tbody=document.getElementById(bodyId); tbody.innerHTML='';
  const entryType=bodyId==='tmpl-income-body'?'credit':'debit';
  sorted.forEach(tmpl=>{
    const tr=document.createElement('tr'); tr.className='tmpl-row'; tr.dataset.id=tmpl.id;
    tr.appendChild(makeTmplEC(tmpl,'payee',   'text',  '',sorted));
    tr.appendChild(makeTmplEC(tmpl,'category','text',  ''));
    tr.appendChild(makeTmplEC(tmpl,'day_of_month','number','text-align:center'));
    tr.appendChild(makeTmplEC(tmpl,'amount',  'number','text-align:right'));
    const autoTd=document.createElement('td'); autoTd.style.textAlign='center';
    const aBtn=document.createElement('button');
    aBtn.className='flag-btn'+(tmpl.is_automatic?' on':'');
    aBtn.innerHTML=`<i class="bi bi-lightning${tmpl.is_automatic?'-fill':''}"></i> `
      +`<span style="font-size:11px">${tmpl.is_automatic?'Auto':'Manual'}</span>`;
    aBtn.onclick=()=>updateTmpl(tmpl.id,'is_automatic',tmpl.is_automatic?0:1);
    autoTd.appendChild(aBtn); tr.appendChild(autoTd);
    tr.appendChild(makeTmplEC(tmpl,'notes','text',''));
    const delTd=document.createElement('td');
    const db=document.createElement('button'); db.className='del-btn';
    db.innerHTML='<i class="bi bi-x-lg"></i>'; db.onclick=()=>delTmpl(tmpl.id);
    delTd.appendChild(db); tr.appendChild(delTd);
    tbody.appendChild(tr);
  });
  refreshSortIcons(bodyId);
}
async function updateTmpl(id,field,value){
  const tmpl=getTmplById(id);
  if(!tmpl || valuesEqual(field, tmpl[field], value)) return;

  applyLocalTmplField(id, field, value);
  const patch = {[field]: value};
  if(field==='payee'){
    const tmplNow=getTmplById(id);
    if(tmplNow && !tmplNow.category){
      const def=getPayeeDefaultCategory(value);
      if(def){
        applyLocalTmplField(id, 'category', def);
        patch.category = def;
      }
    }
  }

  const data=await fetch(`/api/templates/${id}`,
    {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)}).then(r=>r.json());
  const i=templates.findIndex(t=>t.id===id);
  if(i!==-1) templates[i]={...templates[i],...data};
  computeTmplBadges();
  if(!hasActiveEditor()){
    renderTemplates();
    renderTransactions();
  }
  refreshSuggestions();
}
async function delTmpl(id){
  await fetch(`/api/templates/${id}`,{method:'DELETE'});
  templates=templates.filter(t=>t.id!==id);
  computeTmplBadges(); renderTemplates(); renderTransactions();
  refreshSuggestions();
}

// ═══════════ ALL TRANSACTIONS VIEW ═══════════

function getAllTxnById(id){
  return allTransactions.find(t=>t.id===id)||null;
}

function applyLocalAllTxnField(id,field,value){
  const i=allTransactions.findIndex(t=>t.id===id);
  if(i===-1) return;
  allTransactions[i]={...allTransactions[i],[field]:value};
  if(field==='payee'&&value) addPayee(value);
  if(field==='category'&&value){
    addCat(value);
    if(allTransactions[i].payee) payeeDefaults[allTransactions[i].payee]=value;
  }
}

function computeAllPayeeBadges(){
  allPayeeBadges={};
  // Badge ordering is per-month, matching the monthly view's behaviour
  const byMonth={};
  for(const t of allTransactions){(byMonth[t.month||'']||=[]).push(t);}
  for(const txns of Object.values(byMonth)){
    const sorted=[...txns].sort((a,b)=>(a.date||'9').localeCompare(b.date||'9')||a.id-b.id);
    const seen={};
    for(const t of sorted){
      const k=`${t.payee}|${t.entry_type}`;seen[k]=(seen[k]||0)+1;allPayeeBadges[t.id]=seen[k];
    }
  }
}

function pushStatusAll(txn){
  const myOrder=allPayeeBadges[txn.id]||1;
  const peers=templates.filter(t=>t.payee===txn.payee&&t.entry_type===txn.entry_type)
    .sort((a,b)=>a.sort_order-b.sort_order||a.id-b.id);
  const match=peers[myOrder-1];
  if(!match) return 'pnew';
  const txnDay=txn.date?parseInt(txn.date.slice(8),10):null;
  const exact=match.category===txn.category&&Math.abs(match.amount-txn.amount)<0.005&&
    match.is_automatic===txn.is_automatic&&(match.notes||'')===(txn.notes||'')&&
    (match.day_of_month==null||txnDay==null||match.day_of_month===txnDay);
  return exact?'pexact':'pdiff';
}

// ── Cell builders for all-transactions view ──────────────────────────────────
function makePayeeAllSpan(txn,section){
  const span=document.createElement('span');
  span.textContent=txn.payee||'';
  const total=section.filter(t=>t.payee===txn.payee&&t.entry_type===txn.entry_type).length;
  if(total>1){
    const b=document.createElement('span');
    b.className='pbadge';b.textContent='#'+(allPayeeBadges[txn.id]||1);span.appendChild(b);
  }
  return span;
}

function makeAllEC(txn,field,type,extraClass,section){
  const td=document.createElement('td');
  td.className='editable '+(extraClass||'');
  let span;
  if(field==='payee'&&section) span=makePayeeAllSpan(txn,section);
  else{
    span=document.createElement('span');
    if(field==='amount') span.innerHTML=fmtTxnAmt(txn.amount,txn.entry_type);
    else if(field==='entry_type') span.textContent=txn.entry_type==='credit'?'Income':'Expense';
    else if(field==='date') span.textContent=txn.date||'';   // full YYYY-MM-DD
    else span.textContent=txn[field]||'';
  }
  td.appendChild(span);

  td.onclick=e=>{
    if(td.querySelector('input,select')) return;
    editingAllTxnId=txn.id;
    span.style.display='none';
    let el;

    const repaintStatic=()=>{
      const latest=getAllTxnById(txn.id)||txn;
      if(field==='payee'&&section){
        span.replaceWith(makePayeeAllSpan(latest,section));
        span=td.querySelector('span');
      }else if(field==='amount'){
        span.innerHTML=fmtTxnAmt(latest.amount,latest.entry_type);
      }else if(field==='entry_type'){
        span.textContent=latest.entry_type==='credit'?'Income':'Expense';
      }else if(field==='date'){
        span.textContent=latest.date||'';
      }else{
        span.textContent=latest[field]||'';
      }
    };

    const closeEditor=()=>{
      if(el&&el.parentNode===td) el.remove();
      repaintStatic();span.style.display='';editingAllTxnId=null;
    };

    const makeOnTab=(shiftKey)=>{
      el.onblur=null;_hideAC();doSave();closeEditor();
      const t=getNextTxnTarget(td,shiftKey);
      if(t&&t.type!=='ghost') setTimeout(()=>applyAllTxnTarget(t),80);
    };

    if(field==='category'){
      el=document.createElement('input');el.type='text';el.className='cell-input';el.value=txn[field]||'';
      acBind(el,()=>[...categories].sort(),v=>{el.value=v;},makeOnTab);
    }else if(field==='payee'){
      el=document.createElement('input');el.type='text';el.className='cell-input';el.value=txn[field]||'';
      acBind(el,()=>[...payees].sort(),v=>{el.value=v;},makeOnTab);
    }else if(field==='entry_type'){
      el=document.createElement('select');el.className='cell-select';
      ['credit','debit'].forEach(v=>{
        const o=document.createElement('option');o.value=v;
        o.textContent=v==='credit'?'Income':'Expense';
        if(v===txn[field]) o.selected=true;el.appendChild(o);});
    }else if(field==='date'){
      // Full YYYY-MM-DD date input
      el=document.createElement('input');el.type='date';el.className='cell-input';
      el.value=txn.date||'';
    }else{
      el=document.createElement('input');el.type=type||'text';el.className='cell-input';
      el.value=field==='amount'?txn.amount.toFixed(2):(txn[field]||'');
    }
    td.appendChild(el);el.focus();
    if(el.tagName==='INPUT'&&el.type!=='date'){try{el.select();}catch(x){}}

    const doSave=()=>{
      let v=field==='amount'?parseFloat(el.value)||0:el.value;
      // Date is already YYYY-MM-DD — no reconstruction needed
      const latest=getAllTxnById(txn.id)||txn;
      if(valuesEqual(field,latest[field],v)) return false;
      if(field==='category'&&v) addCat(v);
      if(field==='payee'&&v) addPayee(v);
      updateAllField(txn.id,field,v);
      return true;
    };
    el.onblur=()=>{_hideAC();doSave();closeEditor();};
    el.onkeydown=ev=>{
      if(ev.key==='Escape'){ev.preventDefault();el.onblur=null;_hideAC();closeEditor();return;}
      if(ev.key==='Tab'){ev.preventDefault();_acPickFromInput(el);makeOnTab(ev.shiftKey);return;}
      if(ev.key==='Enter'){
        ev.preventDefault();
        if(_acDrop&&_acPickFromInput(el)){ makeOnTab(false); return; }
        el.blur();
      }
    };
    e.stopPropagation();
  };
  return td;
}

function makeAllFlagCell(txn){
  const td=document.createElement('td');td.className='w-fl';
  const btn=document.createElement('button');
  btn.className='flag-btn'+(txn.is_automatic?' on':'');
  btn.innerHTML=`<i class="bi bi-lightning${txn.is_automatic?'-fill':''}"></i>`;
  btn.onclick=()=>updateAllField(txn.id,'is_automatic',txn.is_automatic?0:1);
  td.appendChild(btn);return td;
}

function makeAllStatusCell(txn){
  const td=document.createElement('td');td.className='w-st';
  const div=document.createElement('div');div.className='status-group';
  [['estimated','Est','ae'],['actual','Act','aa'],['reconciled','Rec','ar']].forEach(([key,lbl,cls])=>{
    const b=document.createElement('button');
    b.className='sb'+(txn.status===key?' '+cls:'');b.textContent=lbl;
    b.onclick=()=>updateAllField(txn.id,'status',key);div.appendChild(b);
  });
  td.appendChild(div);return td;
}

function makeAllPushCell(txn){
  const td=document.createElement('td');td.className='w-fl';
  const st=pushStatusAll(txn);
  const btn=document.createElement('button');btn.className=`push-btn ${st}`;
  const icons={pnew:'bi-arrow-right-circle',pdiff:'bi-arrow-right-circle-fill',pexact:'bi-check-circle-fill'};
  const titles={pnew:'Not in template — click to add',pdiff:'In template (values differ) — click to update',pexact:'In template (exact match)'};
  btn.innerHTML=`<i class="bi ${icons[st]}"></i>`;btn.title=titles[st];
  if(st!=='pexact') btn.onclick=()=>doPushToTemplateAll(txn.id);
  td.appendChild(btn);return td;
}

// ── Tab navigation for all-view ──────────────────────────────────────────────
function applyAllTxnTarget(t){
  if(!t) return;
  if(t.type==='ghost'){
    // Tab reaches ghost tfoot — focus the date input naturally
    const el=document.getElementById('gia-date');
    if(el) el.focus();
    return;
  }
  const tbody=document.getElementById('all-body');
  if(!tbody) return;
  const row=tbody.querySelector(`tr.txn-row[data-id="${t.txnId}"]`);
  if(row){const eds=row.querySelectorAll('td.editable');if(eds[t.fieldIdx]) eds[t.fieldIdx].click();}
}

// ── Render ───────────────────────────────────────────────────────────────────
function renderAllBody(rows){
  const hasEditing=editingAllTxnId&&rows.some(r=>r.id===editingAllTxnId);
  const sorted=hasEditing?[...rows]:sortRows(rows,'all-body','date');
  const tbody=document.getElementById('all-body');tbody.innerHTML='';
  sorted.forEach(txn=>{
    const tr=document.createElement('tr');tr.className='txn-row';tr.dataset.id=txn.id;
    tr.appendChild(makeAllEC(txn,'date','date','w-dt-full'));
    tr.appendChild(makeAllEC(txn,'entry_type','text','w-etype'));
    tr.appendChild(makeAllEC(txn,'payee','text','w-py',sorted));
    tr.appendChild(makeAllEC(txn,'category','text','w-ca'));
    tr.appendChild(makeAllEC(txn,'amount','number','w-am'));
    tr.appendChild(makeAllEC(txn,'notes','text','w-no'));
    tr.appendChild(makeAllStatusCell(txn));
    tr.appendChild(makeAllFlagCell(txn));
    tr.appendChild(makeAllPushCell(txn));
    const delTd=document.createElement('td');delTd.className='w-de';
    const db=document.createElement('button');db.className='del-btn';
    db.innerHTML='<i class="bi bi-x-lg"></i>';db.onclick=()=>delAllTxn(txn.id);
    delTd.appendChild(db);tr.appendChild(delTd);
    tbody.appendChild(tr);
  });
  refreshSortIcons('all-body');
}

function renderAllTransactions(){
  const filtered=applyAllFilters(allTransactions);
  renderAllBody(filtered);
  updateAllFilterBadge();
  updateResultCount(allTransactions.length,filtered.length);
  renderAllChart();
}

// ── Mutations ────────────────────────────────────────────────────────────────
async function updateAllField(id,field,value){
  const txn=getAllTxnById(id);
  if(!txn||valuesEqual(field,txn[field],value)) return;
  applyLocalAllTxnField(id,field,value);
  const patch={[field]:value};
  if(field==='payee'){
    const now=getAllTxnById(id);
    if(now&&!now.category){
      const def=getPayeeDefaultCategory(value);
      if(def){applyLocalAllTxnField(id,'category',def);patch.category=def;}
    }
  }
  const data=await resilientApiFetch(`/api/transactions/${id}`,
    {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)}).then(r=>r.json());
  const i=allTransactions.findIndex(t=>t.id===id);
  if(i!==-1) allTransactions[i]={...allTransactions[i],...data};
  computeAllPayeeBadges();
  if(!hasActiveEditor()) renderAllTransactions();
  refreshSuggestions();
}

async function delAllTxn(id){
  await resilientApiFetch(`/api/transactions/${id}`,{method:'DELETE'});
  const txn=getAllTxnById(id);
  if(txn&&txn.month) monthCounts[txn.month]=Math.max(0,(monthCounts[txn.month]||1)-1);
  allTransactions=allTransactions.filter(t=>t.id!==id);
  computeAllPayeeBadges();renderAllTransactions();
}


async function doPushToTemplateAll(txnId){
  await resilientApiFetch(`/api/transactions/${txnId}/to-template`,{method:'POST'});
  templates=await resilientApiFetch('/api/templates').then(r=>r.json());
  templates.forEach(t=>{if(t.category)addCat(t.category);if(t.payee)addPayee(t.payee);});
  computeTmplBadges();computeAllPayeeBadges();renderAllTransactions();
  toast('Pushed to Template Builder');
}

// ── Filters ──────────────────────────────────────────────────────────────────
const allFilterState={
  search:'', dateFrom:'', dateTo:'',
  categories:new Set(),   // empty = all
  statuses:new Set(),     // empty = all
  entryType:'both',
  amountMin:'', amountMax:'',
};

function applyAllFilters(rows){
  const {search,dateFrom,dateTo,categories,statuses,entryType,amountMin,amountMax}=allFilterState;
  const q=search.trim().toLowerCase();
  return rows.filter(t=>{
    if(q && ![(t.payee||''),(t.category||''),(t.notes||'')].some(s=>s.toLowerCase().includes(q))) return false;
    if(dateFrom && t.date && t.date<dateFrom) return false;
    if(dateTo   && t.date && t.date>dateTo)   return false;
    if(categories.size && !categories.has(t.category||'')) return false;
    if(statuses.size   && !statuses.has(t.status||''))     return false;
    if(entryType!=='both' && t.entry_type!==entryType)     return false;
    const amt=Math.abs(parseFloat(t.amount||0));
    if(amountMin!=='' && amt<parseFloat(amountMin)) return false;
    if(amountMax!=='' && amt>parseFloat(amountMax)) return false;
    return true;
  });
}

function countActiveFilters(){
  const f=allFilterState;
  return (f.search?1:0)+(f.dateFrom?1:0)+(f.dateTo?1:0)+
         (f.categories.size?1:0)+(f.statuses.size?1:0)+
         (f.entryType!=='both'?1:0)+(f.amountMin!==''?1:0)+(f.amountMax!==''?1:0);
}

function updateAllFilterBadge(){
  const n=countActiveFilters();
  const badge=document.getElementById('all-filter-badge');
  if(!badge) return;
  if(n){badge.textContent=n;badge.style.display='';}
  else badge.style.display='none';
}

function updateResultCount(total,shown){
  const el=document.getElementById('all-result-count');
  if(!el) return;
  if(countActiveFilters()===0){el.textContent='';return;}
  el.textContent=`${shown} of ${total}`;
}

function exportAllCSV(){
  const rows = applyAllFilters(allTransactions);
  const cols = [
    {key:'date',       label:'Date'},
    {key:'entry_type', label:'Type',     fmt:v=>v==='credit'?'Income':'Expense'},
    {key:'payee',      label:'Payee'},
    {key:'category',   label:'Category'},
    {key:'amount',     label:'Amount',   fmt:v=>parseFloat(v||0).toFixed(2)},
    {key:'status',     label:'Status'},
    {key:'recurs_monthly', label:'Recurring', fmt:v=>v?'Yes':'No'},
    {key:'is_automatic',   label:'Auto Pay',  fmt:v=>v?'Yes':'No'},
    {key:'notes',      label:'Memo'},
    {key:'month',      label:'Month'},
  ];
  const esc = v => {
    const s = String(v??'');
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g,'""')}"` : s;
  };
  const header = cols.map(c=>c.label).join(',');
  const lines  = rows.map(r=>
    cols.map(c=>esc(c.fmt ? c.fmt(r[c.key]) : (r[c.key]??''))).join(',')
  );
  const csv    = [header, ...lines].join('\r\n');
  const blob   = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const url    = URL.createObjectURL(blob);
  const a      = document.createElement('a');
  const now    = new Date();
  const stamp  = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}`;
  a.href       = url;
  a.download   = `transactions_${stamp}.csv`;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  setTimeout(()=>URL.revokeObjectURL(url), 5000);
}

// Filter bar toggle
function toggleAllFilterBar(){
  document.getElementById('all-filter-bar').classList.toggle('open');
}

// Handlers wired to inputs
function onAllFilterChange(){
  allFilterState.search   =document.getElementById('af-search').value;
  allFilterState.dateFrom =document.getElementById('af-from').value;
  allFilterState.dateTo   =document.getElementById('af-to').value;
  const mn=document.getElementById('af-min').value;
  const mx=document.getElementById('af-max').value;
  allFilterState.amountMin=mn===''?'':parseFloat(mn);
  allFilterState.amountMax=mx===''?'':parseFloat(mx);
  renderAllTransactions();
}

function toggleAllStatus(s){
  if(allFilterState.statuses.has(s)) allFilterState.statuses.delete(s);
  else allFilterState.statuses.add(s);
  document.getElementById(`af-st-${s}`).classList.toggle('on',allFilterState.statuses.has(s));
  renderAllTransactions();
}

function setAllEntryType(t){
  allFilterState.entryType=t;
  ['both','credit','debit'].forEach(v=>{
    const btn=document.getElementById(`af-ty-${v}`);
    if(btn) btn.classList.toggle('on',v===t);
  });
  renderAllTransactions();
}

// Category dropdown
function buildAllCatDropdown(){
  const list=document.getElementById('af-cat-list');
  if(!list) return;
  // Collect unique categories from allTransactions
  const cats=[...new Set(allTransactions.map(t=>t.category||'').filter(Boolean))].sort();
  list.innerHTML='';
  cats.forEach(cat=>{
    const item=document.createElement('label');
    item.className='fcat-item';
    const cb=document.createElement('input');
    cb.type='checkbox'; cb.value=cat;
    cb.checked=allFilterState.categories.has(cat);
    cb.onchange=()=>{
      if(cb.checked) allFilterState.categories.add(cat);
      else allFilterState.categories.delete(cat);
      updateCatLabel(); renderAllTransactions();
    };
    item.appendChild(cb);
    item.appendChild(document.createTextNode(cat));
    list.appendChild(item);
  });
}

function updateCatLabel(){
  const el=document.getElementById('af-cat-label');
  if(!el) return;
  const n=allFilterState.categories.size;
  el.textContent=n===0?'All categories':n===1?[...allFilterState.categories][0]:`${n} categories`;
}

function toggleAllCatDropdown(e){
  e.stopPropagation();
  buildAllCatDropdown();
  document.getElementById('af-cat-list').classList.toggle('open');
}

// Close category dropdown when clicking outside
document.addEventListener('click',e=>{
  const wrap=document.getElementById('af-cat-wrap');
  if(wrap && !wrap.contains(e.target)){
    const list=document.getElementById('af-cat-list');
    if(list) list.classList.remove('open');
  }
});

function clearAllFilters(){
  allFilterState.search=''; allFilterState.dateFrom=''; allFilterState.dateTo='';
  allFilterState.categories.clear(); allFilterState.statuses.clear();
  allFilterState.entryType='both';
  allFilterState.amountMin=''; allFilterState.amountMax='';
  // Reset form controls
  ['af-search','af-from','af-to','af-min','af-max'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.value='';
  });
  ['estimated','actual','reconciled'].forEach(s=>{
    const btn=document.getElementById(`af-st-${s}`);if(btn) btn.classList.remove('on');
  });
  setAllEntryType('both');
  updateCatLabel();
  renderAllTransactions();
}

async function loadAllTransactions(){
  resetSortState(['all-body'],'date');
  allTransactions=await resilientApiFetch('/api/transactions/all').then(r=>r.json());
  allTransactions.forEach(t=>{if(t.category)addCat(t.category);if(t.payee)addPayee(t.payee);});
  computeAllPayeeBadges();renderAllTransactions();
}

// ═══════════ GHOST ROW COMMIT ═══════════
async function commitGhostTmpl(entryType){
  const p = entryType==='credit' ? 'gt-inc' : 'gt-exp';
  const payee    = document.getElementById(`${p}-payee`).value.trim();
  const category = document.getElementById(`${p}-cat`).value.trim();
  const dayRaw   = parseInt(document.getElementById(`${p}-day`).value,10)||1;
  const day      = Math.max(1,Math.min(31,dayRaw));
  const amount   = parseFloat(document.getElementById(`${p}-amount`).value)||0;
  const isAuto   = parseInt(document.getElementById(`${p}-auto`).value,10)||0;
  const notes    = document.getElementById(`${p}-notes`).value.trim();
  const body = {payee,category,entry_type:entryType,amount,day_of_month:day,is_automatic:isAuto,notes};
  try{
    const created = await resilientApiFetch('/api/templates',
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    templates.push(created);
    if(payee) addPayee(payee);
    if(category){ addCat(category); if(payee) payeeDefaults[payee]=category; }
    computeTmplBadges(); renderTemplates(); updateTmplNet();
    clearGhostTmpl(entryType);
    document.getElementById(`${p}-payee`).focus();
  }catch(e){ console.error('commitGhostTmpl',e); }
}
function clearGhostTmpl(entryType){
  const p = entryType==='credit' ? 'gt-inc' : 'gt-exp';
  ['payee','cat','day','amount','notes'].forEach(f=>{
    const el=document.getElementById(`${p}-${f}`); if(el) el.value='';
  });
  const autoEl=document.getElementById(`${p}-auto`); if(autoEl) autoEl.value='0';
}
async function commitGhostMonthly(entryType){
  const p = entryType==='credit' ? 'gi-inc' : 'gi-exp';
  const [yr,mo] = currentMonth.split('-');
  const lastDay = new Date(+yr,+mo,0).getDate();
  const dayRaw = parseInt(document.getElementById(`${p}-date`).value,10)||0;
  const day = dayRaw>0 ? Math.min(dayRaw,lastDay) : 1;
  const fullDate = `${currentMonth}-${String(day).padStart(2,'0')}`;
  const payee    = document.getElementById(`${p}-payee`).value.trim();
  const category = document.getElementById(`${p}-cat`).value.trim();
  const amount   = parseFloat(document.getElementById(`${p}-amount`).value)||0;
  const notes    = document.getElementById(`${p}-notes`).value.trim();
  const body = {date:fullDate,payee,category,amount,entry_type:entryType,
                status:'estimated',is_adhoc:0,recurs_monthly:0,is_automatic:0,notes,sort_order:0};
  try{
    const created = await resilientApiFetch(`/api/months/${currentMonth}/transactions`,
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    transactions.push(created);
    if(payee) addPayee(payee);
    if(category){ addCat(category); if(payee) payeeDefaults[payee]=category; }
    monthCounts[currentMonth]=(monthCounts[currentMonth]||0)+1;
    buildCarousel(); computePayeeBadges(); renderTransactions(); refreshBalances();
    clearGhostMonthly(entryType);
    document.getElementById(`${p}-date`).focus();
  }catch(e){ console.error('commitGhostMonthly',e); }
}
function clearGhostMonthly(entryType){
  const p = entryType==='credit' ? 'gi-inc' : 'gi-exp';
  ['date','payee','cat','amount','notes'].forEach(f=>{
    const el=document.getElementById(`${p}-${f}`); if(el) el.value='';
  });
}
async function commitGhostAll(){
  const date=document.getElementById('gia-date').value.trim();
  if(!date){ document.getElementById('gia-date').focus(); return; }
  const entryType=document.getElementById('gia-type').value;
  const payee    =document.getElementById('gia-payee').value.trim();
  const category =document.getElementById('gia-cat').value.trim();
  const amount   =parseFloat(document.getElementById('gia-amount').value)||0;
  const notes    =document.getElementById('gia-notes').value.trim();
  const body={date,payee,category,amount,entry_type:entryType,status:'estimated',
              is_adhoc:0,recurs_monthly:0,is_automatic:0,notes,sort_order:0};
  try{
    const created=await resilientApiFetch('/api/transactions',
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    allTransactions.push(created);
    if(payee) addPayee(payee);
    if(category){ addCat(category); if(payee) payeeDefaults[payee]=category; }
    if(created.month) monthCounts[created.month]=(monthCounts[created.month]||0)+1;
    computeAllPayeeBadges(); renderAllTransactions();
    clearGhostAll();
    document.getElementById('gia-date').focus();
  }catch(e){ console.error('commitGhostAll',e); }
}
function clearGhostAll(){
  ['date','payee','cat','amount','notes'].forEach(f=>{
    const el=document.getElementById(`gia-${f}`); if(el) el.value='';
  });
}
function initGhostRows(){
  // Wire autocomplete + Enter/Tab handling for a ghost row's inputs.
  // When dropdown is open: Enter/Tab pick the highlighted item and advance to the next field.
  // When dropdown is closed: Enter commits the row; Tab on the last field commits the row.
  const wire=(pfx, inputIds, commitFn)=>{
    const payeeEl=document.getElementById(`${pfx}-payee`);
    const catEl  =document.getElementById(`${pfx}-cat`);
    if(payeeEl) acBind(payeeEl,()=>[...payees].sort(),v=>{ payeeEl.value=v; },null);
    if(catEl)   acBind(catEl,  ()=>[...categories].sort(),v=>{ catEl.value=v; },null);
    inputIds.forEach((id, i)=>{
      const el=document.getElementById(id); if(!el) return;
      const isLast = i === inputIds.length - 1;
      const focusNext=()=>{
        const nextId=inputIds[i+1];
        if(nextId) document.getElementById(nextId)?.focus();
      };
      el.addEventListener('keydown',ev=>{
        if(ev.key==='Enter'){
          ev.preventDefault();
          if(_acDrop){ _acPickFromInput(el); if(!isLast) focusNext(); else commitFn(); }
          else { commitFn(); }
          return;
        }
        if(ev.key==='Tab' && !ev.shiftKey){
          if(_acDrop){ ev.preventDefault(); _acPickFromInput(el); if(!isLast) focusNext(); else commitFn(); return; }
          if(isLast){ ev.preventDefault(); commitFn(); }
        }
      });
    });
  };
  // Monthly view ghost rows
  wire('gi-inc', ['gi-inc-date','gi-inc-payee','gi-inc-cat','gi-inc-amount','gi-inc-notes'],
    ()=>commitGhostMonthly('credit'));
  wire('gi-exp', ['gi-exp-date','gi-exp-payee','gi-exp-cat','gi-exp-amount','gi-exp-notes'],
    ()=>commitGhostMonthly('debit'));
  // Template builder ghost rows
  wire('gt-inc', ['gt-inc-payee','gt-inc-cat','gt-inc-day','gt-inc-amount','gt-inc-auto','gt-inc-notes'],
    ()=>commitGhostTmpl('credit'));
  wire('gt-exp', ['gt-exp-payee','gt-exp-cat','gt-exp-day','gt-exp-amount','gt-exp-auto','gt-exp-notes'],
    ()=>commitGhostTmpl('debit'));
  // All-transactions ghost row
  const giaPayee=document.getElementById('gia-payee');
  const giaCat  =document.getElementById('gia-cat');
  if(giaPayee) acBind(giaPayee,()=>[...payees].sort(),v=>{ giaPayee.value=v; },null);
  if(giaCat)   acBind(giaCat,  ()=>[...categories].sort(),v=>{ giaCat.value=v; },null);
  const giaIds=['gia-date','gia-payee','gia-cat','gia-amount','gia-notes'];
  giaIds.forEach((id, i)=>{
    const el=document.getElementById(id); if(!el) return;
    const isLast = i === giaIds.length - 1;
    const focusNext=()=>{
      const nextId=giaIds[i+1];
      if(nextId) document.getElementById(nextId)?.focus();
    };
    el.addEventListener('keydown',ev=>{
      if(ev.key==='Enter'){
        ev.preventDefault();
        if(_acDrop){ _acPickFromInput(el); if(!isLast) focusNext(); else commitGhostAll(); }
        else { commitGhostAll(); }
        return;
      }
      if(ev.key==='Tab' && !ev.shiftKey){
        if(_acDrop){ ev.preventDefault(); _acPickFromInput(el); if(!isLast) focusNext(); else commitGhostAll(); return; }
        if(isLast){ ev.preventDefault(); commitGhostAll(); }
      }
    });
  });
}

// ═══════════ INIT ═══════════
(async function init(){
  const today=new Date();
  currentMonth=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`;
  buildJumpPicker();
  // Initialize default sort states
  resetSortState(['income-body','expense-body'],'date');
  resetSortState(['tmpl-income-body','tmpl-expense-body'],'day_of_month');
  const[cats,counts,tmpls,payeeList,pd]=await Promise.all([
    fetch('/api/categories').then(r=>r.json()).catch(()=>[]),
    fetch('/api/months/list').then(r=>r.json()).catch(()=>({})),
    fetch('/api/templates').then(r=>r.json()).catch(()=>[]),
    fetch('/api/payees').then(r=>r.json()).catch(()=>[]),
    fetch('/api/payee-defaults').then(r=>r.json()).catch(()=>({})),
  ]);
  cats.forEach(c=>c&&addCat(c));
  payeeList.forEach(p=>p&&addPayee(p));
  payeeDefaults=pd;
  monthCounts=counts;
  templates=tmpls;
  templates.forEach(t=>{if(t.category)addCat(t.category);if(t.payee)addPayee(t.payee);});
  computeTmplBadges();
  buildCarousel();
  initGhostRows();
  await loadMonth(currentMonth);
  loadGlobalBalance();
})();

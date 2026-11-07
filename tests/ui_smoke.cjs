/* Optional DOM smoke test: NODE_PATH=<jsdom node_modules> node tests/ui_smoke.cjs.
   Uses real backend calculations with synthetic books; no live exchange calls. */
const {JSDOM}=require('jsdom');
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const fixture=JSON.parse(execFileSync('.venv/bin/python',['-c',`
import json, tempfile, time
from app.main import Settings, ScannerSettings
from app.scanner import Scanner
from app.storage import Storage
from app.fetchers import Book
from app.opportunities import statistics
with tempfile.TemporaryDirectory() as d:
 s=Scanner(Storage(d+'/ui.db')); now=time.time()
 cfg=ScannerSettings(trading_mode='prefunded',capital_usdt=100,capital_toman=1000,row_modes={'ETH:toman:wallex:nobitex':'transfer'}).model_dump()
 s.store.save_scanner_settings(cfg)
 s.store.replace_fees([dict(exchange=e,coin='ETH',network='ERC20',withdrawal=0,minimum=0,supported=True) for e in ('wallex','nobitex')])
 settings=Settings(wallex=dict(maker=0,taker=0,withdrawal=0),nobitex=dict(maker=0,taker=0,withdrawal=0),wallex_usdt=dict(maker=0,taker=0),nobitex_usdt=dict(maker=0,taker=0))
 for c,q,ask,bid in [('BTC','USDT',10,11),('ETH','toman',100,100.2)]:
  s.markets.append(dict(coin=c,quote=q,wallex=c,nobitex=c))
  s.tickers[c,q]=dict(wallex_ask=ask,wallex_bid=ask-.1,nobitex_ask=bid+.1,nobitex_bid=bid,timestamp=now)
  s.depth[c,q]=dict(wallex=Book([(ask,1000)],[(ask-.1,1000)],now),nobitex=Book([(bid+.1,1000)],[(bid,1000)],now),timestamp=now)
 print(json.dumps(dict(snapshot=dict(rows=s.rows(settings),excluded=[],settings=cfg),settings=settings.model_dump(),stats=dict(overall=statistics([],None),coins={},transfer_minutes=None))))
`],{encoding:'utf8'}));
const dom=new JSDOM(fs.readFileSync('app/static/overview.html','utf8'),{runScripts:'outside-only',url:'http://fixture.test/overview'});
const w=dom.window;
let cfg=structuredClone(fixture.snapshot.settings), settings=structuredClone(fixture.settings), saves=0;
w.setTimeout=()=>1;w.clearTimeout=()=>{};w.confirm=()=>true;
w.Element.prototype.scrollIntoView=function(){};
w.HTMLElement.prototype.focus=w.HTMLElement.prototype.focus||function(){};
w.fetch=async(url,opts={})=>{let value;
 if(url==='/api/scanner/settings'){if(opts.method==='PUT'){cfg=JSON.parse(opts.body);saves++}value=cfg}
 else if(url==='/api/settings'){if(opts.method==='PUT'){settings=JSON.parse(opts.body);saves++}value=settings}
 else if(url==='/api/scanner/fees')value=[];
 else if(url==='/api/scanner')value={...fixture.snapshot,settings:cfg};
 else if(url.startsWith('/api/scanner/detail/'))value={rows:fixture.snapshot.rows,books:{wallex:{asks:[[10,100]],bids:[[9,100]]},nobitex:{asks:[[12,100]],bids:[[11,100]]}},history:[]};
 else if(url.startsWith('/api/opportunities?'))value=fixture.stats;
 else throw Error('Unexpected URL '+url);
 return {ok:true,status:200,text:async()=>JSON.stringify(value),json:async()=>structuredClone(value)};
};
const ctx=dom.getInternalVMContext();
for(const file of ['advanced.js','overview.js','options.js'])vm.runInContext(fs.readFileSync('app/static/'+file,'utf8'),ctx,{filename:file});
async function settle(){for(let i=0;i<40;i++)await Promise.resolve()}
(async()=>{await settle();
 const doc=w.document;
 assert.equal(doc.querySelectorAll('#rows tr').length,4);
 assert.equal(doc.querySelectorAll('[data-row-mode]').length,4);
 assert.match(doc.querySelector('#rows').textContent,/پایین‌تر از حاشیه ایمنی/);
 assert.ok(doc.querySelector('#rows .yellow'));
 assert.equal(doc.querySelector('#globalMode').value,'prefunded');
 assert.equal(doc.querySelectorAll('#tierRows tr').length,0);
 await vm.runInContext("openDetail('BTC','USDT')",ctx);await settle();
 assert.match(doc.querySelector('#detailBody').textContent,/هزینه جداگانه بازتوازن/);
 assert.match(doc.querySelector('#detailBody').textContent,/هزینه بازتوازن نامعلوم/);
 assert.match(doc.querySelector('#detailBody').textContent,/موجودی‌ها محدود نشده‌اند/);
 doc.querySelector('#closeDetail').click();
 assert.equal(doc.querySelector('#detail').hidden,true);
 await vm.runInContext("openDetail('BTC','USDT')",ctx);await settle();
 assert.equal(doc.querySelector('#detail').hidden,false);
 doc.querySelector('#statsTab').click();await settle();
 assert.equal(doc.querySelector('#statistics').hidden,false);
 doc.querySelector('#marketTab').click();await settle();
 assert.equal(doc.querySelector('#statistics').hidden,true);
 assert.match(doc.querySelector('#statsBody').textContent,/میانه/);
 await doc.querySelector('#modeForm').onsubmit({preventDefault(){}});await settle();
 assert.equal(saves,1);assert.equal(cfg.safety_margin,.3);
 const selector=doc.querySelector('[data-row-mode]');selector.value='transfer';await selector.onchange();await settle();
 assert.equal(cfg.row_modes[selector.dataset.rowMode],'transfer');
 assert.equal(doc.querySelector('#message').textContent,'');
 const realFetch=w.fetch;
 w.fetch=async()=>({ok:false,status:500,text:async()=>'Internal Server Error'});
 await vm.runInContext('update()',ctx);await settle();
 assert.match(doc.querySelector('#message').textContent,/خطای داخلی سرور/);
 assert.doesNotMatch(doc.querySelector('#message').textContent,/Internal Server Error/i);
 w.fetch=async()=>({ok:false,status:429,text:async()=>'Too Many Requests'});
 await vm.runInContext('update()',ctx);await settle();
 assert.match(doc.querySelector('#message').textContent,/درخواست‌های زیادی/);
 w.fetch=async()=>({ok:false,status:503,text:async()=>JSON.stringify({detail:'سرویس در دسترس نیست.'})});
 await vm.runInContext('update()',ctx);await settle();
 assert.match(doc.querySelector('#message').textContent,/سرویس در دسترس نیست/);
 w.fetch=async()=>{throw new TypeError('Failed to fetch')};
 await vm.runInContext('update()',ctx);await settle();
 assert.match(doc.querySelector('#message').textContent,/اتصال به سرور/);
 w.fetch=realFetch;
 await vm.runInContext('update()',ctx);await settle();
 assert.equal(doc.querySelectorAll('#rows tr').length,4);
 console.log('DOM smoke passed: overview, safety color, detail open/close, statistics, policy save, per-row mode, Persian server errors.');
 dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1});

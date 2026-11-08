"use strict";
const $app = document.getElementById("app"), $tip = document.getElementById("tip");
let S = {user:null, ocr:false, today:""};

/* Hilfen -------------------------------------------------------------- */
function h(tag, attrs, ...kids){
  const el = document.createElement(tag);
  for(const [k,v] of Object.entries(attrs||{})){
    if(v==null||v===false) continue;
    if(k.startsWith("on")) el.addEventListener(k.slice(2),v);
    else if(k==="class") el.className=v;
    else if(k==="html") el.innerHTML=v;
    else if(k in el && k!=="list") el[k]=v;
    else el.setAttribute(k,v===true?"":v);
  }
  for(const kid of kids.flat(Infinity)) if(kid!=null&&kid!==false) el.append(kid.nodeType?kid:String(kid));
  return el;
}
const svgNS="http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids){
  const el=document.createElementNS(svgNS,tag);
  for(const [k,v] of Object.entries(attrs||{})) if(v!=null) el.setAttribute(k,v);
  el.append(...kids.flat().filter(x=>x!=null));
  return el;
}
async function api(url, opt={}){
  const o={method:opt.method||"GET",headers:{"X-Zaehler":"1"}};
  if(opt.form) o.body=opt.form;
  else if(opt.json!==undefined){o.body=JSON.stringify(opt.json);o.headers["Content-Type"]="application/json"}
  let res;
  try{res=await fetch(url,o)}catch(e){throw Object.assign(new Error("Keine Verbindung zum Server."),{status:0})}
  const data=await res.json().catch(()=>({}));
  if(res.status===401&&!url.includes("/login")){S.user=null;render();}
  if(!res.ok) throw Object.assign(new Error(data.error||"Das hat nicht geklappt."),{status:res.status,data});
  return data;
}
const num=(v,d=3)=>v==null?"–":Number(v).toLocaleString("de-DE",{minimumFractionDigits:d,maximumFractionDigits:d});
const date=iso=>{if(!iso)return"–";const[y,m,d]=iso.slice(0,10).split("-");return`${d}.${m}.${y}`};
const dateShort=iso=>{const[,m,d]=iso.slice(0,10).split("-");return`${d}.${m}.`};
const stamp=iso=>{if(!iso)return"–";const t=iso.slice(11,16);return`${date(iso)}, ${t} Uhr`};
const MONTHS=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
const MON=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
const monthName=key=>{const[y,m]=key.split("-");return`${MONTHS[m-1]} ${y}`};
const cls=m=>`c-${m.color}`;
const rate=(m)=>`${m.unit}/Tag`;
function errorBox(el,e){el.replaceChildren(h("p",{class:"err",role:"alert"},e.message||String(e)))}

function drum(value,dec,unit,size=""){
  const txt=value==null||value===""?"":Number(value).toFixed(dec);
  const [i="",f=""]=txt.split(".");
  const width=Math.max(5,i.length);
  const lead=width-i.length;
  const cells=[];
  for(let n=0;n<width;n++){const ch=n<lead?"0":i[n-lead];cells.push(h("span",{class:"d"+(n<lead?" lead":"")},h("span",null,txt?ch:"0")))}
  for(let n=0;n<dec;n++)cells.push(h("span",{class:"d dec"},h("span",null,f[n]||"0")));
  return h("span",{class:`drum ${size}`,role:"img","aria-label":txt?`${num(value,dec)} ${unit}`:`kein Stand ${unit}`},cells,unit?h("span",{class:"u"},unit):null);
}

/* Rahmen -------------------------------------------------------------- */
function shell(active,...content){
  const items=[["#/","Übersicht","home"]];
  if(S.user.record)items.push(["#/ablesen","Ablesen","read"]);
  items.push(["#/verlauf","Verlauf","log"],["#/statistik","Statistik","stats"],["#/mehr","Mehr","more"]);
  return h("div",{class:"shell"},
    h("header",{class:"top"},h("a",{class:"brand",href:"#/"},"Zählerstand"),
      h("nav",{class:"nav","aria-label":"Hauptmenü"},items.map(([href,t,key])=>h("a",{href,"aria-current":key===active?"page":null},t)))),
    h("main",null,content));
}
function loading(active){ $app.replaceChildren(shell(active,h("p",{class:"muted"},"Wird geladen …"))) }

/* Router -------------------------------------------------------------- */
async function render(){
  closeTip();
  if(!S.user&&!S.setup){return viewLogin()}
  if(S.setup){return viewSetup()}
  const [,route="",arg]=location.hash.replace(/^#/,"").split("/");
  const views={"":viewHome,ablesen:viewRead,verlauf:viewLog,statistik:viewStats,mehr:viewMore,nachweis:viewProof,verwaltung:viewAdmin,konto:viewAccount};
  const view=views[route]||viewHome;
  try{await view(arg)}catch(e){
    if(e.status===401)return;
    $app.replaceChildren(shell("",h("div",{class:"panel"},h("p",{class:"err"},e.message))));
  }
}
addEventListener("hashchange",()=>{scrollTo(0,0);render()});
let rz;addEventListener("resize",()=>{clearTimeout(rz);rz=setTimeout(()=>{if(location.hash.startsWith("#/statistik"))render()},250)});

/* Anmeldung ------------------------------------------------------------ */
function authForm(title,intro,fields,submit,run){
  const msg=h("div");
  const form=h("form",{class:"panel login stack",onsubmit:async ev=>{
    ev.preventDefault();msg.replaceChildren();
    try{await run(Object.fromEntries(new FormData(form)));await boot()}catch(e){errorBox(msg,e)}
  }},h("h1",null,title),intro&&h("p",{class:"muted"},intro),fields,msg,h("button",{class:"btn wide",type:"submit"},submit));
  $app.replaceChildren(h("div",{class:"shell"},form));
}
const field=(label,name,type="text",extra={})=>h("label",{class:"field"},label,h("input",{name,type,required:true,...extra}));
function oidcBox(text){
  const o=S.oidc||{};
  if(!o.enabled)return null;
  const err=new URLSearchParams(location.search).get("fehler");
  return h("div",{class:"panel login stack"},h("h1",null,text),err&&h("p",{class:"err"},err),
    h("a",{class:"btn wide",href:"/auth/pocketid?next="+encodeURIComponent("/"+location.hash)},o.label));
}
function viewLogin(){
  const o=S.oidc||{},params=new URLSearchParams(location.search);
  if(o.auto_redirect&&!params.get("fehler")){location.href="/auth/pocketid?next="+encodeURIComponent("/"+location.hash);return}
  const box=oidcBox("Zählerstand");
  if(box&&!o.password_login){$app.replaceChildren(h("div",{class:"shell"},box));return}
  authForm(box?"Mit Passwort":"Zählerstand",null,[field("Benutzername","username","text",{autocomplete:"username",autocapitalize:"none"}),
    field("Passwort","password","password",{autocomplete:"current-password"})],"Anmelden",
    d=>api("/api/login",{method:"POST",json:d}));
  if(box)$app.firstChild.prepend(box);
}
function viewSetup(){
  authForm("Einrichten","Lege dein Admin-Konto an. Es sieht als einziges den privaten Zähler.",
    [field("Dein Name","name"),field("Benutzername","username","text",{autocomplete:"username",autocapitalize:"none"}),
     field("Passwort (mindestens 8 Zeichen)","password","password",{minLength:8,autocomplete:"new-password"})],"Konto anlegen",
    d=>api("/api/setup",{method:"POST",json:d}));
  const box=oidcBox("Mit Pocket ID einrichten");
  if(box)$app.firstChild.prepend(box);
}

/* Übersicht ------------------------------------------------------------ */
async function viewHome(){
  loading("home");
  const o=await api("/api/overview");
  const open=o.meters.filter(x=>!x.done);
  const name=monthName(o.month).split(" ")[0];
  const lead=o.meters.length&&!open.length
    ?`${name} ist komplett abgelesen.`
    :`${name}: ${o.meters.length-open.length} von ${o.meters.length} Zählern abgelesen.`;
  $app.replaceChildren(shell("home",
    h("div",{class:"row",style:"justify-content:space-between;margin-bottom:14px"},
      h("h1",null,lead),
      S.user.record&&open.length?h("a",{class:"btn",href:"#/ablesen/los"},"Zähler ablesen"):null),
    h("div",{class:"plates"},o.meters.map(plate))));
}
function plate(x){
  const m=x.meter,iv=x.last_interval,y=x.ytd;
  const facts=[];
  if(!x.last)facts.push("Noch kein Stand erfasst.");
  if(iv)facts.push(h("div",null,`${dateShort(iv.start)} bis ${dateShort(iv.end)}: ${iv.ok?`${num(iv.delta,m.decimals)} ${m.unit}, ${num(iv.per_day,2)} ${rate(m)}`:"Stand gesunken, bitte prüfen"}`));
  if(y&&y.pct!=null){
    const word=y.pct<0?"weniger":"mehr";
    facts.push(h("div",null,`${y.year} bisher ${Math.abs(y.pct).toLocaleString("de-DE")} % ${word} als im Vorjahr`));
  }
  return h("a",{class:`plate ${cls(m)}`,href:`#/verlauf/${m.id}`},
    h("div",{class:"head"},h("h2",null,m.name,m.private?h("span",{class:"tag"},"nur für dich"):null),
      h("span",{class:"status"+(x.done?"":" open")},x.done?`abgelesen ${dateShort(x.done)}`:"noch offen")),
    x.last?drum(x.last.value,m.decimals,m.unit):drum(null,m.decimals,m.unit),
    h("div",{class:"facts"},facts));
}

/* Ablesen -------------------------------------------------------------- */
async function viewRead(arg){
  loading("read");
  if(!S.user.record){location.hash="#/";return}
  const o=await api("/api/overview");
  const open=o.meters.filter(x=>!x.done);
  if(arg==="los"&&open.length)return step(open,0);
  if(arg&&arg!=="los"){
    const one=o.meters.find(x=>String(x.meter.id)===arg);
    if(one)return step([one],0);
  }
  $app.replaceChildren(shell("read",
    h("h1",{style:"margin-bottom:6px"},open.length?"Was steht an?":"Alles abgelesen"),
    h("p",{class:"muted",style:"margin-bottom:14px"},open.length?`${open.length} ${open.length===1?"Zähler ist":"Zähler sind"} für ${monthName(o.month).split(" ")[0]} noch offen.`:"Du kannst trotzdem einen Zusatzstand eintragen, zum Beispiel beim Anbieterwechsel."),
    open.length?h("a",{class:"btn wide",href:"#/ablesen/los",style:"margin-bottom:14px"},"Rundgang starten"):null,
    h("div",{class:"panel menu"},o.meters.map(x=>h("a",{href:`#/ablesen/${x.meter.id}`},
      x.meter.name,x.done?h("span",{class:"muted small"},` (abgelesen ${dateShort(x.done)})`):h("span",{class:"small"}," (offen)"))))));
}

function step(queue,idx){
  const x=queue[idx],m=x.meter;
  let file=null,saving=false;
  const stepNo=idx+1,total=queue.length;
  const dateIn=h("input",{type:"date",name:"read_on",value:S.today,max:S.today,required:true});
  const value=h("input",{class:"value-input",id:"val",inputMode:"decimal",autocomplete:"off",required:true,placeholder:"0,000"});
  const note=h("input",{type:"text",maxLength:500});
  const swap=h("input",{type:"checkbox"});
  const liveDrum=h("div",null,drum(null,m.decimals,m.unit,"big"));
  const delta=h("p",{class:"delta muted small"});
  const msg=h("div");
  const hint=h("p",{class:"small muted"});
  const shot=h("div",{class:"shot"});
  const saveBtn=h("button",{class:"btn wide",type:"submit"},idx+1<queue.length?"Speichern und weiter":"Speichern");

  const parse=()=>{const t=value.value.trim().replace(/\s/g,"");if(!t)return null;const n=Number(t.includes(",")?t.replace(/\./g,"").replace(",","."):t);return Number.isFinite(n)?n:NaN};
  function update(){
    const v=parse(),old=liveDrum.textContent;
    liveDrum.replaceChildren(drum(v==null||Number.isNaN(v)?null:v,m.decimals,m.unit,"big"));
    if(old!==liveDrum.textContent)liveDrum.querySelectorAll(".d").forEach(c=>c.classList.add("roll"));
    delta.textContent="";
    if(x.last&&v!=null&&!Number.isNaN(v)&&!swap.checked){
      const days=Math.round((new Date(dateIn.value)-new Date(x.last.read_on))/864e5),d=v-x.last.value;
      delta.textContent=days>0?`${d>=0?"+":""}${num(d,m.decimals)} ${m.unit} in ${days} Tagen, ${num(d/days,2)} ${rate(m)}`:"";
    }
  }
  value.addEventListener("input",update);dateIn.addEventListener("change",update);swap.addEventListener("change",update);

  async function pick(f){
    if(!f)return;file=f;msg.replaceChildren();
    const img=h("img",{src:URL.createObjectURL(f),alt:`Foto ${m.name}`,onclick:()=>img.classList.toggle("zoom")});
    shot.className="shot has";shot.replaceChildren(img);
    again.hidden=false;
    value.focus({preventScroll:true});
    hint.textContent=S.ocr?"Foto wird gelesen …":"";
    const fd=new FormData();fd.append("photo",f);fd.append("meter_id",m.id);
    try{
      const r=await api("/api/photo/inspect",{method:"POST",form:fd});
      hint.textContent="";
      if(r.taken_at){const d=r.taken_at.slice(0,10);if(d<=S.today&&d!==dateIn.value){dateIn.value=d;hint.textContent=`Datum vom Foto übernommen: ${date(d)}. `;update()}}
      if(r.suggestion!=null&&!value.value){value.value=String(r.suggestion).replace(".",",");update();hint.textContent+="Stand aus dem Foto gelesen. Bitte mit dem Foto vergleichen."}
      else if(S.ocr&&r.suggestion==null)hint.textContent+="Stand konnte nicht gelesen werden, bitte eintippen.";
    }catch(e){hint.textContent="";errorBox(msg,e);file=null}
  }
  const filebtn=(label,cap,cl)=>{const inp=h("input",{type:"file",accept:"image/*",capture:cap?"environment":null,onchange:e=>pick(e.target.files[0])});
    return h("label",{class:`btn filebtn ${cl}`},label,inp)};
  const again=h("div",{hidden:true},filebtn("Neues Foto","1","quiet small"));
  shot.append(filebtn("Foto machen",true,""),filebtn("Aus der Galerie wählen",false,"quiet small"));

  async function save(confirm){
    if(saving)return;
    const v=parse();
    msg.replaceChildren();
    if(v==null||Number.isNaN(v))return errorBox(msg,new Error("Bitte den Stand als Zahl eingeben."));
    const fd=new FormData();
    fd.append("value",String(v));fd.append("read_on",dateIn.value);fd.append("note",note.value);
    if(swap.checked)fd.append("new_meter","1");
    if(confirm)fd.append("confirm","1");
    if(file)fd.append("photo",file);
    saving=true;saveBtn.disabled=true;saveBtn.textContent="Wird gespeichert …";
    try{
      await api(`/api/meters/${m.id}/readings`,{method:"POST",form:fd});
      if(idx+1<queue.length)return step(queue,idx+1);
      location.hash="#/";render();
    }catch(e){
      saving=false;saveBtn.disabled=false;saveBtn.textContent=idx+1<queue.length?"Speichern und weiter":"Speichern";
      if(e.status===409&&e.data.warnings){
        msg.replaceChildren(h("div",{class:"warn stack"},e.data.warnings.map(w=>h("p",null,w.text)),
          h("button",{class:"btn quiet small",type:"button",onclick:()=>save(true)},"Trotzdem speichern")));
      }else errorBox(msg,e);
    }
  }
  const form=h("form",{class:"stack",novalidate:true,onsubmit:e=>{e.preventDefault();save(false)}},
    liveDrum,
    h("label",{class:"field",htmlFor:"val"},"Stand in "+m.unit,value),
    x.last?h("p",{class:"small muted"},`Letzter Stand ${num(x.last.value,m.decimals)} ${m.unit} am ${date(x.last.read_on)}`):null,
    delta,
    h("label",{class:"field"},"Datum",dateIn),
    h("details",null,h("summary",null,"Notiz oder Zählertausch"),h("div",{class:"stack",style:"margin-top:8px"},
      h("label",{class:"field"},"Notiz",note),
      h("label",{class:"check"},swap,"Zähler wurde getauscht, das ist der erste Stand"))),
    msg,saveBtn,
    idx+1<queue.length?h("button",{class:"btn quiet wide",type:"button",onclick:()=>step(queue,idx+1)},"Überspringen"):
      h("a",{class:"btn quiet wide",href:"#/"},"Abbrechen"));
  $app.replaceChildren(shell("read",
    h("h1",null,m.name,m.private?h("span",{class:"tag"},"nur für dich"):null),
    total>1?h("div",null,h("p",{class:"muted small",style:"margin-top:2px"},`Zähler ${stepNo} von ${total}`),
      h("div",{class:"steps","aria-hidden":"true"},Array.from({length:total},(_,n)=>h("i",{class:n<stepNo-1?"done":n===stepNo-1?"now":""})))):h("div",{style:"height:12px"}),
    h("div",{class:"wizard"},h("div",{class:"stack"},shot,again,hint),form)));
  scrollTo(0,0);
}

/* Verlauf -------------------------------------------------------------- */
async function meterTabs(route,arg){
  const meters=await api("/api/meters");
  const cur=meters.find(m=>String(m.id)===arg)||meters[0];
  const tabs=h("div",{class:"tabs"},meters.map(m=>h("a",{href:`#/${route}/${m.id}`,"aria-current":m.id===cur.id?"true":null},m.name)));
  return {meters,cur,tabs};
}
async function viewLog(arg){
  loading("log");
  const {cur,tabs}=await meterTabs("verlauf",arg);
  const d=await api(`/api/meters/${cur.id}/readings`);
  const m=d.meter;
  const rows=d.readings.map(r=>h("tr",{class:"click",tabIndex:0,onclick:()=>detail(r.id),onkeydown:e=>{if(e.key==="Enter")detail(r.id)}},
    h("td",null,date(r.read_on)),
    h("td",{class:"r"},num(r.value,m.decimals)),
    h("td",{class:"r"},r.new_meter?"neuer Zähler":!r.ok?h("span",{class:"err"},`${num(r.delta,m.decimals)} prüfen`):num(r.delta,m.decimals)),
    h("td",{class:"r"},r.per_day==null||!r.ok?"–":num(r.per_day,2)),
    h("td",null,r.photo?h("img",{class:"thumb",src:`/api/photos/${r.photo}/thumb`,alt:`Foto vom ${date(r.read_on)}`,loading:"lazy"}):h("span",{class:"muted small"},"kein Foto"))));
  $app.replaceChildren(shell("log",
    h("h1",{style:"margin-bottom:12px"},"Verlauf"),tabs,
    h("div",{class:`panel ${cls(m)}`},d.readings.length?h("div",{class:"scroll"},h("table",null,
      h("thead",null,h("tr",null,h("th",null,"Datum"),h("th",{class:"r"},`Stand ${m.unit}`),h("th",{class:"r"},"Differenz"),h("th",{class:"r"},rate(m)),h("th",null,"Foto"))),
      h("tbody",null,rows))):h("div",{class:"stack"},h("p",null,"Noch keine Stände erfasst."),S.user.record?h("a",{class:"btn",href:`#/ablesen/${m.id}`},"Ersten Stand eintragen"):null))));
}
async function detail(id){
  const d=await api(`/api/readings/${id}`);
  const m=d.meter,r=d.reading;
  const dlg=h("dialog",{onclose:()=>dlg.remove()});
  const msg=h("div");
  function showView(){
    dlg.replaceChildren(h("div",{class:"dlg stack"},
      h("div",{class:"bar"},h("h2",null,`${m.name}, ${date(r.read_on)}`),h("button",{class:"btn quiet small",onclick:()=>dlg.close()},"Schließen")),
      drum(r.value,m.decimals,m.unit),
      d.photo?h("a",{href:`/api/photos/${d.photo.id}/original`,target:"_blank",rel:"noopener"},h("img",{class:"full",src:`/api/photos/${d.photo.id}/view`,alt:`Foto ${m.name} vom ${date(r.read_on)}`})):h("p",{class:"muted"},"Zu dieser Ablesung gibt es kein Foto."),
      h("dl",{class:"kv"},
        r.delta!=null?[h("dt",null,"Differenz"),h("dd",null,`${num(r.delta,m.decimals)} ${m.unit} in ${r.days} Tagen`)]:null,
        r.new_meter?[h("dt",null,"Hinweis"),h("dd",null,"Erster Stand nach Zählertausch")]:null,
        r.note?[h("dt",null,"Notiz"),h("dd",null,r.note)]:null,
        h("dt",null,"Eingetragen"),h("dd",null,`${stamp(d.created_at)} von ${d.created_by}`),
        d.photo?[h("dt",null,"Foto aufgenommen"),h("dd",null,d.photo.taken_at?stamp(d.photo.taken_at):"nicht im Foto gespeichert"),
          h("dt",null,"SHA-256"),h("dd",{class:"small"},d.photo.sha256)]:null),
      d.history.length>1?h("details",null,h("summary",null,`Änderungen (${d.history.length})`),h("ul",{class:"plain small"},d.history.map(a=>h("li",null,`${stamp(a.at)}: ${a.action} von ${a.user}`,a.old&&a.new&&a.old.value!==a.new.value?`, Stand ${a.old.value} zu ${a.new.value}`:"",a.reason?` (${a.reason})`:"")))):null,
      d.old_photos.length?h("details",null,h("summary",null,"Frühere Fotos"),h("div",{class:"row",style:"margin-top:8px"},d.old_photos.map(p=>h("a",{href:`/api/photos/${p.id}/original`,target:"_blank",rel:"noopener"},h("img",{class:"thumb",src:`/api/photos/${p.id}/thumb`,alt:`Früheres Foto vom ${date(p.uploaded_at)}`}))))):null,
      msg,
      S.user.record?h("div",{class:"row"},
        h("button",{class:"btn quiet small",onclick:showEdit},"Korrigieren"),
        h("label",{class:"btn quiet small filebtn"},d.photo?"Foto ersetzen":"Foto ergänzen",h("input",{type:"file",accept:"image/*",onchange:async e=>{
          const fd=new FormData();fd.append("photo",e.target.files[0]);
          try{await api(`/api/readings/${id}/photo`,{method:"POST",form:fd});dlg.close();render();detail(id)}catch(err){errorBox(msg,err)}}})),
        S.user.admin?h("button",{class:"btn danger small",onclick:async()=>{
          if(!confirmDelete.hidden)return;confirmDelete.hidden=false}},"Löschen"):null):null,
      confirmDelete));
  }
  const confirmDelete=h("div",{class:"warn stack",hidden:true},h("p",null,"Die Ablesung verschwindet aus Listen und Statistik. Das Protokoll behält den Eintrag."),
    h("button",{class:"btn danger small",onclick:async()=>{await api(`/api/readings/${id}`,{method:"DELETE"});dlg.close();render()}},"Ablesung löschen"));
  function showEdit(){
    const v=h("input",{name:"value",inputMode:"decimal",value:String(r.value).replace(".",","),required:true});
    const day=h("input",{type:"date",name:"read_on",value:r.read_on,max:S.today,required:true});
    const note=h("input",{name:"note",value:r.note,maxLength:500});
    const reason=h("input",{name:"reason",placeholder:"zum Beispiel Tippfehler",maxLength:300});
    const swap=h("input",{type:"checkbox",checked:r.new_meter});
    const em=h("div");
    async function send(confirm){
      em.replaceChildren();
      try{
        await api(`/api/readings/${id}`,{method:"POST",json:{value:v.value,read_on:day.value,note:note.value,reason:reason.value,new_meter:swap.checked,confirm}});
        dlg.close();render();
      }catch(e){
        if(e.status===409&&e.data.warnings)em.replaceChildren(h("div",{class:"warn stack"},e.data.warnings.map(w=>h("p",null,w.text)),h("button",{class:"btn quiet small",type:"button",onclick:()=>send(true)},"Trotzdem speichern")));
        else errorBox(em,e);
      }
    }
    dlg.replaceChildren(h("form",{class:"dlg stack",onsubmit:e=>{e.preventDefault();send(false)}},
      h("h2",null,"Ablesung korrigieren"),
      h("p",{class:"small muted"},"Der alte Wert bleibt im Änderungsprotokoll sichtbar."),
      h("label",{class:"field"},`Stand in ${m.unit}`,v),h("label",{class:"field"},"Datum",day),
      h("label",{class:"field"},"Notiz",note),h("label",{class:"field"},"Grund der Änderung",reason),
      h("label",{class:"check"},swap,"Erster Stand nach Zählertausch"),em,
      h("div",{class:"row"},h("button",{class:"btn",type:"submit"},"Änderung speichern"),h("button",{class:"btn quiet",type:"button",onclick:showView},"Zurück"))));
  }
  showView();document.body.append(dlg);dlg.showModal();
}

/* Statistik ------------------------------------------------------------ */
function tip(ev,lines){
  $tip.hidden=false;$tip.replaceChildren(...lines.map((l,i)=>h("div",{style:i?"":"font-weight:600"},l)));
  const pad=12,w=$tip.offsetWidth,x=Math.min(innerWidth-w-8,Math.max(8,ev.clientX+pad));
  const y=Math.max(8,ev.clientY-$tip.offsetHeight-pad);
  $tip.style.left=x+"px";$tip.style.top=y+"px";
}
function closeTip(){$tip.hidden=true}
function niceMax(v){if(v<=0)return 1;const p=10**Math.floor(Math.log10(v)),n=v/p;return(n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*p}
const tickCount=max=>{const n=max/10**Math.floor(Math.log10(max));return Math.abs(n-2)<1e-9?4:5};
const tickDec=max=>{const st=max/tickCount(max);return st>=1?0:st>=.1?1:2};
function axes(g,W,H,L,B,T,max,fmt,xLabels){
  const n=tickCount(max),ax=[];
  for(let i=0;i<=n;i++){const v=max*i/n,y=H-B-(H-B-T)*i/n;
    ax.push(s("line",{x1:L,x2:W,y1:y,y2:y,stroke:"var(--grid)","stroke-width":1}));
    ax.push(s("text",{x:L-6,y:y+4,"text-anchor":"end"},fmt(v)));}
  xLabels.forEach(([x,t])=>ax.push(s("text",{x,y:H-6,"text-anchor":"middle"},t)));
  g.append(...ax);
}
function barChart(box,items,m,field){
  const W=Math.max(300,box.clientWidth||600),H=240,L=46,B=24,T=8,R=14;
  const max=niceMax(Math.max(...items.map(i=>i[field]),0.001));
  const dec=tickDec(max),svg=s("svg",{class:"chart",viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":`Balkendiagramm ${m.name}`});
  const col=`var(--${m.color})`;
  svg.append(s("defs",null,s("pattern",{id:"hatch",width:5,height:5,patternUnits:"userSpaceOnUse",patternTransform:"rotate(45)"},s("rect",{width:2,height:5,fill:col}))));
  const step=(W-L-R)/items.length,bw=Math.max(3,Math.min(step-2,36)),every=Math.ceil(items.length/(W/56));
  const labels=[];
  items.forEach((it,i)=>{if((items.length-1-i)%every===0)labels.push([L+step*i+step/2,MON[it.m-1]+(it.m===1||i===0?` ${String(it.year).slice(2)}`:"")])});
  const g=s("g");svg.append(g);axes(g,W-R,H,L,B,T,max,v=>num(v,dec),labels);
  const scale=(H-B-T)/max;
  items.forEach((it,i)=>{
    const hgt=Math.max(1,it[field]*scale),x=L+step*i+(step-bw)/2,y=H-B-hgt,r=Math.min(4,bw/2,hgt);
    const bar=s("path",{d:`M${x} ${H-B}V${y+r}Q${x} ${y} ${x+r} ${y}H${x+bw-r}Q${x+bw} ${y} ${x+bw} ${y+r}V${H-B}Z`,fill:it.full?col:"url(#hatch)",stroke:it.full?"none":col});
    const hit=s("rect",{x:L+step*i,y:T,width:step,height:H-B-T,fill:"transparent"});
    const show=e=>{bar.setAttribute("opacity",".78");tip(e,[monthName(it.month),`${num(it.value,1)} ${m.unit}`,`${num(it.per_day,2)} ${rate(m)}`,it.full?"":`${it.days} von ${it.days_in_month} Tagen bekannt`].filter(Boolean))};
    hit.addEventListener("pointermove",show);hit.addEventListener("pointerdown",show);
    hit.addEventListener("pointerleave",()=>{bar.removeAttribute("opacity");closeTip()});
    svg.append(bar,hit);
  });
  return svg;
}
function yearChart(box,months,m,yearsList){
  const W=Math.max(300,box.clientWidth||600),H=240,L=46,B=24,T=10,R=44;
  const byYear=new Map(yearsList.map(y=>[y,Array(12).fill(null)]));
  months.filter(x=>x.full&&byYear.has(x.year)).forEach(x=>byYear.get(x.year)[x.m-1]=x.value);
  const all=[...byYear.values()].flat().filter(v=>v!=null);
  if(!all.length)return null;
  const max=niceMax(Math.max(...all)),dec=tickDec(max);
  const svg=s("svg",{class:"chart",viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":`Jahresvergleich ${m.name}`});
  const inner=W-L-R,X=i=>L+inner*i/11,Y=v=>H-B-(H-B-T)*v/max;
  const g=s("g");svg.append(g);
  const labels=MON.map((t,i)=>[X(i),t]).filter((_,i)=>W>=560||i%2===0);
  axes(g,W-R,H,L,B,T,max,v=>num(v,dec),labels);
  const shades=[`var(--${m.color})`,"var(--past1)","var(--past2)","var(--past3)"];
  const ends=[];
  yearsList.forEach((y,yi)=>{
    const vals=byYear.get(y);let d="",pen=false,lastI=-1;
    vals.forEach((v,i)=>{if(v==null){pen=false;return}d+=`${pen?"L":"M"}${X(i)} ${Y(v)}`;pen=true;lastI=i});
    svg.prepend(g);
    svg.append(s("path",{d,fill:"none",stroke:shades[yi],"stroke-width":yi===0?2.5:1.75,"stroke-linejoin":"round"}));
    vals.forEach((v,i)=>{if(v!=null&&(vals[i-1]==null&&vals[i+1]==null))svg.append(s("circle",{cx:X(i),cy:Y(v),r:3.5,fill:shades[yi]}))});
    if(lastI>=0)ends.push({y,x:X(lastI)+6,py:Y(vals[lastI])+4});
  });
  ends.sort((a,b)=>a.py-b.py).forEach((e,i,all)=>{
    if(i&&Math.abs(e.x-all[i-1].x)<40&&e.py-all[i-1].py<14)e.py=all[i-1].py+14;
    svg.append(s("text",{x:e.x,y:e.py},String(e.y)));
  });
  const cross=s("line",{y1:T,y2:H-B,stroke:"var(--ink3)","stroke-width":1,opacity:0});svg.append(cross);
  const hit=s("rect",{x:L,y:T,width:inner,height:H-B-T,fill:"transparent"});
  const move=e=>{
    const rect=svg.getBoundingClientRect(),px=(e.clientX-rect.left)*W/rect.width;
    const i=Math.min(11,Math.max(0,Math.round((px-L)/inner*11)));
    cross.setAttribute("x1",X(i));cross.setAttribute("x2",X(i));cross.setAttribute("opacity",1);
    tip(e,[MONTHS[i],...yearsList.map(y=>{const v=byYear.get(y)[i];return`${y}: ${v==null?"–":num(v,1)+" "+m.unit}`})]);
  };
  hit.addEventListener("pointermove",move);hit.addEventListener("pointerdown",move);
  hit.addEventListener("pointerleave",()=>{cross.setAttribute("opacity",0);closeTip()});
  svg.append(hit);
  return {svg,shades};
}
async function viewStats(arg){
  loading("stats");
  const {cur,tabs}=await meterTabs("statistik",arg);
  const d=await api(`/api/meters/${cur.id}/stats`);
  const m=d.meter;
  const content=h("div",{class:`stack ${cls(m)}`});
  $app.replaceChildren(shell("stats",h("h1",{style:"margin-bottom:12px"},"Statistik"),tabs,content));
  if(!d.months.length){content.append(h("div",{class:"panel"},h("p",null,"Für eine Auswertung braucht dieser Zähler mindestens zwei Stände.")));return}

  const lastYear=d.years[d.years.length-1];
  const cards=[h("div",{class:"panel"},h("div",{class:"big-number num"},`${num(d.per_day,2)}`),h("div",{class:"muted small"},`${rate(m)} im Schnitt, seit ${date(d.intervals[0].start)}`)),
    h("div",{class:"panel"},h("div",{class:"big-number num"},`${num(d.ytd.value,m.decimals>1?1:m.decimals)} ${m.unit}`),h("div",{class:"muted small"},`${d.ytd.year} bis ${dateShort(d.ytd.until)}${d.ytd.complete?"":", nicht lückenlos"}`))];
  if(d.ytd.pct!=null)cards.push(h("div",{class:"panel"},h("div",{class:"big-number num"},`${d.ytd.pct>0?"+":""}${d.ytd.pct.toLocaleString("de-DE")} %`),h("div",{class:"muted small"},`gegenüber ${num(d.ytd.prev_value,1)} ${m.unit} im gleichen Zeitraum ${d.ytd.year-1}`)));
  content.append(h("div",{class:"stats"},cards));
  if(d.bad_intervals)content.append(h("div",{class:"warn"},h("p",null,`${d.bad_intervals===1?"Ein Zeitraum":`${d.bad_intervals} Zeiträume`} mit sinkendem Stand ${d.bad_intervals===1?"wird":"werden"} nicht mitgezählt. Im Verlauf prüfen, ob ein Zählertausch markiert werden muss.`)));

  let mode="value";
  const chartBox=h("div"),seg=h("div",{class:"tabs",style:"margin:10px 0 6px"});
  const items=d.months.slice(-24);
  const drawBars=()=>{
    chartBox.replaceChildren(barChart(chartBox,items,m,mode));
    seg.replaceChildren(...[["value",`${m.unit} im Monat`],["per_day",`${rate(m)}`]].map(([k,t])=>h("button",{"aria-current":k===mode?"true":null,onclick:()=>{mode=k;drawBars()}},t)));
  };
  const partial=items.some(i=>!i.full);
  content.append(h("section",{class:"panel"},h("h2",null,"Verbrauch pro Monat"),seg,chartBox,
    partial?h("div",{class:"legend"},h("span",null,h("i",{class:"hatch"}),"Monat noch nicht vollständig abgelesen")):null,
    h("p",{class:"small muted",style:"margin-top:6px"},"Die Differenz zwischen zwei Ablesungen wird gleichmäßig auf die Tage verteilt. So landet der Verbrauch im richtigen Monat, auch wenn am 3. oder 5. abgelesen wurde."),
    h("details",{style:"margin-top:8px"},h("summary",null,"Als Tabelle"),h("div",{class:"scroll"},h("table",null,
      h("thead",null,h("tr",null,h("th",null,"Monat"),h("th",{class:"r"},m.unit),h("th",{class:"r"},rate(m)))),
      h("tbody",null,[...d.months].reverse().map(x=>h("tr",null,h("td",null,monthName(x.month),x.full?"":" (Teil)"),h("td",{class:"r"},num(x.value,1)),h("td",{class:"r"},num(x.per_day,2))))))))));
  drawBars();

  const ys=d.years.map(y=>y.year).reverse().slice(0,4);
  if(ys.length>=1){
    const box=h("div"),sec=h("section",{class:"panel"},h("h2",{style:"margin-bottom:8px"},"Jahre im Vergleich"),box);
    content.append(sec);
    const r=yearChart(box,d.months,m,ys);
    if(r){box.append(r.svg);sec.append(h("div",{class:"legend"},ys.map((y,i)=>h("span",null,h("i",{style:`background:${r.shades[i]}`}),y))))}
    else box.append(h("p",{class:"muted"},"Noch kein vollständiger Monat."));
    sec.append(h("div",{class:"scroll",style:"margin-top:10px"},h("table",null,
      h("thead",null,h("tr",null,h("th",null,"Jahr"),h("th",{class:"r"},m.unit),h("th",{class:"r"},rate(m)),h("th",{class:"r"},"Tage bekannt"))),
      h("tbody",null,[...d.years].reverse().map(y=>h("tr",null,h("td",null,y.year),h("td",{class:"r"},num(y.value,1)),h("td",{class:"r"},num(y.per_day,2)),h("td",{class:"r"},`${y.days} von ${y.days_in_year}`)))))));
  }
  if(d.parent){
    const rows=d.parent.rows,stuck=rows.filter(r=>r.stuck).length,low=rows.filter(r=>r.low).length;
    content.append(h("section",{class:"panel stack"},h("h2",null,`Vergleich mit ${d.parent.name}`,h("span",{class:"tag"},"nur für dich")),
      !rows.length?h("p",{class:"muted"},"Sobald beide Zähler einen vollen Monat haben, steht hier der Vergleich."):
      [h("p",null,stuck||low?[stuck?`In ${stuck} ${stuck===1?"Monat":"Monaten"} stand dieser Zähler still, während der Hauptzähler lief. `:"",low?`In ${low} ${low===1?"Monat":"Monaten"} lief er auffällig wenig.`:""]:`Dieser Zähler lief in allen ${rows.length} verglichenen Monaten gleichmäßig mit dem Hauptzähler mit.`),
       h("div",{class:"scroll"},h("table",null,h("thead",null,h("tr",null,h("th",null,"Monat"),h("th",{class:"r"},`Dieser ${m.unit}`),h("th",{class:"r"},`Haupt ${m.unit}`),h("th",{class:"r"},"Anteil"))),
       h("tbody",null,[...rows].reverse().slice(0,12).map(r=>h("tr",null,h("td",null,monthName(r.month)),h("td",{class:"r"},num(r.sub,2)),h("td",{class:"r"},num(r.main,2)),h("td",{class:"r"},r.stuck?h("span",{class:"err"},"steht still"):r.low?h("span",{class:"err"},`${r.share.toLocaleString("de-DE")} %, auffällig`):r.share==null?"–":`${r.share.toLocaleString("de-DE")} %`))))))]));
  }
}

/* Mehr ------------------------------------------------------------------ */
function viewMore(){
  $app.replaceChildren(shell("more",h("h1",{style:"margin-bottom:12px"},"Mehr"),h("div",{class:"panel menu"},
    h("a",{href:"#/nachweis"},"Nachweis und Export"),
    h("a",{href:"#/konto"},"Mein Konto"),
    S.user.admin?h("a",{href:"#/verwaltung"},"Verwaltung"):null)));
}
async function viewProof(){
  loading("more");
  const meters=await api("/api/meters");
  const sel=h("select",null,meters.map(m=>h("option",{value:m.id},m.name)));
  const from=h("input",{type:"date"}),to=h("input",{type:"date"}),msg=h("div");
  const go=async()=>{
    msg.replaceChildren();
    const url=`/api/nachweis.pdf?meter=${sel.value}&from=${from.value}&to=${to.value}`;
    const res=await fetch(url,{headers:{"X-Zaehler":"1"}});
    if(!res.ok){const b=await res.json().catch(()=>({}));return errorBox(msg,new Error(b.error||"Das PDF konnte nicht erstellt werden."))}
    const a=h("a",{href:URL.createObjectURL(await res.blob()),download:`nachweis-${date(S.today)}.pdf`});document.body.append(a);a.click();a.remove();
  };
  $app.replaceChildren(shell("more",h("h1",{style:"margin-bottom:12px"},"Nachweis und Export"),h("div",{class:"stack"},
    h("section",{class:"panel stack"},h("h2",null,"PDF für den Anbieter"),
      h("p",{class:"muted"},"Tabelle aller Stände, jedes Foto mit Aufnahmedatum und Prüfsumme, dazu alle nachträglichen Änderungen."),
      h("label",{class:"field"},"Zähler",sel),h("div",{class:"form2"},h("label",{class:"field"},"Von (optional)",from),h("label",{class:"field"},"Bis (optional)",to)),
      msg,h("button",{class:"btn",onclick:go},"PDF herunterladen")),
    h("section",{class:"panel stack"},h("h2",null,"Excel-Liste"),h("p",{class:"muted"},"Gleicher Aufbau wie deine bisherige Liste, mit Links zu den Fotos."),
      h("a",{class:"btn quiet",href:"/api/export.xlsx"},"Excel herunterladen")))));
}
function viewAccount(){
  const msg=h("div");
  const form=h("form",{class:"panel stack",onsubmit:async e=>{e.preventDefault();msg.replaceChildren();
    try{await api("/api/password",{method:"POST",json:Object.fromEntries(new FormData(form))});form.reset();msg.replaceChildren(h("p",{class:"ok"},"Passwort geändert."))}catch(err){errorBox(msg,err)}}},
    h("h2",null,"Passwort ändern"),field("Aktuelles Passwort","old","password",{autocomplete:"current-password"}),field("Neues Passwort (mindestens 8 Zeichen)","new","password",{minLength:8,autocomplete:"new-password"}),msg,h("button",{class:"btn",type:"submit"},"Passwort ändern"));
  $app.replaceChildren(shell("more",h("h1",{style:"margin-bottom:12px"},S.user.name),h("div",{class:"stack"},form,
    h("button",{class:"btn quiet",onclick:async()=>{await api("/api/logout",{method:"POST"});S.user=null;render()}},"Abmelden"))));
}

/* Verwaltung -------------------------------------------------------------- */
async function viewAdmin(arg){
  loading("more");
  if(!S.user.admin){location.hash="#/";return}
  const tab=arg||"konten";
  const tabs=h("div",{class:"tabs"},[["konten","Konten"],["zaehler","Zähler"],["import","Excel übernehmen"],["protokoll","Protokoll"]].map(([k,t])=>h("a",{href:`#/verwaltung/${k}`,"aria-current":k===tab?"true":null},t)));
  const body=h("div",{class:"stack"});
  $app.replaceChildren(shell("more",h("h1",{style:"margin-bottom:12px"},"Verwaltung"),tabs,body));
  await ({konten:adminUsers,zaehler:adminMeters,import:adminImport,protokoll:adminLog}[tab]||adminUsers)(body);
}
async function adminUsers(body){
  const users=await api("/api/users");
  const msg=h("div");
  const save=(u,patch)=>api(`/api/users/${u.id}`,{method:"POST",json:patch}).then(()=>adminUsers(body.replaceChildren()||body)).catch(e=>errorBox(msg,e));
  const form=h("form",{class:"panel stack",onsubmit:async e=>{e.preventDefault();
    const d=Object.fromEntries(new FormData(form));d.can_record=d.can_record==="on";
    try{await api("/api/users",{method:"POST",json:d});body.replaceChildren();adminUsers(body)}catch(err){errorBox(fmsg,err)}}},
    h("h2",null,"Konto anlegen"),h("div",{class:"form2"},field("Name","name"),field("Benutzername","username","text",{autocapitalize:"none"}),field("Passwort (mindestens 8 Zeichen)","password","password",{minLength:8,autocomplete:"new-password"}),
      h("label",{class:"field"},"Rolle",h("select",{name:"role"},h("option",{value:"member"},"Familie"),h("option",{value:"admin"},"Admin")))),
    h("label",{class:"check"},h("input",{type:"checkbox",name:"can_record"}),"Darf Stände eintragen"),
    h("p",{class:"small muted"},"Familienkonten sehen den privaten Zähler nicht. Admin-Konten sehen alles."));
  const fmsg=h("div");form.append(fmsg,h("button",{class:"btn",type:"submit"},"Konto anlegen"));
  body.append(h("div",{class:"panel"},msg,h("div",{class:"scroll"},h("table",null,h("thead",null,h("tr",null,h("th",null,"Name"),h("th",null,"Rolle"),h("th",null,"Eintragen"),h("th",null,"Aktiv"),h("th",null,""))),
    h("tbody",null,users.map(u=>h("tr",null,h("td",null,u.name,h("div",{class:"small muted"},u.username)),
      h("td",null,u.role==="admin"?"Admin":"Familie"),
      h("td",null,h("input",{type:"checkbox",checked:u.can_record||u.role==="admin",disabled:u.role==="admin","aria-label":`${u.name} darf eintragen`,onchange:e=>save(u,{can_record:e.target.checked})})),
      h("td",null,h("input",{type:"checkbox",checked:u.active,"aria-label":`${u.name} aktiv`,onchange:e=>save(u,{active:e.target.checked})})),
      h("td",null,h("button",{class:"btn quiet small",onclick:()=>resetPw(u,msg)},"Passwort")))))))),form);
}
function resetPw(u,msg){
  const inp=h("input",{type:"password",minLength:8,required:true,autocomplete:"new-password"}),em=h("div");
  const dlg=h("dialog",{onclose:()=>dlg.remove()},h("form",{class:"dlg stack",onsubmit:async e=>{e.preventDefault();
    try{await api(`/api/users/${u.id}`,{method:"POST",json:{password:inp.value}});dlg.close();msg.replaceChildren(h("p",{class:"ok"},`Passwort für ${u.name} gesetzt.`))}catch(err){errorBox(em,err)}}},
    h("h2",null,`Neues Passwort für ${u.name}`),h("label",{class:"field"},"Passwort (mindestens 8 Zeichen)",inp),em,
    h("div",{class:"row"},h("button",{class:"btn",type:"submit"},"Passwort setzen"),h("button",{class:"btn quiet",type:"button",onclick:()=>dlg.close()},"Abbrechen"))));
  document.body.append(dlg);dlg.showModal();
}
async function adminMeters(body){
  const meters=await api("/api/meters/all");
  const editor=(m)=>{
    const f=h("form",{class:`panel plate stack ${m?cls(m):"c-neutral"}`,onsubmit:async e=>{e.preventDefault();
      const d=Object.fromEntries(new FormData(f));d.private=d.private==="on";d.active=d.active==="on";d.parent_id=d.parent_id||null;
      try{await api(m?`/api/meters/${m.id}`:"/api/meters",{method:"POST",json:d});body.replaceChildren();adminMeters(body)}catch(err){errorBox(em,err)}}},
      h("h2",null,m?m.name:"Zähler hinzufügen"),
      h("div",{class:"form2"},
        h("label",{class:"field"},"Name",h("input",{name:"name",value:m?m.name:"",required:true})),
        h("label",{class:"field"},"Einheit",h("input",{name:"unit",value:m?m.unit:"m³",required:true})),
        h("label",{class:"field"},"Nachkommastellen",h("input",{name:"decimals",type:"number",min:0,max:4,value:m?m.decimals:3,required:true})),
        h("label",{class:"field"},"Zählernummer (für das PDF)",h("input",{name:"number",value:m?m.number:""})),
        h("label",{class:"field"},"Farbe",h("select",{name:"color"},[["gas","Gelb"],["strom","Violett"],["wasser","Blau"],["neutral","Grau"]].map(([v,t])=>h("option",{value:v,selected:m&&m.color===v},t)))),
        h("label",{class:"field"},"Reihenfolge",h("input",{name:"sort",type:"number",value:m?m.sort:100})),
        h("label",{class:"field"},"Unterzähler von",h("select",{name:"parent_id"},h("option",{value:""},"keinem"),meters.filter(o=>!m||o.id!==m.id).map(o=>h("option",{value:o.id,selected:m&&m.parent_id===o.id},o.name))))),
      h("label",{class:"check"},h("input",{type:"checkbox",name:"private",checked:m&&m.private}),"Privat, nur Admin-Konten sehen diesen Zähler"),
      h("label",{class:"check"},h("input",{type:"checkbox",name:"active",checked:m?m.active:true}),"Aktiv"));
    const em=h("div");f.append(em,h("button",{class:"btn small",type:"submit"},m?"Änderungen speichern":"Zähler hinzufügen"));
    return f;
  };
  body.append(...meters.map(editor),h("details",{class:"panel"},h("summary",null,"Zähler hinzufügen"),h("div",{style:"margin-top:10px"},editor(null))));
}
function adminImport(body){
  const out=h("div",{class:"stack"}),msg=h("div");
  const inp=h("input",{type:"file",accept:".xlsx",class:"input"});
  const go=async()=>{
    msg.replaceChildren();out.replaceChildren();
    if(!inp.files[0])return errorBox(msg,new Error("Bitte zuerst die Excel-Datei wählen."));
    const fd=new FormData();fd.append("file",inp.files[0]);
    try{
      const p=await api("/api/import/preview",{method:"POST",form:fd});
      out.append(h("section",{class:"panel stack"},h("h2",null,"Vorschau"),
        h("div",{class:"scroll"},h("table",null,h("thead",null,h("tr",null,h("th",null,"Zähler"),h("th",{class:"r"},"Neu"),h("th",{class:"r"},"Mit Foto"),h("th",{class:"r"},"Schon da"),h("th",null,"Zeitraum"))),
          h("tbody",null,p.meters.map(m=>h("tr",null,h("td",null,m.name),h("td",{class:"r"},m.count),h("td",{class:"r"},m.photos),h("td",{class:"r"},m.skip),h("td",null,`${date(m.first)} bis ${date(m.last)}`)))))),
        p.meters.filter(m=>m.drops.length).map(m=>h("div",{class:"warn"},h("p",null,`${m.name}: Stand sinkt am ${m.drops.map(date).join(", ")}. Nach der Übernahme im Verlauf prüfen, ob dort der Zähler getauscht wurde.`))),
        p.problem_count?h("div",{class:"warn"},h("p",null,`${p.problem_count} ${p.problem_count===1?"Eintrag wird":"Einträge werden"} übersprungen:`),h("ul",{class:"plain small"},p.problems.map(t=>h("li",null,t)))):null,
        p.missing_count?h("div",{class:"warn"},h("p",null,`${p.missing_count} ${p.missing_count===1?"Foto":"Fotos"} nicht im Importordner gefunden:`),h("ul",{class:"plain small"},p.missing_photos.map(t=>h("li",null,t)))):null,
        h("button",{class:"btn",onclick:async e=>{e.target.disabled=true;
          try{const r=await api("/api/import/commit",{method:"POST",json:{token:p.token}});out.replaceChildren(h("p",{class:"ok"},`${r.added} Stände übernommen, ${r.with_photo} davon mit Foto.`))}catch(err){e.target.disabled=false;errorBox(msg,err)}}},"Stände übernehmen")));
    }catch(e){errorBox(msg,e)}
  };
  body.append(h("section",{class:"panel stack"},h("h2",null,"Bisherige Excel-Liste übernehmen"),
    h("p",{class:"muted"},"Erwarteter Aufbau: A Datum, B Gas, D Foto, E Strom, G Foto, H Wasser, J Foto, K kleiner Zähler. Differenzen werden neu berechnet. Vor dem Übernehmen siehst du eine Vorschau, schon vorhandene Stände werden nicht doppelt eingetragen."),
    h("label",{class:"field"},"Excel-Datei (.xlsx)",inp),msg,h("button",{class:"btn",onclick:go},"Vorschau zeigen")),out);
}
async function adminLog(body){
  const rows=await api("/api/audit");
  const text=r=>{const parts=[];if(r.old&&r.new&&r.old.value!==r.new.value&&r.new.value!=null)parts.push(`${r.old.value} zu ${r.new.value}`);else if(r.new&&r.new.value!=null)parts.push(String(r.new.value));else if(r.old&&r.old.value!=null)parts.push(String(r.old.value));if(r.reason)parts.push(r.reason);return parts.join(", ")};
  body.append(h("div",{class:"panel scroll"},rows.length?h("table",null,h("thead",null,h("tr",null,h("th",null,"Zeit"),h("th",null,"Wer"),h("th",null,"Was"),h("th",null,"Zähler"),h("th",null,"Details"))),
    h("tbody",null,rows.map(r=>h("tr",null,h("td",null,stamp(r.at)),h("td",null,r.user),h("td",null,r.action),h("td",null,r.meter||"–",r.read_on?h("div",{class:"small muted"},date(r.read_on)):null),h("td",null,text(r)))))):h("p",{class:"muted"},"Noch keine Einträge.")));
}

/* Start ------------------------------------------------------------------ */
async function boot(){
  const st=await api("/api/state").catch(e=>({error:e}));
  if(st.error){$app.replaceChildren(h("div",{class:"shell"},h("div",{class:"panel"},h("p",{class:"err"},st.error.message),h("button",{class:"btn",style:"margin-top:10px",onclick:boot},"Erneut versuchen"))));return}
  S={user:st.user,setup:st.setup,ocr:st.ocr,today:st.today,oidc:st.oidc};
  if(st.user&&location.search.includes("fehler="))history.replaceState(null,"",location.pathname+location.hash);
  render();
}
boot();

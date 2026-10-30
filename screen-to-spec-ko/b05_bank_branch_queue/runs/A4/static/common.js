const $=s=>document.querySelector(s);
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
async function api(path,opt={}){
  const h={"Content-Type":"application/json"};
  const t=sessionStorage.getItem("token"); if(t) h["X-Token"]=t;
  const r=await fetch(path,{headers:h,...opt,body:opt.body?JSON.stringify(opt.body):undefined});
  const j=await r.json().catch(()=>({}));
  if(!r.ok){
    let d=j.detail; if(Array.isArray(d)) d=d.map(e=>(e.msg||"").replace(/^Value error, /,"")).join(" / ");
    const e=new Error(d||"오류가 발생했습니다"); e.status=r.status; throw e;
  }
  return j;
}
async function login(role,pin){const j=await api("/api/login",{method:"POST",body:{role,pin}});sessionStorage.setItem("token",j.token);sessionStorage.setItem("role",j.role);}
function hm(s){return s?s.slice(11,16):"-"}
const TAG=t=>t.priority?'<span class="pill pri">예약 우선</span>':'';

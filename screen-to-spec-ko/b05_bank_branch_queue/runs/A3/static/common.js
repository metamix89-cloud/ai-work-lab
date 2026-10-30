const $=s=>document.querySelector(s);
// 서버 값은 항상 textContent/문자열 노드로만 넣는다 (XSS 방지)
function el(tag,props={},...kids){const e=document.createElement(tag);Object.assign(e,props);kids.forEach(k=>e.append(k));return e}
async function api(path,opts={}){
  const h={'Content-Type':'application/json'};const t=sessionStorage.getItem('tok');if(t)h.Authorization='Bearer '+t;
  const r=await fetch(path,{...opts,headers:h,body:opts.body?JSON.stringify(opts.body):undefined});
  const j=await r.json().catch(()=>({}));
  if(!r.ok){let d=j.detail;if(Array.isArray(d))d=d.map(x=>(x.msg||'').replace('Value error, ','')).join(' / ');
    const e=new Error(d||'오류');e.status=r.status;throw e}
  return j}
function say(box,text,ok){box.textContent=text;box.className='msg '+(ok?'ok':'err')}
async function login(role){
  const pin=prompt(role==='manager'?'지점장 PIN (데모: 9999)':'창구 직원 PIN (데모: 1111)');if(!pin)return false;
  try{const j=await api('/api/login',{method:'POST',body:{role,pin}});sessionStorage.setItem('tok',j.token);return true}
  catch(e){alert(e.message);return false}}

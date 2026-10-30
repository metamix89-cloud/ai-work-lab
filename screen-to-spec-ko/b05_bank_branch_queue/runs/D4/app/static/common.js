const $=s=>document.querySelector(s);
async function api(path,opts={}){
  const h={'Content-Type':'application/json'};
  const t=sessionStorage.getItem('token'); if(t) h.Authorization='Bearer '+t;
  const r=await fetch(path,{...opts,headers:h,body:opts.body?JSON.stringify(opts.body):undefined});
  const j=await r.json().catch(()=>({}));
  if(!r.ok){const d=j.detail; throw new Error(typeof d==='string'?d:(d&&d[0]&&d[0].msg)||'오류가 발생했습니다');}
  return j;
}
function say(el,text,ok){el.textContent=text;el.className='msg '+(ok?'ok':'err');}

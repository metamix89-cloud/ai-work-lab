function $(id){return document.getElementById(id)}
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
async function api(path,opts={},token){
  const h={"Content-Type":"application/json"};if(token)h.Authorization="Bearer "+token;
  const r=await fetch(path,{...opts,headers:h});let d={};try{d=await r.json()}catch(e){}
  if(!r.ok){let m=d.detail;if(Array.isArray(m))m=m.map(x=>x.msg).join(", ");const e=new Error(m||"오류가 발생했습니다");e.status=r.status;throw e}
  return d}
function say(id,text,err){const n=$(id);n.textContent=text;n.className="msg"+(err?" err":"");n.hidden=false}

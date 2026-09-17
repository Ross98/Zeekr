'use strict';
document.querySelector('form').addEventListener('submit', async event => {
  event.preventDefault();
  const button=document.querySelector('button');button.disabled=true;
  try {
    const response=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.querySelector('#password').value})});
    if(response.ok) location.replace('/');
    else document.querySelector('#error').textContent=(await response.json()).error;
  } catch { document.querySelector('#error').textContent='连接失败，请重试。'; }
  finally { button.disabled=false; }
});

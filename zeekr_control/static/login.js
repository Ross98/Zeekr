'use strict';
const remember=document.querySelector('#remember');
remember.addEventListener('change', () => {
  document.querySelector('#remember-help').textContent=remember.value==='0'
    ? '每次登录仍需输入密码。'
    : '仅此浏览器、同一 IP 有效。到期、退出登录或 IP 变化后需重新输入密码。';
});
document.querySelector('form').addEventListener('submit', async event => {
  event.preventDefault();
  const button=document.querySelector('button');button.disabled=true;
  document.querySelector('#error').textContent='';
  try {
    const response=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.querySelector('#password').value,remember_days:Number(remember.value)})});
    if(response.ok) location.replace('/');
    else document.querySelector('#error').textContent=(await response.json()).error;
  } catch { document.querySelector('#error').textContent='连接失败，请重试。'; }
  finally { button.disabled=false; }
});

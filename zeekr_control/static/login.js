'use strict';
const remember=document.querySelector('#remember');
remember.addEventListener('change', () => {
  document.querySelector('#remember-help').textContent=remember.value==='0'
    ? '每次登录仍需输入密码。'
    : '仅此浏览器、同一 IP 有效。到期、退出登录或 IP 变化后需重新输入密码。';
});
document.querySelector('form').addEventListener('submit', async event => {
  event.preventDefault();
  const form=event.currentTarget,button=form.querySelector('button'),errorNode=form.querySelector('#error');
  if(button.disabled)return;
  const payload={password:form.querySelector('#password').value,remember_days:Number(remember.value)};
  const controls=[...form.querySelectorAll('input,select,button')].map(control=>[control,control.disabled]);
  const label=button.textContent;
  for(const [control] of controls)control.disabled=true;
  button.textContent='正在登录…';errorNode.textContent='';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
  try {
    const response=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
    if(response.ok) location.replace('/');
    else {
      const result=await response.json();
      errorNode.textContent=typeof result?.error==='string'&&result.error.trim()?result.error:'服务响应无效，登录结果尚未确认，请重试。';
    }
  } catch(error) {
    errorNode.textContent=error.name==='AbortError'?'登录响应超时，结果尚未确认，请重试。'
      :error instanceof SyntaxError?'服务响应无效，登录结果尚未确认，请重试。':'连接失败，登录结果尚未确认，请重试。';
  } finally {
    clearTimeout(timer);
    for(const [control,disabled] of controls)control.disabled=disabled;
    button.textContent=label;
  }
});

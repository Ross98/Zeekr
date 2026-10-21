/* Credentials stay in this ephemeral dialog; never persist in browser storage. */
window.createVehicleLogin=({request,connected})=>{
  let current=null;
  return {open(trigger){
    if(current){current.querySelector('input')?.focus();return;}
    const dialog=document.createElement('dialog');
    dialog.id='vehicle-login-dialog';dialog.className='vehicle-login-dialog';
    dialog.setAttribute('aria-labelledby','vehicle-login-title');
    dialog.innerHTML=`<form class="vehicle-login-form">
      <div class="vehicle-login-head"><h2 id="vehicle-login-title">连接车辆账号</h2><button type="button" class="button secondary" data-close aria-label="关闭登录窗口">关闭</button></div>
      <p>使用原采集副账号重新连接，已有行程、充电和账本记录保留。</p>
      <p class="vehicle-login-warning">新登录可能使同一副账号的官方 App 下线。</p>
      <label for="vehicle-login-phone">副账号手机号</label>
      <input id="vehicle-login-phone" type="tel" inputmode="numeric" autocomplete="off" pattern="1[3-9][0-9]{9}" maxlength="11" required>
      <div class="vehicle-login-code"><div><label for="vehicle-login-code">短信验证码</label><input id="vehicle-login-code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{4,8}" maxlength="8"></div><button type="button" class="button secondary" data-send>发送验证码</button></div>
      <p class="vehicle-login-status" role="status" aria-live="polite"></p>
      <p class="vehicle-login-error" role="alert"></p>
      <button type="submit" class="button" data-verify disabled>验证并连接</button>
      <p class="vehicle-login-note">验证码仅用于本次验证，不写入日志或本地存储。</p>
    </form>`;
    document.body.append(dialog);current=dialog;
    const form=dialog.querySelector('form'),phone=dialog.querySelector('#vehicle-login-phone'),code=dialog.querySelector('#vehicle-login-code');
    const send=dialog.querySelector('[data-send]'),verify=dialog.querySelector('[data-verify]'),status=dialog.querySelector('[role=status]'),error=dialog.querySelector('[role=alert]');
    let challenge='',until=0,expires=0,pending=false,closed=false;
    const update=()=>{
      if(closed)return;
      const remaining=Math.max(0,Math.ceil((until-Date.now())/1000));
      if(challenge&&Date.now()>=expires){challenge='';code.value='';status.textContent='验证码已过期，请重新获取。';}
      send.disabled=pending||remaining>0;
      send.textContent=remaining?`${remaining} 秒后重发`:'发送验证码';
      verify.disabled=pending||!challenge||!/^\d{4,8}$/.test(code.value);
      phone.disabled=code.disabled=pending;
      verify.textContent=pending?'处理中…':'验证并连接';
    };
    const timer=setInterval(update,250);
    const close=()=>{
      if(closed)return;
      closed=true;clearInterval(timer);phone.value=code.value=challenge='';
      current=null;dialog.remove();if(trigger?.isConnected)trigger.focus();
    };
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    dialog.querySelector('[data-close]').onclick=close;
    phone.oninput=()=>{challenge='';code.value='';status.textContent='';error.textContent='';update();};
    code.oninput=update;
    send.onclick=async()=>{
      if(pending||Date.now()<until)return;
      if(!phone.reportValidity())return;
      pending=true;challenge='';code.value='';error.textContent='';update();
      // Conservative cooldown also covers an ambiguous network timeout.
      until=Date.now()+60000;
      try{
        const result=await request('/api/vehicle-login/sms',{phone:phone.value});
        if(closed)return;
        challenge=result.challenge;until=Date.now()+result.retry_after*1000;expires=Date.now()+result.expires_in*1000;
        status.textContent='短信已发送，10 分钟内有效。';code.focus();
      }catch(e){if(!closed)error.textContent=e.message;}
      finally{pending=false;update();if(!closed&&challenge)code.focus();}
    };
    form.onsubmit=async event=>{
      event.preventDefault();if(pending||!challenge||!/^\d{4,8}$/.test(code.value))return;
      pending=true;error.textContent='';update();
      try{
        await request('/api/vehicle-login/verify',{challenge,code:code.value},120000);
        close();await connected();
      }catch(e){if(!closed){code.value='';error.textContent=e.message;}}
      finally{pending=false;update();}
    };
    dialog.showModal();phone.focus();update();
  }};
};

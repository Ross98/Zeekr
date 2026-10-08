// Rebuild the review gallery from an isolated synthetic service.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {fixture}=require('./ui_insight_helpers.cjs');
const directory=path.resolve(__dirname,'../docs/vehicle-insights-demo');
const entries=[];
(async()=>{
  fs.mkdirSync(directory,{recursive:true});
  const f=await fixture({demo:true}),{page}=f;
  const button=name=>page.getByRole('button',{name,exact:true});
  const field=name=>page.getByLabel(name,{exact:true});
  async function capture(slug,title,description,ready){
    if(ready)await page.locator(ready).first().waitFor();
    await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
    await page.screenshot({path:path.join(directory,slug+'.png'),fullPage:true});
    entries.push({slug,title,description});
  }
  try{
    await page.setViewportSize({width:1440,height:1000});
    await field('外观').selectOption('light');
    await field('归档日期').fill('2026-09-20');await button('查看归档').click();
    await page.locator('#insight-snapshot').getByText('70%',{exact:true}).waitFor();
    await button('设为对比起点').click();await button('下一条观测').click();
    await page.locator('#insight-snapshot').getByText('69.99%',{exact:true}).waitFor();
    await button('与起点比较').click();await field('搜索历史参数').fill('chargeLevel');
    await capture('01-time-machine','车辆时间机','拖动时间轴，回看历史状态；挑两条观测看变化。','#insight-comparison [data-change]');

    await button('停车耗电').click();await field('开始日期').fill('2026-09-18');await field('结束日期').fill('2026-09-19');
    await button('分析停车观测').click();await button('查看区间详情').click();
    await capture('02-parking','停车耗电观察','查看一晚静置的 SOC 变化、温度和样本间隔；不完整区间单独标注。','#parking-detail');

    await button('周报与月报').click();await field('报告周期').selectOption('month');await field('周期内日期').fill('2026-09-20');
    await button('查看报告').click();await page.getByRole('heading',{name:'2026-09-01 — 2026-09-30',exact:true}).waitFor();
    await capture('03-reports','用车周报与月报','里程、充电、活动日期和上期对比，完整记录与观测片段分开统计。','[data-report-event]');

    await button('充电账本').click();await field('账本月份').fill('2026-09');await button('读取账本').click();
    await page.waitForFunction(()=>document.querySelector('#ledger-actual-total')?.textContent.includes('30.10'));
    await capture('04-charge-ledger','充电账本','关联充电记录，补录实际费用、桩端电量与电价；实际值和估算分列。','[data-ledger-entry]');

    await button('自定义提醒').click();
    await page.getByText('合成演示：低电量',{exact:true}).first().waitFor();
    await capture('05-reminders','自定义提醒','电量条件、连续确认、冷却与恢复，附规则预览和提醒历史。');

    await button('行程标签').click();await field('标签月份').fill('2026-09');await button('读取行程标签').click();
    await field('比较标签 A').selectOption('通勤');await field('比较标签 B').selectOption('接娃');
    await capture('06-trip-tags','行程标签与同类比较','为行程添加通勤、接娃等标签；对照同类距离、时长和 SOC 变化。','[data-tag-event]');

    await button('充电曲线对比').click();
    for(const side of ['A','B']){await field(`充电 ${side} 月份`).fill('2026-07');await button(`读取充电 ${side}`).click();}
    await field('充电记录 A').selectOption('curve-a');await field('充电记录 B').selectOption('curve-b');
    await button('比较这两次充电').click();await page.getByText('共同观测 SOC：30% — 80%',{exact:true}).waitFor();
    await field('外观').selectOption('dark');
    await capture('07-charge-comparison','充电曲线对比','共同 SOC 区间对照功率、温度和耗时；保留缺口与平台时间的不确定性。','[data-charge-chart]');

    await field('外观').selectOption('light');await button('参数实验室').click();await button('回看实验').click();
    await page.getByText(/保存时的观测摘录/).waitFor();
    await capture('08-experiments','车辆参数实验室','保存动作、前后样本和变化字段；研究线索保留原始摘录，不自动确认语义。','[data-lab-record]');

    await button('用车日历').click();await field('日历月份').fill('2026-09');await button('读取用车日历').click();
    await page.locator('[data-calendar-day="2026-09-19"]').click();
    await capture('09-calendar','用车日历','逐日查看行程、充电和停车观测；跨午夜、缺数据与未来日期清楚区分。','.calendar-panel');

    await button('生活账本').click();await field('生活账本月份').fill('2026-09');await button('读取生活账本').click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-life-expense]').length===3);
    await capture('10-vehicle-life','车辆生活账本','记录保险、停车、洗车等支出；另有日期或里程到期的保养待办。','[data-life-expense]');

    await button('数据质量雷达').click();await field('质量分析开始日期').fill('2026-09-18');await field('质量分析结束日期').fill('2026-09-20');
    await button('分析数据质量').click();await page.waitForFunction(()=>document.querySelector('#quality-totals')?.textContent.includes('236'));
    await capture('11-quality','数据质量雷达','查看读取延迟、新时间、修订、重复和缺口；覆盖统计不冒充车辆在线率。','.quality-delay-row');

    await button('行程卡片').click();await field('卡片记录月份').fill('2026-09');await button('读取卡片素材').click();
    await field('卡片行程').selectOption('report-trip');await field('卡片标题').fill('周末，慢一点');
    await field('卡片备注').fill('一段熟悉的路，一次轻松的出行。\n合成行程 · 仅供预览');
    await field('卡片外观').selectOption('dark');
    await capture('12-trip-cards','可分享行程卡片','选择行程、照片和备注，在浏览器内导出 PNG；地点默认隐藏。','#trip-card-canvas');
    const download=page.waitForEvent('download');await button('导出 PNG 图片').click();
    await (await download).saveAs(path.join(directory,'trip-card.png'));
    assert.deepEqual(f.posts,[]);assert.deepEqual(f.errors,[]);
    assert.ok(f.external.every(url=>url.startsWith('blob:'+f.origin)));
    const escape=s=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    fs.writeFileSync(path.join(directory,'index.html'),`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>用车研究 · 十二项功能预览</title>
<style>:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;background:#f2f5f3;color:#172c26;font:16px/1.65 system-ui,-apple-system,sans-serif}main{max-width:1180px;margin:auto;padding:52px 24px}h1{font-size:clamp(28px,4vw,46px);line-height:1.2;margin:14px 0 20px}h2{margin:16px 0 8px;font-size:22px}p{margin:8px 0}a{color:#075a46}header{max-width:800px;margin-bottom:32px}.label{font-weight:700;letter-spacing:.12em;font-size:13px;color:#416155}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}article{background:#fff;border:1px solid #d6e1db;border-radius:18px;overflow:hidden}article>a{display:block;border-bottom:1px solid #d6e1db;background:#e9efeb}img{display:block;width:100%;height:330px;object-fit:cover;object-position:top}.copy{padding:4px 24px 24px}.copy p{color:#475f55}footer{margin-top:32px;padding:24px;border-radius:18px;background:#e3ece6}code{overflow-wrap:anywhere}a:focus-visible{outline:3px solid #1d876b;outline-offset:4px}@media(max-width:720px){main{padding:28px 16px}.grid{grid-template-columns:1fr}img{height:270px}}@media(prefers-color-scheme:dark){body{background:#10211c;color:#e5f1ea}article{background:#182e25;border-color:#3a5047}.copy p{color:#bbcec1}a{color:#a4e4c3}.label{color:#a7c5b6}article>a{border-color:#3a5047}footer{background:#1c362b}}</style>
<main><header><div class="label">ZEEKR / LOCAL REVIEW / 2026.09.20</div><h1>十二项用车研究工具</h1><p>从历史回看，到日常记录。功能已接入现有网页的「用车研究」。这里全部为合成数据截图，点击图片可看完整页面。</p><p><strong>本地实现与测试已完成。发布状态见交付说明。</strong>预览费用、里程、照片和事件均不代表真实车辆。</p><p><a href="trip-card.png">查看导出的行程卡片</a> · <a href="../vehicle-insights-delivery-2026-09-20.md">交付与验收说明</a></p></header><section class="grid">${entries.map((e,i)=>`<article><a href="${e.slug}.png" aria-label="查看${escape(e.title)}完整截图"><img src="${e.slug}.png" alt="${escape(e.title)}合成数据预览" loading="lazy"></a><div class="copy"><h2>${String(i+1).padStart(2,'0')} · ${escape(e.title)}</h2><p>${escape(e.description)}</p></div></article>`).join('')}</section><footer><strong>动手试</strong><p>在项目目录运行 <code>PYTHONDONTWRITEBYTECODE=1 python3 tests/insights_fixture.py --demo</code>，打开打印端口对应的 <code>http://127.0.0.1:端口</code>，点「用车研究」。一般选 2026 年 9 月；充电曲线选 2026 年 7 月；停车选 9 月 18–19 日。</p><p>演示数据存入临时目录；退出服务后不保留。没有真实账号、车辆请求或通知发送。</p></footer></main></html>`);
    console.log('INSIGHTS_DEMO_PASS: 12 clean screenshots, local PNG export and review gallery; synthetic service only');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

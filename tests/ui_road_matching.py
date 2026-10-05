from playwright.sync_api import sync_playwright
import subprocess,os
from pathlib import Path
root=Path(__file__).resolve().parents[1];env={**os.environ,'PYTHONPATH':str(root)}
server=subprocess.Popen([os.environ.get('FIXTURE_PYTHON','python3'),str(root/'tests/road_matching_fixture.py')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=root,env=env)
try:
    port=int(server.stdout.readline())
    with sync_playwright() as p:
        b=p.chromium.launch(**({'executable_path':os.environ['CHROMIUM_EXECUTABLE']} if os.environ.get('CHROMIUM_EXECUTABLE') else {}),headless=True)
        page=b.new_page(viewport={'width':1440,'height':1050});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('https://**.is.autonavi.com/**',lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/></svg>'))
        page.goto(f'http://127.0.0.1:{port}');page.get_by_role('button',name='隐藏位置',exact=True).first.click()
        page.get_by_role('button',name='行程与轨迹',exact=True).first.click();page.get_by_label('轨迹日期').fill('2024-01-02');page.get_by_role('button',name='查询行程',exact=True).click()
        page.locator('[data-local-trip="road-trip"]').click();page.get_by_role('button',name='显示位置并加载地图',exact=True).click()
        page.wait_for_selector('path.route-matched-road',state='attached');state=page.evaluate('localTrips.route')
        assert state['count']==5 and state['road_matching']['matched_indices']==[0,1,2,3,4]
        assert state['road_matching']['spans']==[[0,1],[1,2],[3,4]]
        assert len(state['gaps'])==1 and len(state['segments'])==2
        assert page.locator('path.route-sparse-line').count()==0
        assert '算法推断' in page.locator('.route-match-status').inner_text()
        page.get_by_role('button',name='下一点',exact=True).click();before=page.locator('#playback').input_value()
        page.evaluate('window.__roadMap=map');page.evaluate('loadLocalRoute(true)');page.wait_for_timeout(150)
        assert page.locator('#playback').input_value()==before and page.evaluate('map===window.__roadMap')
        out=Path(os.environ['ROAD_MATCH_SCREENSHOTS']) if os.environ.get('ROAD_MATCH_SCREENSHOTS') else None
        if out:
            out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/'integrated-road-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        if out:page.screenshot(path=str(out/'integrated-road-mobile.png'),full_page=True)
        page.get_by_role('button',name='隐藏位置',exact=True).last.click();assert page.locator('path.route-matched-road').count()==0
        assert not errors,errors;b.close()
    print('ROAD_UI_PASS real_API/road_geometry/gaps/source_replay/refresh/hide/mobile')
finally:
    server.terminate();server.wait(timeout=5)

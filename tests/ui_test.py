import os
SHOTS = os.environ.get("SA_SHOTS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")); os.makedirs(SHOTS, exist_ok=True)
LAUNCH = {"executable_path": os.environ["CHROME"]} if os.environ.get("CHROME") else {}
import asyncio, json
from playwright.async_api import async_playwright
BASE = "http://127.0.0.1:8799"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(**LAUNCH, args=['--no-sandbox'])
        pg = await b.new_page(viewport={'width': 1440, 'height': 900})
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('console', lambda m: errs.append('console:' + m.text) if m.type == 'error' else None)
        await pg.goto(BASE); await pg.wait_for_timeout(1200)
        await pg.screenshot(path=SHOTS + '/ui_home0.png')
        # add model via UI
        await pg.goto(BASE + '/#models'); await pg.wait_for_timeout(800)
        await pg.select_option('#mPreset', 'deepseek')
        await pg.fill('#mName', '模拟 DeepSeek'); await pg.fill('#mUrl', 'http://127.0.0.1:9912/v1'); await pg.fill('#mKey', 'good-key')
        await pg.click('#mAdd'); await pg.wait_for_timeout(800)
        await pg.click('[data-mt]'); await pg.wait_for_timeout(1500)
        print('model test:', await pg.inner_text('[id^=mt-]'))
        await pg.screenshot(path=SHOTS + '/ui_models.png', full_page=True)
        # lesson
        await pg.goto(BASE + '/#lesson-2'); await pg.wait_for_timeout(800)
        await pg.screenshot(path=SHOTS + '/ui_lesson.png')
        # question code
        await pg.goto(BASE + '/#q-p22'); await pg.wait_for_timeout(900)
        await pg.fill('#code', 'def solve(r):\n    res=[0]*len(r);st=[]\n    for i,x in enumerate(r):\n        while st and r[st[-1]]<x:\n            j=st.pop();res[j]=i-j\n        st.append(i)\n    return res\n')
        await pg.click('#submit'); await pg.wait_for_timeout(2000)
        print('submit:', (await pg.inner_text('#res'))[:100].replace('\n', ' '))
        await pg.click('[data-ai="hint"]'); await pg.wait_for_timeout(1500)
        print('ai hint:', (await pg.inner_text('#aiOut'))[:80].replace('\n', ' '))
        await pg.screenshot(path=SHOTS + '/ui_q.png', full_page=True)
        # import via UI
        await pg.goto(BASE + '/#import'); await pg.wait_for_timeout(600)
        await pg.fill('#iText', '一些题目……'); await pg.fill('#iSrc', '测试导入')
        await pg.click('#iRun'); await pg.wait_for_timeout(3500)
        await pg.screenshot(path=SHOTS + '/ui_import.png', full_page=True)
        await pg.click('#iSave'); await pg.wait_for_timeout(1200)
        # single choice question imported
        qs = await pg.evaluate("api('/api/questions?type=single')")
        qid = qs[0]['id']
        await pg.goto(BASE + '/#q-' + qid); await pg.wait_for_timeout(800)
        await pg.click('.opt-row >> nth=1'); await pg.click('#submit'); await pg.wait_for_timeout(800)
        print('single:', (await pg.inner_text('#res'))[:60].replace('\n', ' '))
        await pg.screenshot(path=SHOTS + '/ui_single.png', full_page=True)
        # chat with tool + proposal
        await pg.goto(BASE + '/#chat'); await pg.wait_for_timeout(800)
        await pg.fill('#cin', '今天做什么？'); await pg.click('#csend'); await pg.wait_for_timeout(2500)
        await pg.wait_for_selector('#cin:not([disabled])', timeout=20000); await pg.fill('#cin', '帮我调整我的计划'); await pg.click('#csend'); await pg.wait_for_timeout(2500)
        await pg.screenshot(path=SHOTS + '/ui_chat.png', full_page=True)
        await pg.click('[data-pok] >> nth=0'); await pg.wait_for_timeout(800)
        print('goal hours after confirm:', (await pg.evaluate("api('/api/plan')"))['goal']['hours'])
        # exam flow
        await pg.goto(BASE + '/#exams'); await pg.wait_for_timeout(800)
        await pg.select_option('#eScope', 'all'); await pg.click('#eCreate'); await pg.wait_for_timeout(1200)
        await pg.click('#exStart'); await pg.wait_for_timeout(1200)
        await pg.screenshot(path=SHOTS + '/ui_exam.png')
        await pg.fill('#eCode', 'def solve(*a):\n    return 0\n'); await pg.wait_for_timeout(2200)
        await pg.click('#eSubmit'); await pg.click('#eSubmit'); await pg.wait_for_timeout(4000)
        await pg.screenshot(path=SHOTS + '/ui_report.png', full_page=True)
        # plan, bank, review, resources, settings, classify
        for h in ['plan', 'bank', 'review', 'resources', 'settings', 'classify', 'newq', 'home']:
            await pg.goto(BASE + '/#' + h); await pg.wait_for_timeout(900)
            await pg.screenshot(path=SHOTS + f'/ui_{h}.png', full_page=(h in ('bank',)))
        # mobile
        await pg.set_viewport_size({'width': 390, 'height': 844})
        for h in ['home', 'q-p22', 'chat']:
            await pg.goto(BASE + '/#' + h); await pg.wait_for_timeout(900)
            sw = await pg.evaluate("document.documentElement.scrollWidth")
            print('mobile', h, 'scrollWidth', sw)
            await pg.screenshot(path=SHOTS + f'/ui_m_{h}.png')
        print('ERRORS:', errs[:10])
        await b.close()
asyncio.run(main())

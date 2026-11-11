import os
SHOTS = os.environ.get("SA_SHOTS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")); os.makedirs(SHOTS, exist_ok=True)
LAUNCH = {"executable_path": os.environ["CHROME"]} if os.environ.get("CHROME") else {}
import asyncio
from playwright.async_api import async_playwright
BASE = "http://127.0.0.1:8799"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(**LAUNCH, args=['--no-sandbox'])
        pg = await b.new_page(viewport={'width': 1440, 'height': 900})
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(BASE); await pg.wait_for_timeout(1000)
        await pg.evaluate("api('/api/models',{body:{preset:'deepseek',name:'模拟',base_url:'http://127.0.0.1:9912/v1',api_key:'good-key'}})")
        await pg.evaluate("reloadBoot()")
        await pg.goto(BASE + '/#chat-planner'); await pg.wait_for_timeout(800)
        await pg.fill('#cin', '请慢一点讲讲计划'); await pg.press('#cin', 'Enter'); await pg.wait_for_timeout(1200)
        print('input locked while generating:', await pg.is_disabled('#cin'), '| stop visible:', await pg.is_visible('#cstop'))
        await pg.goto(BASE + '/#bank'); await pg.wait_for_timeout(1000)
        print('nav shows:', await pg.inner_text('#cntProp'))
        await pg.goto(BASE + '/#home'); await pg.wait_for_timeout(800)
        await pg.go_back(); await pg.go_back(); await pg.wait_for_timeout(500)   # back to the chat
        print('url:', pg.url)
        await pg.wait_for_timeout(5000)
        txt = await pg.inner_text('#chat')
        print('reply count of 分步回答:', txt.count('分步回答'), '| input enabled again:', not await pg.is_disabled('#cin'))
        await pg.screenshot(path=SHOTS + '/ui_chat_back.png')
        # full reload mid-generation
        await pg.fill('#cin', '请慢一点再讲'); await pg.press('#cin', 'Enter'); await pg.wait_for_timeout(1000)
        await pg.reload(); await pg.wait_for_timeout(6000)
        txt = await pg.inner_text('#chat')
        print('after reload reply complete:', txt.count('分步回答') >= 24)
        # empty reply case shows recovered answer
        await pg.fill('#cin', '空回复测试'); await pg.press('#cin', 'Enter'); await pg.wait_for_timeout(2500)
        print('empty recovered:', '补充回答' in await pg.inner_text('#chat'))
        await pg.screenshot(path=SHOTS + '/ui_chat_final.png')
        print('ERRORS:', errs)
        await b.close()
asyncio.run(main())

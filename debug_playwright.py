from playwright.sync_api import sync_playwright

URL = 'https://www.flashscore.es/'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1200})
    page.goto(URL, wait_until='domcontentloaded', timeout=45000)

    for selector in [
        '#onetrust-accept-btn-handler',
        'button:has-text("Aceptar")',
        'button:has-text("Acepto")',
        'button:has-text("Consentir")',
    ]:
        try:
            page.locator(selector).click(timeout=3000)
            print('aviso aceptado con:', selector)
            break
        except Exception:
            pass

    try:
        odds_tab = page.locator('[data-analytics-alias="odds"]')
        odds_tab.wait_for(state='visible', timeout=15000)
        print('TAB CUOTAS ENCONTRADO:', odds_tab.count())
        odds_tab.click()
        page.wait_for_timeout(4000)
        print('URL DESPUES DEL CLICK:', page.url)
        page.screenshot(path='flashscore_cuotas.png', full_page=True)
        open('debug_pw_odds.html', 'w', encoding='utf-8').write(page.content())
    except Exception as error:
        print('NO SE ENCONTRO EL TAB CUOTAS:', error)
        page.screenshot(path='flashscore_sin_cuotas.png', full_page=True)

    browser.close()

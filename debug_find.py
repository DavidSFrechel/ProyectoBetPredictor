import re
html = open('debug_pw_odds.html', encoding='utf-8').read()
# buscar filas de partido con /partido/ID y cuotas cerca
for m in list(re.finditer(r'/partido/([A-Za-z0-9]+)/', html))[:3]:
    idx = m.start()
    print(html[max(0,idx-500):idx+800])
    print('=====')

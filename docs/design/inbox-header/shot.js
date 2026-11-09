const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1296, height: 900 }, deviceScaleFactor: 2 });
  await p.goto('file://' + __dirname + '/mock.html');
  const names = ['0-today', 'A-one-bar', 'B-named-platforms', 'C-filter-sheet-and-switch'];
  const els = await p.$$('.sheet');
  for (let i = 0; i < els.length; i++) await els[i].screenshot({ path: `${__dirname}/${names[i]}.png` });
  await b.close();
})();

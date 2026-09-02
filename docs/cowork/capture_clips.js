const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const scenes = [
    { s: 'title', n: 90 },
    { s: 'stock', n: 190 },
    { s: 'fp', n: 190 },
    { s: 'env', n: 150 },
    { s: 'use', n: 150 },
  ];
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  await page.goto('file:///home/claude/clips.html');
  await page.waitForFunction(() => typeof window.setFrame === 'function');
  const el = await page.$('#c');
  for (const sc of scenes) {
    const dir = `/home/claude/fr_${sc.s}`;
    fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir);
    for (let i = 0; i < sc.n; i++) {
      await page.evaluate(({ s, f, n }) => window.setFrame(s, f, n), { s: sc.s, f: i, n: sc.n });
      await el.screenshot({ path: `${dir}/f_${String(i).padStart(4, '0')}.png` });
    }
    console.log('done', sc.s, sc.n);
  }
  await browser.close();
})();

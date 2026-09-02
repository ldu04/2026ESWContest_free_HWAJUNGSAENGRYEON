const { chromium } = require('playwright');
(async () => {
  const N = 150;
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
  await page.goto('file:///home/claude/concept_anim.html');
  await page.waitForFunction(() => typeof window.setFrame === 'function');
  const fs = require('fs');
  if (!fs.existsSync('/home/claude/frames')) fs.mkdirSync('/home/claude/frames');
  const el = await page.$('#c');
  for (let i = 0; i < N; i++) {
    await page.evaluate(({f, n}) => window.setFrame(f, n), {f: i, n: N});
    await el.screenshot({ path: `/home/claude/frames/f_${String(i).padStart(4,'0')}.png` });
  }
  await browser.close();
  console.log('CAPTURED', N, 'frames');
})();

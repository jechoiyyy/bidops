import { chromium } from 'playwright';
const dir = process.argv[2];
const b = await chromium.launch();
for (const [f, h] of [['PreSpecDetail', 2560], ['Dashboard', 889], ['OrderPlans', 889], ['Opportunities', 889], ['GoNoGo', 889], ['Criteria', 889], ['RunStatus', 889]]) {
  const p = await b.newPage({ viewport: { width: 1422, height: h } });
  await p.goto('file://' + dir + '/' + f + '.dc.html');
  await p.waitForTimeout(1000);
  await p.screenshot({ path: dir + '/../shots/' + f + '.png' });
  await p.close();
}
await b.close();
